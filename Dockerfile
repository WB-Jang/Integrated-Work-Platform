# ──────────────────────────────────────────────────────────────────────────────
# Integrated Work Platform — Hugging Face Spaces (Docker SDK)
#
# 구성
#   · Python 3.11 (slim)
#   · LibreOffice headless  → docx/pptx → pdf 변환 fallback
#   · BGE-M3 (임베딩) + BGE-Reranker-v2-m3  ← 빌드 시 다운로드 (캐시됨)
#   · embedding_server(8081) + rerank_server(8082) + NiceGUI(7860)
#
# 포트: HF Spaces 외부는 7860 만 노출. 8081/8082 는 컨테이너 내부에서만 사용.
# ──────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface \
    TRANSFORMERS_CACHE=/app/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/app/.cache/huggingface

# ── OS 패키지 ────────────────────────────────────────────────────────────────
# libreoffice         : Word/PPT → PDF 변환 (Windows COM 대체)
# poppler-utils       : pdf 텍스트 추출 보조
# fonts-noto-cjk*     : 한글/중국어/일본어 PDF 렌더링
# curl, git           : 모델 다운로드/헬스체크
# build-essential     : 일부 wheel 빌드 (faiss-cpu 등은 사전 빌드 wheel 사용)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice \
        libreoffice-l10n-ko \
        poppler-utils \
        fonts-noto-cjk fonts-noto-cjk-extra \
        curl git \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# ── 작업 디렉토리 — HF Spaces 권장 사용자(/home/user) ─────────────────────────
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH
WORKDIR /app

# ── 파이썬 의존성 ────────────────────────────────────────────────────────────
COPY --chown=user:user requirements-hf.txt /app/requirements-hf.txt
RUN pip install --user --upgrade pip \
    && pip install --user -r /app/requirements-hf.txt

# ── 모델 다운로드 (빌드 캐시 활용) ──────────────────────────────────────────
# requirements 변경 없으면 이 레이어가 캐시되어 재빌드 시 모델 재다운로드 없음.
COPY --chown=user:user download_models.py /app/download_models.py
RUN python /app/download_models.py

# ── FAISS 인덱스 빌드타임 생성 (재시작 루프 방지) ───────────────────────────
# legal_db/*_store.json → *_idx.index 를 빌드 단계에서 미리 임베딩하여 이미지에 굽는다.
# 이렇게 하면 컨테이너 기동 시 인덱스를 재구축할 필요가 없어 OOM/health-timeout
# 재시작 루프가 사라진다. (모델은 위 download_models.py 가 받아둔 /app/models/bge-m3 사용)
#
# ⚠ 캐시 전략: 이 RUN 의 입력(아래 3개 COPY)을 빌드에 꼭 필요한 것만으로 좁혀서,
#   legal_db(법령 store)나 빌더 코드가 바뀔 때만 재임베딩(≈수십 분)이 일어나고
#   app.py 등 일반 코드만 바꾸면 캐시가 유지되도록 한다.
#   build_legal_indexes 의 의존성: legal_db/*_store.json + legal_db_builder.py + logger.py
COPY --chown=user:user legal_db /app/legal_db
COPY --chown=user:user src/legal_db_builder.py src/logger.py /app/src/
COPY --chown=user:user scripts/build_legal_indexes.py /app/scripts/
RUN python /app/scripts/build_legal_indexes.py

# ── 나머지 애플리케이션 코드 복사 (자주 바뀜 → 맨 마지막) ───────────────────
# COPY 는 기존 파일을 덮어쓸 뿐 삭제하지 않으므로, 위에서 생성한 *.index 는 그대로 보존된다.
# (.dockerignore/.gitignore 로 빌드 컨텍스트에 *.index 가 없어 충돌 없음)
COPY --chown=user:user . /app

# 쓰기 가능 디렉토리 보장 (ephemeral) — 비루트 사용자 권한 안정성
RUN mkdir -p /app/logs /app/uploads /app/report_uploads /app/report_outputs

# HF Spaces 는 7860 노출
EXPOSE 7860

# 환경변수 기본값 (HF Secrets 로 오버라이드)
ENV HOST=0.0.0.0 \
    APP_PORT=7860

ENTRYPOINT ["/bin/bash", "/app/entrypoint.sh"]
