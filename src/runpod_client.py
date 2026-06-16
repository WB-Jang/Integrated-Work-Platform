"""
RunPod Serverless 클라이언트.
RUNPOD_ENDPOINT_ID 와 RUNPOD_API_KEY 환경변수가 설정되면 활성화된다.

- embed_texts(texts)  → list[list[float]]  (정규화된 임베딩)
- rerank(query, cands) → list[{"text", "score"}]

runsync 로 호출하되, cold start 로 즉시 완료되지 않으면 /status 폴링으로 대기한다.
"""
import os
import time

import requests


def _endpoint_id() -> str:
    return os.environ.get("RUNPOD_ENDPOINT_ID", "").strip()


def _api_key() -> str:
    return os.environ.get("RUNPOD_API_KEY", "").strip()


def serverless_enabled() -> bool:
    return bool(_endpoint_id() and _api_key())


def _base_url() -> str:
    return f"https://api.runpod.ai/v2/{_endpoint_id()}"


def _headers() -> dict:
    return {"Authorization": f"Bearer {_api_key()}"}


def _call(payload: dict, timeout: int = 180) -> dict:
    """RunPod 엔드포인트 호출. COMPLETED 시 output(dict) 반환."""
    base = _base_url()
    headers = _headers()

    r = requests.post(
        f"{base}/runsync",
        json={"input": payload},
        headers=headers,
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    status = data.get("status")

    if status == "COMPLETED":
        return data.get("output", {})

    # cold start 등으로 큐/진행 중이면 폴링
    job_id = data.get("id")
    if status in ("IN_QUEUE", "IN_PROGRESS") and job_id:
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(2)
            s = requests.get(f"{base}/status/{job_id}", headers=headers, timeout=30).json()
            st = s.get("status")
            if st == "COMPLETED":
                return s.get("output", {})
            if st in ("FAILED", "CANCELLED", "TIMED_OUT"):
                raise RuntimeError(f"RunPod job {st}: {s}")
        raise TimeoutError("RunPod job polling timed out")

    raise RuntimeError(f"RunPod unexpected response: {data}")


def embed_texts(texts: list[str], timeout: int = 180) -> list[list[float]]:
    out = _call({"task": "embed", "input": texts}, timeout=timeout)
    return out.get("embeddings", [])


def rerank(query: str, candidates: list[str], timeout: int = 180) -> list[dict]:
    out = _call({"task": "rerank", "query": query, "candidates": candidates}, timeout=timeout)
    return out.get("results", [])
