"""
BGE-Reranker 리랭킹 서버 (기본 포트 8082).
POST /rerank
GET  /health
"""
import os
import sys

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()
_model = None


_MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "bge-reranker")


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
def rerank(req: RerankRequest):
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
    _get_model()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
