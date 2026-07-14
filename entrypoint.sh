#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Integrated Work Platform — HF Spaces entrypoint
#
# 1) embedding_server (8081) 백그라운드 기동  ← RunPod 서버리스/원격 사용 시 생략
# 2) rerank_server   (8082) 백그라운드 기동  ← RunPod 서버리스/원격 사용 시 생략
# 3) NiceGUI app     (7860) 포그라운드 실행  ← 이 프로세스가 죽으면 컨테이너 종료
# ──────────────────────────────────────────────────────────────────────────────

# ── 조기 진단 하트비트 (무조건 최우선 출력) ─────────────────────────────────
printf '===[entrypoint] START pid=%s user=%s ===\n' "$$" "$(id -un 2>/dev/null)"

set -e

APP_PORT="${APP_PORT:-7860}"
EMBED_PORT="${EMBED_PORT:-8081}"
RERANK_PORT="${RERANK_PORT:-8082}"

cd /app
echo "[startup] cd /app OK  APP_PORT=${APP_PORT}"
echo "[startup] OPENROUTER_API_KEY=$( [ -n \"${OPENROUTER_API_KEY}\" ] && echo set || echo MISSING )"
echo "[startup] NICEGUI_STORAGE_SECRET=$( [ -n \"${NICEGUI_STORAGE_SECRET}\" ] && echo set || echo MISSING )"

# ── RunPod Serverless 감지 ──────────────────────────────────────────────────
# RUNPOD_ENDPOINT_ID + RUNPOD_API_KEY 가 설정되면 앱이 임베딩/리랭크를 RunPod
# Serverless 로 오프로딩하므로, 컨테이너 내부 로컬 모델 서버는 불필요하다.
# (로컬 서버는 __main__ 에서 BGE-M3 + BGE-reranker 각 ~2.3GB 를 즉시 로드 →
#  HF 컨테이너 RAM 초과 시 OOM 으로 :7860 바인딩 실패 → Starting 에서 멈춤.)
RUNPOD_SERVERLESS=false
if [ -n "${RUNPOD_ENDPOINT_ID}" ] && [ -n "${RUNPOD_API_KEY}" ]; then
    RUNPOD_SERVERLESS=true
    echo "[startup] RunPod Serverless 감지 → 로컬 임베딩/리랭크 서버 생략"
fi

# ── 1) 임베딩 서버 ──────────────────────────────────────────────────────────
if [ -n "${EMBEDDING_SERVER_URL}" ] || [ "${RUNPOD_SERVERLESS}" = true ]; then
    echo "[startup] 로컬 임베딩 서버 생략 (원격/서버리스 사용)"
    EMBED_PID=""
else
    python /app/src/embedding_server.py "${EMBED_PORT}" \
        > /app/logs/embedding_server.log 2>&1 &
    EMBED_PID=$!
    echo "[startup] embedding_server PID=${EMBED_PID} (port ${EMBED_PORT})"
fi

# ── 2) 리랭크 서버 ──────────────────────────────────────────────────────────
if [ -n "${RERANK_SERVER_URL}" ] || [ "${RUNPOD_SERVERLESS}" = true ]; then
    echo "[startup] 로컬 리랭크 서버 생략 (원격/서버리스 사용)"
    RERANK_PID=""
else
    python /app/src/rerank_server.py "${RERANK_PORT}" \
        > /app/logs/rerank_server.log 2>&1 &
    RERANK_PID=$!
    echo "[startup] rerank_server   PID=${RERANK_PID} (port ${RERANK_PORT})"
fi

# 로컬 서버가 실행된 경우에만 준비 대기 (최대 60초)
if [ -n "${EMBED_PID}" ] || [ -n "${RERANK_PID}" ]; then
    for i in $(seq 1 30); do
        EMBED_OK=true
        RERANK_OK=true
        [ -n "${EMBED_PID}" ] && ! curl -sf "http://127.0.0.1:${EMBED_PORT}/health" > /dev/null 2>&1 && EMBED_OK=false
        [ -n "${RERANK_PID}" ] && ! curl -sf "http://127.0.0.1:${RERANK_PORT}/health" > /dev/null 2>&1 && RERANK_OK=false
        if $EMBED_OK && $RERANK_OK; then
            echo "[startup] embedding + rerank ready (after ${i}x2s)"
            break
        fi
        sleep 2
    done
fi

# 자식 프로세스 정리 트랩
cleanup() {
    echo "[shutdown] killing children..."
    [ -n "${EMBED_PID}" ] && kill "${EMBED_PID}" 2>/dev/null || true
    [ -n "${RERANK_PID}" ] && kill "${RERANK_PID}" 2>/dev/null || true
    wait 2>/dev/null || true
    exit 0
}
trap cleanup TERM INT

# ── 3) NiceGUI 앱 (포그라운드) ──────────────────────────────────────────────
# exec 대신 직접 실행하여 종료코드를 로깅. 앱이 비정상 종료해도 컨테이너를 유지해
# HF container logs 에서 트레이스백을 확인할 수 있게 한다(crash-loop 로그 유실 방지).
echo "[startup] launching NiceGUI app on :${APP_PORT} (python -u)"
set +e
python -u /app/src/app.py
APP_EXIT=$?
set -e
echo "[startup] ⚠ NiceGUI app exited with code=${APP_EXIT}"
if [ "${APP_EXIT}" != "0" ]; then
    echo "[startup] ⚠ 앱 비정상 종료 — 진단용으로 컨테이너를 유지합니다. 위 트레이스백을 확인하세요."
    tail -f /dev/null
fi
