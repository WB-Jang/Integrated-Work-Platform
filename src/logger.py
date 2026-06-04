"""
애플리케이션 로거 설정.
logs/ 폴더에 일별 로그 파일이 쌓입니다.

멀티유저 환경: ContextVar 로 현재 요청의 사용자 이니셜을 보관하여 모든 로그
레코드에 자동으로 [USER:XXX] 토큰이 붙도록 합니다.
"""
import logging
import os
from contextvars import ContextVar
from logging.handlers import TimedRotatingFileHandler

_loggers: dict[str, logging.Logger] = {}

# 현재 요청/태스크 컨텍스트의 사용자 이니셜
_current_user: ContextVar[str] = ContextVar("current_user", default="-")

# 클라이언트(브라우저 연결)별 사용자 등록부.
# ContextVar 는 페이지 핸들러 task 안에서만 유효하고, 이후 버튼 클릭·타이머 등
# 별도 task/컨텍스트로 실행되는 이벤트 핸들러에는 전파되지 않는다(→ USER:- 로 남음).
# 이를 보완하기 위해 NiceGUI client.id → 사용자 매핑을 따로 두고, 로그 시점에
# 현재 클라이언트로부터 사용자를 자동 해석한다.
_client_users: dict[str, str] = {}


_EMPTY_STRINGS = frozenset({"null", "none", "undefined", "nan", ""})

def _norm(initials: str) -> str:
    v = (initials or "").strip().upper()[:16]
    return "-" if v.lower() in _EMPTY_STRINGS else (v or "-")


def set_current_user(initials: str) -> None:
    """현재 컨텍스트(요청·태스크)의 사용자 이니셜을 설정.
    NiceGUI 페이지 핸들러나 액션 콜백 진입 시 호출하면, 같은 asyncio task 안에서
    실행되는 모든 후속 로그에 자동 첨부됩니다.
    """
    _current_user.set(_norm(initials))


def register_client_user(client_id, initials: str) -> None:
    """NiceGUI 클라이언트 연결에 사용자 이니셜을 등록(페이지 진입 시 1회)."""
    if client_id is not None:
        _client_users[str(client_id)] = _norm(initials)


def unregister_client_user(client_id) -> None:
    _client_users.pop(str(client_id), None)


def get_current_user() -> str:
    return _resolve_user()


def _resolve_user() -> str:
    """로그에 붙일 사용자 해석. 우선순위:
    1) ContextVar(핸들러가 명시 설정) → 2) 현재 NiceGUI 클라이언트 등록부 → 3) "-".
    """
    u = _current_user.get()
    if u and u != "-":
        return u
    try:
        from nicegui import context, core
        # 서버 시작 전(모듈 임포트 단계의 로깅)에는 context.client 에 접근하면
        # NiceGUI 가 임시 pseudo-client 를 생성하면서 script_mode 가 켜진다.
        # 이후 @ui.page 가 있는 스크립트에서는 ui.run() 이
        # "ui.page cannot be used ... when UI is defined in the global scope"
        # 오류를 던지므로, 서버가 실제로 시작된 뒤에만 클라이언트를 조회한다.
        if core.app.is_started:
            cid = getattr(context.client, "id", None)
            if cid is not None:
                cu = _client_users.get(str(cid))
                if cu:
                    return cu
    except Exception:
        pass
    return u or "-"


class _UserContextFilter(logging.Filter):
    """모든 LogRecord 에 `user` 속성을 추가하는 필터."""
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.user = _resolve_user()
        except Exception:
            record.user = "-"
        return True


def get_logger(name: str = "app") -> logging.Logger:
    """
    지정된 이름의 로거를 반환합니다.
    첫 호출 시 logs/ 폴더에 일별 로테이팅 파일 핸들러를 설정합니다.
    """
    if name in _loggers:
        return _loggers[name]

    log_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "logs"
    )
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        fmt = logging.Formatter(
            "%(asctime)s [%(name)s] [USER:%(user)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # 일별 로테이팅 파일 핸들러 (자정 교체, 30일 보관)
        file_handler = TimedRotatingFileHandler(
            filename=os.path.join(log_dir, f"{name}.log"),
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
        )
        file_handler.suffix = "%Y-%m-%d"
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)

        # 콘솔 핸들러 (기존 print 출력 대체)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(fmt)
        logger.addHandler(console_handler)

        # 사용자 컨텍스트 필터 부착 (모든 핸들러 공통)
        logger.addFilter(_UserContextFilter())

    _loggers[name] = logger
    return logger
