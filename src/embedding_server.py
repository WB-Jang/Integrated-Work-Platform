"""
BGE-M3 임베딩 서버 (기본 포트 8081).
POST /v1/embeddings  — OpenAI-compatible
GET  /health
"""
import os
import sys

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()
_model = None


_MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "bge-m3")


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
def embeddings(req: EmbedRequest):
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
    # 모델 사전 로드 (서버 시작 시 1회)
    _get_model()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
