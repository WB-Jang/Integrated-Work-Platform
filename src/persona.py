"""
유저별 페르소나 (COSTAR 방법론) 관리.

personas.json (프로젝트 루트) 에 접속 IP → 페르소나 매핑을 등록한다.
LLM 답변 생성 시 해당 유저의 페르소나가 system 프롬프트 컨텍스트로 주입된다.

보안 원칙:
  - 페르소나는 **접속 IP 가 정확히 일치하는 경우에만** 적용한다.
  - 미등록 IP 는 페르소나 없이 동작한다. 다른 유저의 페르소나를
    유사 매칭·폴백 등으로 대신 적용하는 일은 절대 없어야 한다.

COSTAR 구성:
  Context   — 유저가 누구이고 어떤 업무 맥락에 있는지
  Objective — 답변이 달성해야 할 목표
  Style     — 문체·표현 방식
  Tone      — 어조
  Audience  — 답변을 읽는 사람(유저)의 수준·배경
  Response  — 답변 구성 방식
"""
import json
import os
import threading

from logger import get_logger

log = get_logger("persona")

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PERSONA_PATH = os.path.join(_BASE_DIR, "personas.json")

_lock = threading.Lock()
_personas: dict[str, dict] = {}
_loaded = False

# COSTAR 키 → 프롬프트 표기 (출력 순서 고정)
_COSTAR_FIELDS = [
    ("context", "Context"),
    ("objective", "Objective"),
    ("style", "Style"),
    ("tone", "Tone"),
    ("audience", "Audience"),
    ("response", "Response"),
]


def _load(force: bool = False) -> None:
    global _loaded, _personas
    with _lock:
        if _loaded and not force:
            return
        _personas = {}
        try:
            if os.path.exists(_PERSONA_PATH):
                with open(_PERSONA_PATH, encoding="utf-8") as f:
                    raw = json.load(f)
                for ip, p in raw.items():
                    if isinstance(p, dict) and not ip.startswith("_"):
                        _personas[ip.strip()] = p
                log.info("페르소나 %d건 로드 완료", len(_personas))
        except Exception as e:
            log.warning("personas.json 로드 실패 (페르소나 미적용으로 계속): %s", e)
        _loaded = True


def reload_personas() -> None:
    """personas.json 변경 후 재로드."""
    _load(force=True)


def get_persona(client_ip: str) -> dict | None:
    """접속 IP 와 정확히 일치하는 페르소나만 반환. 미등록이면 None."""
    _load()
    ip = (client_ip or "").strip()
    if not ip or ip == "unknown":
        return None
    return _personas.get(ip)


def get_persona_block(client_ip: str) -> str:
    """LLM system 프롬프트에 주입할 COSTAR 페르소나 블록 문자열.

    해당 IP 의 페르소나가 없으면 빈 문자열 — 호출부는 빈 문자열이면
    페르소나 없이 동작해야 한다 (절대 다른 페르소나로 대체 금지).
    """
    p = get_persona(client_ip)
    if not p:
        return ""
    costar = p.get("costar", {}) or {}
    lines = ["[사용자 페르소나 — 아래 COSTAR 정보를 답변 생성에 반영하세요]"]
    name = p.get("name", "")
    dept = p.get("department", "")
    rank = p.get("rank", "")
    ident = " · ".join(x for x in (dept, rank, name) if x)
    if ident:
        lines.append(f"사용자: {ident}")
    for key, label in _COSTAR_FIELDS:
        v = (costar.get(key) or "").strip()
        if v:
            lines.append(f"({label[0]}) {label}: {v}")
    if len(lines) <= 1:
        return ""
    return "\n".join(lines)
