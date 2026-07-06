"""
홈 대시보드용 활동 로그 — 프로세스 전역 인메모리 집계.

각 기능(문서분석·요약·법률검색·보고서·PDF변환·규제동향)이 실제로 완료되는
지점에서 record() 를 호출해 "최근 작업 이력"과 KPI 카드 수치(오늘/이번달/누계)를
실데이터로 채운다. 프로세스가 재시작되면 초기화된다(다른 런타임 카운터·로그와
동일한 제약 — README 참고).
"""
import threading
import time
from collections import deque
from datetime import datetime, timedelta

_lock = threading.Lock()
_events: deque = deque(maxlen=200)          # 최근 작업 이력(표시용)
_daily_counts: dict[str, dict[str, int]] = {}   # {category: {yyyy-mm-dd: n}}
_total_counts: dict[str, int] = {}          # {category: 누계}
_llm_daily: dict[str, int] = {}             # {yyyy-mm-dd: n} — create_llm() 호출 수
_START_TIME = time.time()

CATEGORY_LABEL = {
    'analysis': '문서 분석',
    'summary': '문서 요약',
    'qa': '문서 질의응답',
    'legal': '법률 검색',
    'convert': 'PDF 변환',
    'report': '보고서 작성',
    'regulatory': '규제 동향',
    'agent': 'AI 에이전트',
}

STATUS_BADGE = {
    'done': 'badge-done',
    'reviewing': 'badge-reviewing',
    'error': 'badge-error',
    'rag': 'badge-rag',
}

CATEGORY_DOT_COLOR = {
    'analysis': '#f59e0b',
    'summary': '#22c55e',
    'qa': '#818cf8',
    'legal': '#818cf8',
    'convert': 'rgba(148,163,184,.5)',
    'report': '#0ea5e9',
    'regulatory': '#f59e0b',
    'agent': '#0ea5e9',
}


def _today_str() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def _month_str() -> str:
    return datetime.now().strftime('%Y-%m')


def record(category: str, title: str, detail: str = '', status: str = 'done') -> None:
    """기능 완료 시점에서 호출 — 활동 이력 + 카운터를 함께 갱신한다."""
    now = time.time()
    day = _today_str()
    with _lock:
        _events.append({
            'ts': now, 'category': category, 'title': title,
            'detail': detail, 'status': status,
        })
        _daily_counts.setdefault(category, {})
        _daily_counts[category][day] = _daily_counts[category].get(day, 0) + 1
        _total_counts[category] = _total_counts.get(category, 0) + 1


def record_llm_request() -> None:
    """create_llm() 호출 시점 — LLM 요청 수 프록시 카운터."""
    day = _today_str()
    with _lock:
        _llm_daily[day] = _llm_daily.get(day, 0) + 1


def llm_requests_today() -> int:
    with _lock:
        return _llm_daily.get(_today_str(), 0)


def count_today(category: str) -> int:
    with _lock:
        return _daily_counts.get(category, {}).get(_today_str(), 0)


def count_month(category: str) -> int:
    prefix = _month_str()
    with _lock:
        return sum(
            n for day, n in _daily_counts.get(category, {}).items()
            if day.startswith(prefix)
        )


def count_total(category: str) -> int:
    with _lock:
        return _total_counts.get(category, 0)


def _relative_time(ts: float) -> str:
    delta = timedelta(seconds=max(0, time.time() - ts))
    if delta < timedelta(minutes=1):
        return '방금 전'
    if delta < timedelta(hours=1):
        return f'{int(delta.total_seconds() // 60)}분 전'
    if delta < timedelta(days=1):
        return f'{int(delta.total_seconds() // 3600)}시간 전'
    if delta < timedelta(days=2):
        return '어제'
    return f'{delta.days}일 전'


def recent(n: int = 5) -> list[dict]:
    """최근 작업 이력 n건 (최신순), 대시보드 렌더링에 바로 쓸 수 있는 필드 포함."""
    with _lock:
        items = list(_events)[-n:]
    items.reverse()
    out = []
    for e in items:
        out.append({
            'title': e['title'],
            'sub': f"{CATEGORY_LABEL.get(e['category'], e['category'])} · {_relative_time(e['ts'])}",
            'badge_class': STATUS_BADGE.get(e['status'], 'badge-done'),
            'badge_label': e['detail'] or {'done': '완료', 'reviewing': '검토중', 'error': '오류'}.get(e['status'], e['status']),
            'dot_color': CATEGORY_DOT_COLOR.get(e['category'], 'rgba(148,163,184,.5)'),
        })
    return out


def uptime_str() -> str:
    secs = int(time.time() - _START_TIME)
    if secs < 3600:
        return f'{secs // 60}분'
    if secs < 86400:
        return f'{secs // 3600}시간 {(secs % 3600) // 60}분'
    return f'{secs // 86400}일 {(secs % 86400) // 3600}시간'
