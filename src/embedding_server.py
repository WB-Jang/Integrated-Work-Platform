"""
BGE-M3 임베딩 서버 (기본 포트 8081).
POST /v1/embeddings  — OpenAI-compatible
GET  /health

환경변수:
  INFERENCE_API_KEY  — 설정 시 모든 요청에 Authorization: Bearer <key> 검증
  EMBEDDING_HOST     — 바인드 주소 (기본: 127.0.0.1, RunPod에서는 0.0.0.0)
"""
import os
import sys

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

app = FastAPI()
_model = None

_MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "bge-m3")
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
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(_MODEL_PATH)
    return _model


class EmbedRequest(BaseModel):
    model: str = "bge-m3"
    input: str | list


@app.post("/v1/embeddings")
def embeddings(req: EmbedRequest, request: Request):
    _check_auth(request)
    texts = [req.input] if isinstance(req.input, str) else list(req.input)
    m = _get_model()
    vecs = m.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return {
        "data": [{"embedding": v.tolist(), "index": i} for i, v in enumerate(vecs)],
        "model": req.model,
    }


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
    host = os.environ.get("EMBEDDING_HOST", "127.0.0.1")
    _get_model()
    uvicorn.run(app, host=host, port=port, log_level="warning")
