"""
RunPod Serverless 워커 핸들러.
BGE-M3 임베딩 + BGE-Reranker 리랭킹을 하나의 엔드포인트에서 처리한다.

요청 형식 (RunPod: {"input": {...}}):
  임베딩:  {"task": "embed",  "input": ["문장1", "문장2", ...]}
  리랭크:  {"task": "rerank", "query": "...", "candidates": ["후보1", ...]}

응답 형식:
  임베딩:  {"embeddings": [[...], [...]]}
  리랭크:  {"results": [{"text": "...", "score": 0.97}, ...]}

모델은 이미지에 미리 구워둔 /models/bge-m3, /models/bge-reranker 를 사용한다.
"""
import os

import runpod

MODEL_DIR = os.environ.get("MODEL_DIR", "/models")

_emb_model = None
_rerank_model = None


def _get_embed_model():
    global _emb_model
    if _emb_model is None:
        from sentence_transformers import SentenceTransformer
        _emb_model = SentenceTransformer(os.path.join(MODEL_DIR, "bge-m3"))
    return _emb_model


def _get_rerank_model():
    global _rerank_model
    if _rerank_model is None:
        from sentence_transformers import CrossEncoder
        _rerank_model = CrossEncoder(os.path.join(MODEL_DIR, "bge-reranker"))
    return _rerank_model


def handler(event):
    inp = event.get("input", {}) or {}
    task = inp.get("task", "embed")

    if task == "embed":
        texts = inp.get("input") or inp.get("texts") or []
        if isinstance(texts, str):
            texts = [texts]
        if not texts:
            return {"embeddings": []}
        model = _get_embed_model()
        vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return {"embeddings": [v.tolist() for v in vecs]}

    if task == "rerank":
        query = inp.get("query", "")
        candidates = inp.get("candidates", []) or []
        if not candidates:
            return {"results": []}
        model = _get_rerank_model()
        pairs = [[query, c] for c in candidates]
        scores = model.predict(pairs).tolist()
        ranked = sorted(zip(candidates, scores), key=lambda x: -x[1])
        return {"results": [{"text": t, "score": s} for t, s in ranked]}

    return {"error": f"unknown task: {task}"}


runpod.serverless.start({"handler": handler})
