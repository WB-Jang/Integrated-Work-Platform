# RunPod Serverless 워커 이미지
# BGE-M3 임베딩 + BGE-Reranker 리랭킹을 하나의 핸들러에서 서빙.
#
# 빌드(로컬 Docker 사용 시):
#   docker build -t <user>/iwp-embed-rerank:latest -f runpod_serverless/Dockerfile .
#   docker push <user>/iwp-embed-rerank:latest
#
# GitHub 연동 빌드 시: RunPod 콘솔에서 이 Dockerfile 경로를 지정.

FROM runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04

ENV PIP_NO_CACHE_DIR=1 \
    MODEL_DIR=/models \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ── 의존성 ───────────────────────────────────────────────
COPY runpod_serverless/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# ── 모델 굽기 (cold start 가속) ──────────────────────────
COPY runpod_serverless/download_models.py /app/download_models.py
RUN python /app/download_models.py

# ── 핸들러 ───────────────────────────────────────────────
COPY runpod_serverless/handler.py /app/handler.py

CMD ["python", "-u", "/app/handler.py"]
