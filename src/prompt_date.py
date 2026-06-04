"""
모든 LLM 프롬프트에 '오늘 날짜' 시스템 문구를 자동 주입.

각 기능(홈 챗·문서분석·법률검색·메일분석·규제동향·요약·에이전트)이 제각각 프롬프트를
만들기 때문에, 프롬프트마다 날짜를 넣는 대신 LLM 계층(ChatOpenAI)에서 한 번에 주입한다.
langchain 의 모든 호출 경로(invoke/ainvoke/stream/astream, 체인 포함)는 결국
ChatOpenAI._generate/_agenerate/_stream/_astream 로 수렴하므로, 이 네 메서드를
래핑하여 메시지 맨 앞에 '오늘 날짜' SystemMessage 를 끼워 넣는다.

install() 을 앱 시작 시 1회 호출하면 적용된다(모델 생성 이전이 아니어도 무방 —
클래스 메서드를 패치하므로 이미 만든 인스턴스에도 적용된다).
"""
from datetime import date

from logger import get_logger

log = get_logger("prompt_date")

# 중복 주입 방지용 마커
_DATE_MARKER = "[오늘 날짜]"


def today_note() -> str:
    """오늘 날짜 안내 문구(평문). 필요 시 직접 프롬프트에 넣을 수도 있음."""
    return (
        f"{_DATE_MARKER} 오늘은 {date.today().isoformat()} 입니다. "
        "날짜·기한·최신성에 대한 판단(예: 날짜 오기 검증, 기한 경과 여부)은 "
        "반드시 이 날짜를 기준으로 하세요."
    )


def _inject(messages):
    """메시지 목록 맨 앞에 오늘 날짜 SystemMessage 를 삽입(이미 있으면 그대로)."""
    try:
        from langchain_core.messages import SystemMessage
        msgs = list(messages)
        for m in msgs:
            if _DATE_MARKER in (getattr(m, "content", "") or ""):
                return msgs  # 이미 주입됨
        return [SystemMessage(content=today_note())] + msgs
    except Exception:
        return messages


def install() -> None:
    """ChatOpenAI 의 생성/스트리밍 메서드를 1회 패치하여 날짜 문구를 자동 주입."""
    try:
        from langchain_openai import ChatOpenAI
    except Exception as e:
        log.warning("langchain_openai 미설치 — 날짜 주입 비활성화: %s", e)
        return

    if getattr(ChatOpenAI, "_date_patched", False):
        return

    _orig_generate = ChatOpenAI._generate
    _orig_agenerate = ChatOpenAI._agenerate
    _orig_stream = ChatOpenAI._stream
    _orig_astream = ChatOpenAI._astream

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return _orig_generate(self, _inject(messages), stop=stop, run_manager=run_manager, **kwargs)

    def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return _orig_agenerate(self, _inject(messages), stop=stop, run_manager=run_manager, **kwargs)

    def _stream(self, *args, **kwargs):
        if args:
            args = (_inject(args[0]),) + args[1:]
        elif "messages" in kwargs:
            kwargs["messages"] = _inject(kwargs["messages"])
        return _orig_stream(self, *args, **kwargs)

    def _astream(self, *args, **kwargs):
        if args:
            args = (_inject(args[0]),) + args[1:]
        elif "messages" in kwargs:
            kwargs["messages"] = _inject(kwargs["messages"])
        return _orig_astream(self, *args, **kwargs)

    ChatOpenAI._generate = _generate
    ChatOpenAI._agenerate = _agenerate
    ChatOpenAI._stream = _stream
    ChatOpenAI._astream = _astream
    ChatOpenAI._date_patched = True
    log.info("프롬프트 날짜 자동 주입 활성화 (오늘=%s)", date.today().isoformat())
