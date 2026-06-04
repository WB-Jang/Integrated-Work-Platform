"""
LLM 백엔드 가용성 단일 진실 공급원 (Single Source of Truth)

폐쇄망 등 LLM 백엔드(로컬 llama-server / OpenAI / OpenRouter)가 전혀 연결되지 않은
환경에서, LLM 사용 기능에 "현재 LLM 서버가 부재" 안내를 일관되게 노출하기 위한 모듈.

app.py 와 각 패널 파일이 공통으로 import 한다 (순환 import 회피용 경량 모듈).

사용:
    import llm_status
    llm_status.detect(config)        # 서버 시작 시 1회
    if llm_status.is_available(): ...
    if not llm_status.guard(): return   # 액션 핸들러 진입부 가드 (팝업 후 False)
"""
import os
import socket
from urllib.parse import urlparse

from logger import get_logger

log = get_logger("llm_status")

# 모듈 전역 상태 (detect() 가 채움)
_AVAILABLE: bool = False
_PROVIDER: str = ""          # 'local' | 'openai' | 'openrouter' | ''
_DETECTED: bool = False

UNAVAILABLE_MSG = (
    "현재 LLM 서버가 연결되어 있지 않아 이 기능을 사용할 수 없습니다.\n\n"
    "로컬 LLM(llama-server) 또는 OpenRouter/OpenAI 연결이 필요합니다. "
    "관리자에게 LLM 서버 구성을 문의하세요."
)


def _is_port_open(base_url: str, timeout: float = 1.5) -> bool:
    """base_url(host:port)에 직접 TCP 연결이 가능한지 확인.

    로컬 llama-server(localhost) 점검용. 사내 프록시 환경에서 외부(OpenAI/OpenRouter)
    호스트는 직접 TCP 가 막혀 있어도 프록시 경유로는 접속되므로, 외부 점검에는
    _is_http_reachable() 를 사용해야 한다 (이 함수는 프록시를 거치지 않음).
    """
    try:
        parsed = urlparse(base_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def _is_http_reachable(base_url: str, timeout: float = 4.0) -> bool:
    """HTTP(S)_PROXY / NO_PROXY 환경을 존중하는 외부 엔드포인트 도달성 점검.

    사내 개발망은 보통 프록시(HTTPS_PROXY)를 통해서만 외부에 나갈 수 있어, 직접
    소켓 연결(_is_port_open)은 방화벽에 막혀 false-negative('폐쇄망' 오판)가 난다.
    requests 는 환경변수 프록시 설정을 자동 적용하므로 실제 LLM 클라이언트와 동일한
    경로로 도달성을 판단한다. 인증 없이 호출하므로 401/403/404 등 어떤 HTTP 응답이든
    '도달 가능'으로 간주한다 (연결 자체가 성립했다는 의미).
    """
    try:
        import requests
        requests.get(base_url, timeout=timeout)
        return True
    except Exception:
        return False


def detect(config: dict) -> bool:
    """LLM 백엔드 가용성을 1회 계산하여 모듈 전역에 저장.

    우선순위는 app.create_llm() 의 폴백 순서와 동일:
      1) 로컬 llama-server (committee_llm.base_url 또는 llm_base_url 포트 개방)
      2) OpenAI       (OPENAI_API_KEY 존재 AND api.openai.com:443 도달)
      3) OpenRouter   (OPENROUTER_API_KEY 존재 AND openrouter.ai:443 도달)

    외부(OpenAI/OpenRouter) 점검은 키가 있을 때만 시도하며, 폐쇄망에서는
    1.5s 타임아웃 후 False 로 처리된다. 서버 시작 시 1회만 호출되므로 비용은 무시 가능.
    """
    global _AVAILABLE, _PROVIDER, _DETECTED

    config = config or {}

    # 1) 로컬 llama-server
    committee_cfg = config.get("committee_llm", {})
    local_base_url = committee_cfg.get("base_url") or config.get(
        "llm_base_url", "http://localhost:8080/v1"
    )
    if _is_port_open(local_base_url):
        _AVAILABLE, _PROVIDER, _DETECTED = True, "local", True
        log.info("LLM 가용: 로컬 llama-server (%s)", local_base_url)
        return True

    # 2) OpenAI 직통
    openai_cfg = config.get("openai", {})
    openai_key = (openai_cfg.get("api_key") or os.environ.get("OPENAI_API_KEY", "")).strip()
    if openai_key:
        openai_base = openai_cfg.get("base_url", "https://api.openai.com/v1")
        if _is_http_reachable(openai_base):
            _AVAILABLE, _PROVIDER, _DETECTED = True, "openai", True
            log.info("LLM 가용: OpenAI (%s)", openai_base)
            return True

    # 3) OpenRouter
    openrouter_cfg = config.get("openrouter", {})
    openrouter_key = (
        openrouter_cfg.get("api_key") or os.environ.get("OPENROUTER_API_KEY", "")
    ).strip()
    if openrouter_key:
        openrouter_base = openrouter_cfg.get("base_url", "https://openrouter.ai/api/v1")
        if _is_http_reachable(openrouter_base):
            _AVAILABLE, _PROVIDER, _DETECTED = True, "openrouter", True
            log.info("LLM 가용: OpenRouter (%s)", openrouter_base)
            return True

    _AVAILABLE, _PROVIDER, _DETECTED = False, "", True
    log.warning("LLM 백엔드 미연결 — LLM 기능은 비활성화됩니다 (폐쇄망 모드).")
    return False


def is_available() -> bool:
    """현재 LLM 백엔드 가용 여부. detect() 미호출 시 보수적으로 False."""
    return bool(_AVAILABLE)


def provider() -> str:
    return _PROVIDER


def recheck(config: dict) -> bool:
    """가용성 재점검 (관리자 화면 등에서 사용)."""
    return detect(config)


def show_unavailable_dialog() -> None:
    """LLM 부재 안내 팝업(persistent dialog) 표시.

    NiceGUI 슬롯 컨텍스트 안에서 호출되어야 한다. 컨텍스트가 없으면 조용히 무시.
    """
    try:
        from nicegui import ui
    except Exception:
        return
    try:
        with ui.dialog() as dlg, ui.card().style(
            "min-width:360px;max-width:460px;padding:24px 22px;"
            "background:var(--bg);border:1px solid var(--border);border-radius:12px;"
        ):
            ui.html(
                '<div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">'
                '<span class="material-symbols-outlined" '
                'style="font-size:22px;color:#d97706;">cloud_off</span>'
                '<span style="font-size:15px;font-weight:700;color:var(--text);">'
                'LLM 서버 미연결</span>'
                '</div>'
                '<div style="font-size:13px;color:var(--text-2);line-height:1.6;'
                'white-space:pre-line;">'
                f'{UNAVAILABLE_MSG}'
                '</div>'
            )
            ui.button("확인", on_click=dlg.close).classes("btn-primary-mono w-full").style(
                "margin-top:16px;"
            )
        dlg.open()
    except Exception as e:
        log.warning("LLM 안내 팝업 표시 실패: %s", e)


def guard() -> bool:
    """LLM 액션 핸들러 진입부 가드.

    가용하면 True. 아니면 안내 팝업을 띄우고 False 를 반환한다.
    """
    if is_available():
        return True
    show_unavailable_dialog()
    return False
