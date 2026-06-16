#!/bin/bash
# ============================================================
# RunPod GPU 서버 시작 스크립트
# BGE-M3 임베딩 서버 (8081) + BGE-Reranker 서버 (8082)
#
# 필수 환경변수 (RunPod Pod 설정 > Environment Variables):
#   INFERENCE_API_KEY  — HuggingFace Space와 공유하는 인증 키
#
# 선택 환경변수:
#   HF_TOKEN           — 비공개 모델 접근 시 필요 (BAAI 모델은 공개라 불필요)
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_DIR="${SCRIPT_DIR}/models"
SRC_DIR="${SCRIPT_DIR}/src"

echo "=== RunPod 임베딩/리랭크 서버 시작 ==="
echo "작업 디렉토리: ${SCRIPT_DIR}"

# ── 의존성 설치 ────────────────────────────────────────────
echo "[1/4] pip 패키지 설치 중..."
# transformers 4.44.x 까지는 PyTorch 2.1과 호환됨
# sentence-transformers 2.7.0은 transformers<5.0 범위 내에서 동작
pip install -q \
    "transformers==4.44.2" \
    "sentence-transformers==2.7.0" \
    fastapi \
    uvicorn \
    numpy

# ── 모델 다운로드 ──────────────────────────────────────────
# Network Volume을 사용하는 경우 이미 다운로드되어 있으면 건너뜀
echo "[2/4] 모델 확인/다운로드..."

if [ ! -d "${MODEL_DIR}/bge-m3" ] || [ -z "$(ls -A ${MODEL_DIR}/bge-m3 2>/dev/null)" ]; then
    echo "  BGE-M3 다운로드 중... (~2.3GB, 수 분 소요)"
    python -c "
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='BAAI/bge-m3',
    local_dir='${MODEL_DIR}/bge-m3',
    ignore_patterns=['*.ot', 'flax_model*', 'tf_model*', 'rust_model*'],
)
print('BGE-M3 다운로드 완료')
"
else
    echo "  BGE-M3: 이미 존재 (건너뜀)"
fi

if [ ! -d "${MODEL_DIR}/bge-reranker" ] || [ -z "$(ls -A ${MODEL_DIR}/bge-reranker 2>/dev/null)" ]; then
    echo "  BGE-Reranker 다운로드 중... (~570MB)"
    python -c "
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='BAAI/bge-reranker-v2-m3',
    local_dir='${MODEL_DIR}/bge-reranker',
    ignore_patterns=['*.ot', 'flax_model*', 'tf_model*', 'rust_model*'],
)
print('BGE-Reranker 다운로드 완료')
"
else
    echo "  BGE-Reranker: 이미 존재 (건너뜀)"
fi

# ── 서버 시작 ─────────────────────────────────────────────
echo "[3/4] 서버 시작..."

# RunPod에서 외부 접속을 위해 0.0.0.0 바인딩
export EMBEDDING_HOST="0.0.0.0"
export RERANK_HOST="0.0.0.0"

# INFERENCE_API_KEY 확인
if [ -z "${INFERENCE_API_KEY}" ]; then
    echo "⚠️  경고: INFERENCE_API_KEY 환경변수가 설정되지 않았습니다."
    echo "   RunPod Pod 설정 > Environment Variables에서 설정하세요."
fi

cd "${SCRIPT_DIR}"

# 임베딩 서버 백그라운드 실행
python "${SRC_DIR}/embedding_server.py" 8081 &
EMB_PID=$!
echo "  임베딩 서버 PID: ${EMB_PID} (포트 8081)"

# 리랭크 서버 백그라운드 실행
python "${SRC_DIR}/rerank_server.py" 8082 &
RERANK_PID=$!
echo "  리랭크 서버 PID: ${RERANK_PID} (포트 8082)"

# ── 헬스체크 ──────────────────────────────────────────────
echo "[4/4] 서버 준비 대기 중..."
MAX_WAIT=180
WAITED=0

for PORT in 8081 8082; do
    while true; do
        if curl -sf "http://localhost:${PORT}/health" > /dev/null 2>&1; then
            echo "  ✅ 포트 ${PORT} 준비 완료"
            break
        fi
        if [ ${WAITED} -ge ${MAX_WAIT} ]; then
            echo "  ❌ 포트 ${PORT} 시작 실패 (${MAX_WAIT}초 초과)"
            exit 1
        fi
        sleep 5
        WAITED=$((WAITED + 5))
        echo "  대기 중... (${WAITED}s / ${MAX_WAIT}s)"
    done
done

echo ""
echo "=== 서버 준비 완료 ==="
echo "RunPod 콘솔에서 아래 포트의 Public URL을 확인하세요:"
echo "  임베딩: 포트 8081  → EMBEDDING_SERVER_URL"
echo "  리랭크: 포트 8082  → RERANK_SERVER_URL  (URL 끝에 /rerank 추가)"
echo ""
echo "HuggingFace Space Secrets에 설정할 값:"
echo "  EMBEDDING_SERVER_URL = https://<pod-id>-8081.proxy.runpod.net"
echo "  RERANK_SERVER_URL    = https://<pod-id>-8082.proxy.runpod.net/rerank"
echo "  INFERENCE_API_KEY    = (위에서 설정한 키)"
echo ""

# 프로세스 종료 시 자식 프로세스도 정리
trap "kill ${EMB_PID} ${RERANK_PID} 2>/dev/null" EXIT

# 두 서버 중 하나라도 종료되면 스크립트 종료
wait -n ${EMB_PID} ${RERANK_PID}
