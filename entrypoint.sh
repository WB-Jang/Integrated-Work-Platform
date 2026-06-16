#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Integrated Work Platform — HF Spaces entrypoint
#
# 1) embedding_server (8081) 백그라운드 기동
# 2) rerank_server   (8082) 백그라운드 기동
# 3) NiceGUI app     (7860) 포그라운드 실행  ← 이 프로세스가 죽으면 컨테이너 종료
# ──────────────────────────────────────────────────────────────────────────────
set -e

APP_PORT="${APP_PORT:-7860}"
EMBED_PORT="${EMBED_PORT:-8081}"
RERANK_PORT="${RERANK_PORT:-8082}"

cd /app

echo "[startup] BASE=$(pwd)"
echo "[startup] APP_PORT=${APP_PORT}  EMBED_PORT=${EMBED_PORT}  RERANK_PORT=${RERANK_PORT}"
echo "[startup] OPENROUTER_API_KEY=$( [ -n \"${OPENROUTER_API_KEY}\" ] && echo set || echo MISSING )"
echo "[startup] NICEGUI_STORAGE_SECRET=$( [ -n \"${NICEGUI_STORAGE_SECRET}\" ] && echo set || echo MISSING )"

# ── 1) 임베딩 서버 ──────────────────────────────────────────────────────────
# EMBEDDING_SERVER_URL이 설정되어 있으면 RunPod 외부 서버를 사용하므로 로컬 서버 생략
if [ -n "${EMBEDDING_SERVER_URL}" ]; then
    echo "[startup] EMBEDDING_SERVER_URL=${EMBEDDING_SERVER_URL} → 로컬 임베딩 서버 생략 (RunPod 사용)"
    EMBED_PID=""
else
    python /app/src/embedding_server.py "${EMBED_PORT}" \
        > /app/logs/embedding_server.log 2>&1 &
    EMBED_PID=$!
    echo "[startup] embedding_server PID=${EMBED_PID} (port ${EMBED_PORT})"
fi

# ── 2) 리랭크 서버 ──────────────────────────────────────────────────────────
# RERANK_SERVER_URL이 설정되어 있으면 RunPod 외부 서버를 사용하므로 로컬 서버 생략
if [ -n "${RERANK_SERVER_URL}" ]; then
    echo "[startup] RERANK_SERVER_URL=${RERANK_SERVER_URL} → 로컬 리랭크 서버 생략 (RunPod 사용)"
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
echo "[startup] launching NiceGUI app on :${APP_PORT}"
exec python /app/src/app.py
