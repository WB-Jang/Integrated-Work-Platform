"""메뉴 활성화/비활성화 상태 관리 — JSON 파일 기반 영속화."""
import os
import json

_STATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'menu_state.json'
)

MENU_ITEMS: dict[str, str] = {
    'analysis':       '문서분석',
    'summary':        '문서요약',
    'qa':             '문서질의응답',
    'legal':          '법률검색',
    'convert':        'PDF 변환',
    'reporting':      '보고서',
    'outlook':        '메일분석',
    'regulatory':     '규제동향',
    'risk_dashboard': 'Risk DashBoard',
    'risk_indicator': 'Risk Indicator Dashboard',
}

MENU_GROUPS: dict[str, list[str]] = {
    'llm':       ['analysis', 'summary', 'qa', 'legal'],
    'business':  ['convert', 'reporting', 'outlook', 'regulatory'],
    'dashboard': ['risk_dashboard', 'risk_indicator'],
}

_state: dict[str, bool] = {}


def load() -> dict[str, bool]:
    """파일에서 메뉴 상태를 로드합니다. 없으면 기본값(모두 활성) 사용."""
    global _state
    defaults = {k: True for k in MENU_ITEMS}
    if os.path.exists(_STATE_PATH):
        try:
            with open(_STATE_PATH, encoding='utf-8') as f:
                saved = json.load(f)
            _state = {**defaults, **{k: bool(v) for k, v in saved.items() if k in defaults}}
        except Exception:
            _state = dict(defaults)
    else:
        _state = dict(defaults)
    return dict(_state)


def save() -> None:
    """현재 상태를 파일에 저장합니다."""
    try:
        with open(_STATE_PATH, 'w', encoding='utf-8') as f:
            json.dump(_state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get() -> dict[str, bool]:
    """현재 상태 복사본을 반환합니다."""
    if not _state:
        load()
    return dict(_state)


def is_enabled(key: str) -> bool:
    """특정 메뉴 항목의 활성화 여부를 반환합니다."""
    if not _state:
        load()
    return _state.get(key, True)


def set_enabled(key: str, enabled: bool) -> None:
    """특정 메뉴 항목의 활성화 여부를 설정하고 파일에 저장합니다."""
    if not _state:
        load()
    _state[key] = enabled
    save()
