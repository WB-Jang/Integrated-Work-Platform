"""
BGE-Reranker 리랭킹 서버 (기본 포트 8082).
POST /rerank
GET  /health

환경변수:
  INFERENCE_API_KEY  — 설정 시 모든 요청에 Authorization: Bearer <key> 검증
  RERANK_HOST        — 바인드 주소 (기본: 127.0.0.1, RunPod에서는 0.0.0.0)
"""
import os
import sys

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

app = FastAPI()
_model = None

_MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "bge-reranker")
_API_KEY = os.environ.get("INFERENCE_API_KEY", "")


def _check_auth(request: Request):
    if not _API_KEY:
        return
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {_API_KEY}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import CrossEncoder
        _model = CrossEncoder(_MODEL_PATH)
    return _model


class RerankRequest(BaseModel):
    query: str
    candidates: list[str]


@app.post("/rerank")
def rerank(req: RerankRequest, request: Request):
    _check_auth(request)
    if not req.candidates:
        return {"results": []}
    m = _get_model()
    pairs = [[req.query, c] for c in req.candidates]
    scores = m.predict(pairs).tolist()
    ranked = sorted(zip(req.candidates, scores), key=lambda x: -x[1])
    return {"results": [{"text": t, "score": s} for t, s in ranked]}


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8082
    host = os.environ.get("RERANK_HOST", "127.0.0.1")
    _get_model()
    uvicorn.run(app, host=host, port=port, log_level="warning")
