"""
금융감독원(FSS) 관련 Risk Dashboard 패널.

두 개의 탭으로 구성된다:
  1. 감독원 뉴스 — 금융감독원 보도·알림 원문 피드(접속 실패 시 네이버 뉴스 폴백).
  2. 네이버 키워드 검색 — 질문을 입력하면 관련 뉴스를 수집·재정렬·요약해 통합 답변을
     생성한다(옛 '규제 동향' 메뉴의 뉴스 검색 기능을 이관).

NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수(HF Spaces Secrets)가 있으면 네이버
뉴스 검색을 사용한다.
"""
import os
import re
import asyncio
import html as _html
import datetime
import time as _time
from email.utils import parsedate_to_datetime

import requests

from nicegui import ui, run as nicegui_run, app as nicegui_app
from nicegui import context as _ng_context
from logger import get_logger, set_current_user
from ui_styles import progress_block_html, step_list_html, elapsed_ticker_script

log = get_logger("fss_dashboard")

# 뉴스 검색 진행 단계 라벨(규제 동향 뉴스 검색에서 이관)
_YNA_STEPS = ['키워드 추출', '기사 수집', '유사도 재정렬', '기사 요약', '클러스터링', '통합 답변']

# 출처별 태그 라벨(뉴스 검색 카드용)
_SOURCE_TAG = {
    "금융감독원": "FSS",
    "한국은행":   "BOK",
    "금융위원회": "FSC",
    "연합뉴스":   "YNA",
}

# YYYYMMDD, YYYY.MM.DD, YYYY/MM/DD 등을 YYYY-MM-DD 로 정규화
_DATE_DIGITS_RE = re.compile(r'^\s*(\d{4})[.\-/]?(\d{2})[.\-/]?(\d{2})\s*$')


def _normalize_date(raw: str) -> tuple[str, bool]:
    """입력 문자열을 YYYY-MM-DD 로 정규화. (정규화된 문자열, 유효 여부) 반환.
    빈 문자열은 유효한 것으로 취급(선택 입력이므로)."""
    raw = (raw or '').strip()
    if not raw:
        return '', True
    m = _DATE_DIGITS_RE.match(raw)
    if not m:
        return raw, False
    y, mo, d = m.groups()
    try:
        datetime.date(int(y), int(mo), int(d))
    except ValueError:
        return raw, False
    return f'{y}-{mo}-{d}', True


def _apply_current_user() -> None:
    try:
        v = (nicegui_app.storage.user.get('initials') or '-').strip().upper()
    except Exception:
        v = '-'
    set_current_user(v or '-')

# ── 대시보드 4개 카테고리 ─────────────────────────────────────────────────────
# 각 카테고리를 네이버 뉴스 검색 질의어로 매핑한다.
_CATEGORY_QUERIES = {
    "금융감독원 보도자료": "금융감독원 보도자료",
    "금융사고 공시":       "금융사고 금융감독원",
    "검사·감독 결과":      "금융감독원 검사 제재",
    "금융회사 경영공시":   "금융회사 경영공시",
}

# ── 금융감독원 보도·알림 게시판 (1차 소스) ───────────────────────────────────
# menuNo=200747(보도·알림) 하위 '보도자료' 게시판. 실데이터(감독원 원문)를 우선
# 사용하고, 접속·파싱 실패 시 네이버 뉴스로 자동 폴백한다.
_FSS_BASE = "https://www.fss.or.kr"
_FSS_PRESS_LIST = "https://www.fss.or.kr/fss/bbs/B0000188/list.do?menuNo=200218"
_FSS_FEED_LABEL = "금융감독원 보도·알림"

# ── 네이버 뉴스 검색 API (폴백 소스) ─────────────────────────────────────────
_NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"
_REQUESTS_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _strip_html(s: str) -> str:
    """네이버 응답의 <b> 태그·HTML 엔티티를 제거해 순수 텍스트로 변환."""
    s = re.sub(r"<[^>]+>", "", s or "")
    return _html.unescape(s).strip()


def _fmt_pubdate(pub: str) -> str:
    """RFC822 pubDate(예: 'Mon, 14 Jul 2025 09:00:00 +0900') → 'YYYY-MM-DD'."""
    try:
        return parsedate_to_datetime(pub).strftime("%Y-%m-%d")
    except Exception:
        return ""


def _fetch_naver_news(query: str, count: int = 10) -> list[dict]:
    """네이버 뉴스 검색 API로 query 관련 최신 기사를 반환.

    NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 미설정 또는 오류 시 빈 리스트.
    """
    cid = os.environ.get("NAVER_CLIENT_ID", "").strip()
    csec = os.environ.get("NAVER_CLIENT_SECRET", "").strip()
    if not (cid and csec):
        log.warning("네이버 검색 자격증명(NAVER_CLIENT_ID/SECRET) 미설정")
        return []
    try:
        resp = requests.get(
            _NAVER_NEWS_URL,
            params={"query": query, "display": max(count, 5), "sort": "date"},
            headers={
                "X-Naver-Client-Id": cid,
                "X-Naver-Client-Secret": csec,
                **_REQUESTS_HEADERS,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        out = []
        for it in data.get("items", [])[:count]:
            title = _strip_html(it.get("title", ""))
            # originallink(원본 언론사) 우선, 없으면 link(네이버뉴스)
            url = (it.get("originallink") or it.get("link") or "").strip()
            if not title or not url:
                continue
            out.append({
                "title": title,
                "url": url,
                "regDate": _fmt_pubdate(it.get("pubDate", "")),
                "content": _strip_html(it.get("description", ""))[:200],
                "_source": "네이버뉴스",
            })
        return out
    except Exception as exc:
        log.warning("네이버 뉴스 검색 실패 (%s): %s", query, exc)
        return []


def _fetch_all_categories(api_key: str = None, count: int = 10) -> dict[str, list[dict]]:
    """4개 카테고리를 네이버 뉴스 검색으로 수집한다(폴백 경로).

    api_key 인자는 호출부 호환을 위해 유지하나 사용하지 않는다(네이버 자격증명은
    NAVER_CLIENT_ID/SECRET 환경변수 사용).
    """
    results = {}
    for label, query in _CATEGORY_QUERIES.items():
        items = _fetch_naver_news(query, count)
        log.info("네이버 뉴스 '%s': %d건", label, len(items))
        results[label] = items
    return results


# ── FSS 보도자료 게시판 파싱 ──────────────────────────────────────────────────
_FSS_DATE_RE = re.compile(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})")


def _abs_fss_url(href: str) -> str:
    """FSS 상대경로(/fss/...)를 절대 URL로 변환."""
    href = (href or "").strip().replace("&amp;", "&")
    if not href:
        return ""
    if href.startswith(("http://", "https://")):
        return href
    if href.startswith("/"):
        return _FSS_BASE + href
    return _FSS_BASE + "/" + href


def _fetch_fss_press(count: int = 10) -> list[dict]:
    """금융감독원 보도자료 게시판(B0000188) 목록을 파싱해 최신 게시물을 반환.

    게시판 HTML의 <tr> 행마다 상세(view.do?...nttId=...) 링크·제목·등록일을 추출한다.
    접속·파싱 실패 또는 결과 없음 시 빈 리스트(→ 네이버 폴백).
    """
    try:
        resp = requests.get(_FSS_PRESS_LIST, headers=_REQUESTS_HEADERS, timeout=10)
        resp.raise_for_status()
        text = resp.text
    except Exception as exc:
        log.warning("FSS 보도자료 목록 조회 실패: %s", exc)
        return []

    out: list[dict] = []
    seen: set[str] = set()
    # 각 행(<tr> … </tr>) 안에서 view 링크 + 날짜를 함께 뽑는다.
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S | re.I):
        m = re.search(
            r'href="([^"]*view\.do[^"]*nttId=\d+[^"]*)"[^>]*>(.*?)</a>',
            tr, re.S | re.I,
        )
        if not m:
            continue
        url = _abs_fss_url(m.group(1))
        title = _strip_html(m.group(2))
        if not (url and title) or url in seen:
            continue
        seen.add(url)
        dm = _FSS_DATE_RE.search(tr)
        reg = f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}" if dm else ""
        out.append({
            "title": title,
            "url": url,
            "regDate": reg,
            "content": "",
            "_source": "금융감독원",
        })
        if len(out) >= count:
            break
    log.info("FSS 보도자료 %d건 파싱", len(out))
    return out


def _fetch_dashboard_feed(api_key: str = None, count: int = 10) -> dict[str, list[dict]]:
    """대시보드용 단일 피드. 1차: FSS 보도·알림 원문, 실패 시 네이버 뉴스로 폴백."""
    items = _fetch_fss_press(count)
    if items:
        return {_FSS_FEED_LABEL: items}
    # 폴백 — 네이버 뉴스(감독원 보도자료 질의)
    naver = _fetch_naver_news("금융감독원 보도자료", count)
    log.info("FSS 원문 없음 → 네이버 폴백 %d건", len(naver))
    return {_FSS_FEED_LABEL: naver}


def build_fss_dashboard_panel(config: dict, create_llm_fn=None):
    """Risk DashBoard 패널을 현재 NiceGUI 컨텍스트에 렌더링합니다.

    두 개 탭:
      1. 감독원 뉴스 — 금융감독원 보도·알림 원문 피드.
      2. 네이버 키워드 검색 — 질문 기반 뉴스 검색·요약(create_llm_fn 필요).
    """
    # ── 헤더 ─────────────────────────────────────────────────────────────
    with ui.element('div').classes('page-head'):
        ui.html(
            '<div class="titles">'
            '<div class="page-title">Risk DashBoard</div>'
            '<div class="page-subtitle">'
            '금융감독원 보도·알림 원문과 키워드 기반 뉴스 검색을 한 곳에서 조회합니다.'
            '</div>'
            '</div>'
        )

    # ── 탭 전환기 ────────────────────────────────────────────────────────
    with ui.element('div').style(
        'display:flex;gap:4px;border-bottom:1px solid var(--border);'
        'margin:0 32px 4px;padding-top:4px;'
    ):
        tab_state = ['feed']  # 'feed' | 'news'
        tab_btns: dict = {}
        for k, label in [('feed', '감독원 뉴스'), ('news', '네이버 키워드 검색')]:
            b = ui.element('button')
            with b:
                ui.html(f'<span>{label}</span>')
            tab_btns[k] = b

    feed_container = ui.element('div')
    news_container = ui.element('div')

    def _tab_btn_style(active: bool) -> str:
        weight = '600' if active else '500'
        color = 'var(--text)' if active else 'var(--text-3)'
        border = 'var(--text)' if active else 'transparent'
        return (
            f'background:transparent;border:none;border-bottom:2px solid {border};'
            f'padding:9px 14px;cursor:pointer;font-size:13px;font-weight:{weight};'
            f'color:{color};transition:all .15s;'
        )

    def _switch_tab(key: str):
        tab_state[0] = key
        for k, b in tab_btns.items():
            b.style(_tab_btn_style(k == key))
        feed_container.style(f'display:{"block" if key == "feed" else "none"};')
        news_container.style(f'display:{"block" if key == "news" else "none"};')

    tab_btns['feed'].on('click', lambda _e: _switch_tab('feed'))
    tab_btns['news'].on('click', lambda _e: _switch_tab('news'))

    with feed_container:
        _build_feed_tab(config)
    with news_container:
        _build_news_search_tab(config, create_llm_fn)

    _switch_tab('feed')


def _build_feed_tab(config: dict):
    """감독원 뉴스 탭 — 금융감독원 보도·알림 원문 피드(실패 시 네이버 폴백)."""
    fss_api_key = config.get("fss_api_key", "").strip()
    state = {"data": {}, "last_updated": None}

    # ── 폴백(네이버) 자격증명 안내 배너 ───────────────────────────────────
    _naver_ready = bool(
        os.environ.get("NAVER_CLIENT_ID", "").strip()
        and os.environ.get("NAVER_CLIENT_SECRET", "").strip()
    )
    if not _naver_ready:
        with ui.element('div').style(
            'margin:16px 32px;padding:12px 16px;'
            'background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.35);border-radius:8px;'
            'font-size:13px;color:var(--warning);'
        ):
            ui.html(
                '<b>ℹ 폴백(네이버 검색) 자격증명 미설정</b> — 기본은 감독원 원문을 사용합니다. '
                '<code>NAVER_CLIENT_ID</code> / <code>NAVER_CLIENT_SECRET</code>(HF Spaces Secrets)를 '
                '설정하면 감독원 접속 실패 시 네이버 뉴스로 대체됩니다.'
            )

    # ── 컨트롤 바 ────────────────────────────────────────────────────────
    with ui.element('div').style(
        'display:flex;align-items:center;gap:12px;padding:12px 32px;'
        'border-bottom:1px solid var(--border);flex-shrink:0;'
    ):
        count_input = ui.number(
            label='조회 건수', value=10, min=1, max=30, step=1,
        ).props('outlined dense hide-bottom-space').style('width:150px;')

        refresh_btn = ui.button('데이터 조회').classes('btn-primary-mono')
        last_updated_label = ui.html('<span style="color:var(--text-4);font-size:12px;"></span>')

    # ── 대시보드 (단일 피드) ──────────────────────────────────────────────
    dashboard_grid = ui.element('div').style(
        'display:block;padding:20px 32px;flex:1;overflow-y:auto;'
    )

    progress_bar = ui.linear_progress().props('indeterminate').classes('w-full')
    progress_bar.style('margin:0 32px;')
    progress_bar.visible = False

    # ── 카드 렌더링 ──────────────────────────────────────────────────────
    def _normalize_url(u: str) -> str:
        """원문 URL을 절대 URL로 정규화. 스킴이 없으면 https:// 보정,
        도메인 없는 상대경로(/...)는 외부 접속이 불가하므로 링크를 생략한다."""
        u = (u or "").strip()
        if not u:
            return ""
        if u.startswith("//"):
            return "https:" + u
        if u.startswith(("http://", "https://")):
            return u
        if u.startswith("/"):
            # FSS 상대경로는 감독원 도메인으로 절대화, 그 외는 링크 생략
            return _FSS_BASE + u if u.startswith("/fss") else ""
        return "https://" + u

    def _render_item(item: dict):
        title = _html.escape(str(item.get("title") or item.get("boardTitle") or "제목 없음"))
        url_raw = item.get("url") or item.get("boardUrl") or ""
        url_norm = _normalize_url(url_raw)
        date_raw = (
            item.get("regDate") or item.get("date") or
            item.get("boardDate") or item.get("pubDate") or ""
        )
        date_safe = _html.escape(str(date_raw)[:10]) if date_raw else ""
        content_raw = item.get("content") or item.get("summary") or ""
        content_safe = _html.escape(str(content_raw)[:200]).replace("\n", "<br>") if content_raw else ""
        source_label = item.get("_source", "")
        source_html = (
            f'<span style="font-size:10.5px;color:var(--text-4);margin-left:4px;">'
            f'[{_html.escape(source_label)}]</span>'
        ) if source_label else ""

        # 카드 본문은 ui.html, 외부 링크는 ui.link(new_tab=True)로 분리 — raw <a>가
        # NiceGUI(SPA) 안에서 새 탭으로 열리지 않던 문제를 회피하고 URL도 정규화한다.
        with ui.element('div').style('padding:10px 0;border-bottom:1px solid var(--border);'):
            ui.html(
                f'<div style="display:flex;align-items:flex-start;justify-content:space-between;gap:8px;">'
                f'<span style="font-size:13px;font-weight:500;color:var(--text);line-height:1.5;">'
                f'{title}{source_html}</span>'
                f'<span style="font-size:11px;color:var(--text-4);flex-shrink:0;">{date_safe}</span>'
                f'</div>'
                + (f'<div style="font-size:12px;color:var(--text-3);margin-top:4px;">{content_safe}</div>'
                   if content_safe else '')
            )
            if url_norm:
                ui.link('원문 보기 →', target=url_norm, new_tab=True).style(
                    'font-size:11.5px;color:var(--text-3);text-decoration:none;'
                    'border-bottom:1px solid var(--border);display:inline-block;margin-top:4px;'
                )

    def _render_dashboard(data: dict[str, list[dict]]):
        dashboard_grid.clear()
        with dashboard_grid:
            for category, items in data.items():
                with ui.element('div').style(
                    'background:var(--bg);border:1px solid var(--border);'
                    'border-radius:12px;padding:16px;display:flex;flex-direction:column;'
                    'min-height:280px;'
                ):
                    # 카드 헤더 — 실제 사용된 소스(감독원/네이버뉴스) 표시
                    src = items[0].get("_source") if items else ""
                    source_note = (
                        f'<span style="font-size:10.5px;color:var(--text-4);margin-left:6px;">'
                        f'{_html.escape(src)}</span>'
                    ) if src else ""
                    ui.html(
                        f'<div style="display:flex;align-items:center;gap:8px;'
                        f'margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid var(--border);">'
                        f'<span class="material-symbols-outlined" '
                        f'style="font-size:18px;color:#3b82f6;">campaign</span>'
                        f'<span style="font-size:14px;font-weight:600;color:var(--text);">'
                        f'{_html.escape(category)}</span>'
                        f'{source_note}'
                        f'<span style="margin-left:auto;font-size:11.5px;color:var(--text-4);">'
                        f'{len(items)}건</span>'
                        f'</div>'
                    )

                    if not items:
                        ui.html(
                            '<div style="text-align:center;color:var(--text-4);font-size:12.5px;'
                            'padding:20px 0;">데이터 없음 (감독원 접속·네이버 폴백 모두 실패)</div>'
                        )
                    else:
                        for item in items:
                            _render_item(item)

    # ── 조회 핸들러 ──────────────────────────────────────────────────────
    async def refresh_dashboard():
        count = int(count_input.value or 10)
        progress_bar.visible = True
        refresh_btn.props(add='disable')
        last_updated_label.content = (
            '<span style="color:var(--text-4);font-size:12px;">조회 중…</span>'
        )

        try:
            data = await nicegui_run.io_bound(_fetch_dashboard_feed, fss_api_key, count)

            state["data"] = data
            state["last_updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            _render_dashboard(data)
            last_updated_label.content = (
                f'<span style="color:var(--text-4);font-size:12px;">'
                f'최종 갱신: {state["last_updated"]}</span>'
            )
            ui.notify('대시보드 조회 완료', type='positive', position='top')
        except Exception as e:
            log.error("대시보드 조회 오류: %s", e)
            ui.notify(f'조회 오류: {e}', type='negative', position='top')
            last_updated_label.content = (
                '<span style="color:var(--danger);font-size:12px;">조회 실패</span>'
            )
        finally:
            progress_bar.visible = False
            refresh_btn.props(remove='disable')

    refresh_btn.on_click(refresh_dashboard)

    # 초기 빈 그리드 렌더링 (단일 피드 안내)
    with dashboard_grid:
        with ui.element('div').style(
            'background:var(--bg);border:1px solid var(--border);'
            'border-radius:12px;padding:16px;min-height:240px;'
            'display:flex;flex-direction:column;align-items:center;justify-content:center;'
        ):
            ui.html(
                '<span class="material-symbols-outlined" '
                'style="font-size:32px;color:var(--border-strong);margin-bottom:10px;">campaign</span>'
                f'<div style="font-size:13px;font-weight:600;color:var(--text-3);">'
                f'{_html.escape(_FSS_FEED_LABEL)}</div>'
                '<div style="font-size:12px;color:var(--text-4);margin-top:4px;">'
                '조회 버튼을 눌러 감독원 보도·알림을 불러오세요</div>'
            )


# ── 뉴스 검색 탭(옛 '규제 동향'의 뉴스 검색 기능 이관) ────────────────────────
def _build_news_search_tab(config: dict, create_llm_fn=None):
    """네이버 키워드 검색 탭 — 질문 기반 뉴스 수집·재정렬·요약·통합답변.

    옛 '규제 동향' 메뉴의 뉴스 검색(연합/네이버) 파이프라인을 그대로 이관한다.
    기관별 모니터링·메일 발송 기능은 이관하지 않는다(요청에 따라 제외).
    """
    state = {'results': []}
    _yna_ctl = {'task': None, 'busy': False}

    if create_llm_fn is None:
        with ui.element('div').style('padding:24px 32px;'):
            ui.html(
                '<div class="muted-text" style="color:var(--danger);">'
                '뉴스 검색용 LLM이 구성되지 않았습니다. 관리자에게 문의하세요.</div>'
            )
        return

    # ── 본문 — 좌측 필터 / 우측 결과 ─────────────────────────────────────
    with ui.element('div').classes('filter-result-row'):

        # ── 좌측: 검색 설정 ──────────────────────────────────────────────
        with ui.element('div').classes('filter-col'):
            ui.html(
                '<div class="section-card-title">'
                '<span class="material-symbols-outlined">tune</span>뉴스 검색'
                '</div>'
            )
            keyword_input = ui.input(
                label='질문 (LLM이 키워드 자동 추출)',
                placeholder='예: 최근 한국은행 기준금리 인하 전망은 어떻습니까?',
            ).props('outlined dense').classes('w-full mb-2')
            date_from_input = ui.input(
                label='시작일 (YYYY-MM-DD 또는 YYYYMMDD)', placeholder='예: 2025-01-01 또는 20250101',
            ).props('outlined dense').classes('w-full mb-2')
            date_from_err = ui.html('').style('margin:-4px 0 6px 2px;')
            date_to_input = ui.input(
                label='종료일 (YYYY-MM-DD 또는 YYYYMMDD)', placeholder='예: 2025-12-31 또는 20251231',
            ).props('outlined dense').classes('w-full mb-2')
            date_to_err = ui.html('').style('margin:-4px 0 6px 2px;')

            def _make_date_blur_handler(inp, err_el):
                def _on_blur():
                    normalized, ok = _normalize_date(inp.value)
                    if not ok:
                        err_el.content = (
                            '<div style="font-size:11px;color:var(--danger);">'
                            '인식할 수 없는 날짜 형식입니다 (예: 2025-01-01, 20250101)</div>'
                        )
                        return
                    inp.value = normalized
                    err_el.content = ''
                return _on_blur

            date_from_input.on('blur', _make_date_blur_handler(date_from_input, date_from_err))
            date_to_input.on('blur', _make_date_blur_handler(date_to_input, date_to_err))

            yna_count_input = ui.number(
                label='최대 조회 건수', value=10, min=1, max=30, step=1,
            ).props('outlined dense').classes('w-full mb-3')

            fetch_btn_yna = ui.button('검색 및 요약').classes('btn-primary-mono w-full')

        # ── 우측: 결과 ───────────────────────────────────────────────────
        with ui.element('div').classes('result-col'):
            result_count_label = ui.html(
                '<div class="muted-text">질문을 입력하고 검색을 클릭하세요.</div>'
                '<div style="margin-top:8px;font-size:11.5px;color:var(--text-4);">'
                '질문을 입력하면 관련 뉴스를 찾아 통합 답변을 생성합니다.</div>'
            )
            progress_area = ui.html('')
            skeleton_area = ui.column().classes('w-full mt-2 gap-0')
            skeleton_area.visible = False
            result_container = ui.column().classes('w-full mt-2').style('flex:1; overflow:auto;')

    ui.add_body_html(elapsed_ticker_script())

    # NiceGUI 슬롯/클라이언트 컨텍스트를 태스크 내부에서 복원(create_task 유실 대응).
    _client = _ng_context.client

    def _spawn(coro):
        async def _wrapped():
            with _client:
                await coro
        return asyncio.create_task(_wrapped())

    # ── 렌더링 ──────────────────────────────────────────────────────────
    def _render_one_card(item: dict):
        source = item.get('source', '')
        tag_label = _SOURCE_TAG.get(source, source[:3])
        title_safe = _html.escape(item.get('title') or '')
        summary_safe = _html.escape(item.get('summary', '')).replace('\n', '<br>')
        pub_date = item.get('published_date', '')
        date_html = (
            f'<span style="color:var(--text-4);font-size:11px;margin-left:auto;">'
            f'{_html.escape(str(pub_date))}</span>'
        ) if pub_date else ''

        with ui.element('div').classes('reg-card'):
            ui.html(
                '<div class="reg-title">'
                f'<span class="tag solid">{_html.escape(tag_label)}</span>'
                f'<span style="color:var(--text-3);font-size:11.5px;">'
                f'{_html.escape(source)}</span>'
                f'<span style="flex:1;color:var(--text);font-weight:600;">{title_safe}</span>'
                f'{date_html}'
                '</div>'
                f'<div class="reg-summary">{summary_safe}</div>'
            )
            ui.link('원문 보기 →', target=item.get('url') or '', new_tab=True).classes('reg-link')

    def _render_results(results, clustered=False, question='', keywords=None,
                        answer_summary='', approximate=False):
        result_container.clear()
        with result_container:
            if not results:
                ui.html(
                    '<div style="text-align:center;color:var(--text-4);font-size:13px;'
                    'padding:24px;background:var(--bg-elev);border:1px solid var(--border);'
                    'border-radius:var(--radius);">검색 결과가 없습니다.</div>'
                )
                return

            if approximate:
                ui.html(
                    '<div style="font-size:12.5px;color:var(--text-2);'
                    'padding:10px 12px;margin-bottom:10px;background:var(--bg-elev);'
                    'border:1px solid var(--text-3);border-left:3px solid var(--text-2);'
                    'border-radius:var(--radius);">'
                    '⚠ 질문과 <b>명확히 관련된 기사를 찾지 못했습니다.</b> '
                    '아래는 의미상 가장 가까운 <b>참고용 근접 기사</b>이며, '
                    '질문에 대한 직접적인 답이 아닐 수 있습니다.</div>'
                )

            if answer_summary:
                kws_html = ''
                if keywords:
                    chips = ' '.join(
                        f'<span class="tag solid" style="margin-right:4px;">{_html.escape(k)}</span>'
                        for k in keywords
                    )
                    kws_html = (
                        f'<div style="margin:6px 0 10px;font-size:11.5px;color:var(--text-3);">'
                        f'추출 키워드: {chips}</div>'
                    )
                ans_html = _html.escape(answer_summary).replace('\n', '<br>')
                q_html = _html.escape(question)
                ui.html(
                    '<div class="reg-card" style="border:1px solid var(--text-3);'
                    'background:var(--bg-elev);">'
                    '<div class="reg-title">'
                    '<span class="tag solid">통합답변</span>'
                    f'<span style="flex:1;color:var(--text);font-weight:700;">{q_html}</span>'
                    '</div>'
                    f'{kws_html}'
                    f'<div class="reg-summary">{ans_html}</div>'
                    '</div>'
                )

            if not clustered:
                for item in results:
                    _render_one_card(item)
                return

            clusters: dict[int, list[dict]] = {}
            for item in results:
                c = item.get('cluster', 0)
                clusters.setdefault(c, []).append(item)

            def _cluster_rank(c_idx: int) -> int:
                its = clusters[c_idx]
                return its[0].get('cluster_rank', 999) if its else 999

            ordered = sorted(clusters.keys(), key=_cluster_rank)
            for display_idx, c_idx in enumerate(ordered, start=1):
                items_in_cluster = clusters[c_idx]
                reps = [it for it in items_in_cluster if it.get('is_representative')]
                if not reps:
                    reps = items_in_cluster[:2]
                total_in_cluster = len(items_in_cluster)
                sim = items_in_cluster[0].get('cluster_similarity', 0.0)
                ui.html(
                    f'<div style="font-size:12px;font-weight:700;color:var(--text-3);'
                    f'text-transform:uppercase;letter-spacing:.04em;'
                    f'margin:16px 0 8px;padding:0 2px;">'
                    f'클러스터 {display_idx} — 대표 기사 '
                    f'(전체 {total_in_cluster}건 중 2건, 질문 유사도 {sim:.3f})</div>'
                )
                for item in reps:
                    _render_one_card(item)

    # ── 뉴스 검색 실행 ──────────────────────────────────────────────────
    async def fetch_news_search():
        _apply_current_user()
        question = (keyword_input.value or '').strip()
        if not question:
            ui.notify('질문을 입력하세요.', type='warning', position='top')
            return
        log.info('Risk DashBoard 뉴스 검색 질의: %s', question[:120])

        date_from_norm, from_ok = _normalize_date(date_from_input.value)
        date_to_norm, to_ok = _normalize_date(date_to_input.value)
        if not from_ok or not to_ok:
            ui.notify('날짜 형식을 확인하세요 (예: 2025-01-01, 20250101).', type='warning', position='top')
            return
        date_from_input.value = date_from_norm
        date_to_input.value = date_to_norm
        date_from = date_from_norm or None
        date_to = date_to_norm or None
        count = int(yna_count_input.value or 10)
        naver_client_id = config.get('naver_client_id', '').strip()
        naver_client_secret = config.get('naver_client_secret', '').strip()

        _start_ts = _time.time()
        _yna_ctl['busy'] = True
        _yna_ctl['task'] = asyncio.current_task()
        fetch_btn_yna.text = '중지'
        fetch_btn_yna.classes(add='is-stop')
        result_container.clear()
        result_count_label.content = ''
        skeleton_area.visible = True
        skeleton_area.clear()
        with skeleton_area:
            for _ in range(3):
                ui.html('<div class="skeleton-card"></div>')

        def _step(idx: int, extra: str = '') -> None:
            elapsed_span = (
                f'<span class="progress-block-elapsed" data-elapsed-since="{_start_ts}">'
                '0초 경과</span>'
            )
            progress_area.content = (
                step_list_html(_YNA_STEPS, idx)
                + f'<div class="muted-text" style="display:flex;align-items:center;gap:8px;">'
                f'{extra}{elapsed_span}</div>'
            )

        _step(0)

        try:
            llm = create_llm_fn()
            from regulatory_agent import (
                extract_search_queries,
                search_news_by_keywords,
                rerank_by_question,
                summarize_update,
                cluster_news_results,
                summarize_clusters_for_question,
            )

            embed_url = config.get('legal_embedding', {}).get('url', 'http://127.0.0.1:8081')
            embed_model = config.get('legal_embedding', {}).get('model', 'bge-m3')
            embed_timeout = config.get('legal_embedding', {}).get('timeout', 45)

            search_queries = await nicegui_run.io_bound(
                extract_search_queries, question, llm, 5,
            )
            _step(1, f'검색 표현: {_html.escape(", ".join(search_queries))} · ')

            fetch_count = min(count * 3, 30)
            items = await nicegui_run.io_bound(
                search_news_by_keywords, search_queries, date_from, date_to, fetch_count,
                naver_client_id, naver_client_secret,
            )

            if items:
                _step(2, f'{len(items)}건 후보 · ')
                items = await nicegui_run.io_bound(
                    rerank_by_question,
                    question, items, embed_url, embed_model, embed_timeout, count,
                )

            sim_threshold = float(
                config.get('legal_embedding', {}).get('relevance_threshold', 0.45)
            )
            approximate = False
            scored = [it for it in items if 'rerank_score' in it]
            if scored:
                relevant = [it for it in scored if it['rerank_score'] >= sim_threshold]
                if relevant:
                    items = relevant
                else:
                    approximate = True
                    items = scored[:min(3, len(scored))]
            else:
                lex_hit = [it for it in items if it.get('lexical_score', 0) > 0]
                if lex_hit:
                    items = lex_hit[:count]
                else:
                    approximate = True
                    items = items[:min(3, len(items))]
            if approximate:
                for it in items:
                    it['is_approximate'] = True

            _step(3, f'{len(items)}건 · ')

            def _summarize_all(items_, llm_):
                out = []
                for it in items_:
                    try:
                        s = summarize_update(it["source"], it["title"], it["url"], llm_)
                    except Exception as exc:
                        s = f"(요약 실패: {exc})\n출처: {it['url']}"
                    out.append({**it, "summary": s})
                return out

            results = await nicegui_run.io_bound(_summarize_all, items, llm)

            clustered = False
            if len(results) >= 3:
                _step(4)
                results = await nicegui_run.io_bound(
                    cluster_news_results,
                    results, question, embed_url, embed_model, embed_timeout,
                )
                clustered = True

            answer_summary = ''
            if results:
                _step(5)
                answer_summary = await nicegui_run.io_bound(
                    summarize_clusters_for_question, question, results, llm, approximate,
                )

            state['results'] = results
            _render_results(
                results,
                clustered=clustered,
                question=question,
                keywords=search_queries,
                answer_summary=answer_summary,
                approximate=approximate,
            )
            n_clusters = len({it.get('cluster', 0) for it in results}) if clustered else 0
            cluster_info = f' / {n_clusters}개 클러스터' if clustered else ''
            kws_str = ', '.join(search_queries)
            approx_note = (
                ' — <b style="color:var(--text-2);">명확히 관련된 기사 없음(참고용 근접)</b>'
                if approximate else ''
            )
            result_count_label.content = (
                f'<div class="info-block"><b>뉴스 검색 결과: {len(results)}건{cluster_info}</b>'
                f'{approx_note} (검색 표현: {_html.escape(kws_str)})</div>'
            )
            progress_area.content = ''
            if results:
                ui.notify(f'{len(results)}건 검색·요약 완료', type='positive', position='top')
            else:
                ui.notify('검색 결과가 없습니다. 질문이나 날짜를 조정해 보세요.', type='warning', position='top')
        except asyncio.CancelledError:
            log.info('뉴스 검색 취소됨')
            progress_area.content = (
                '<div class="muted-text" style="color:var(--warning);">검색을 중지했습니다.</div>'
            )
            ui.notify('검색을 중지했습니다.', type='warning', position='top')
        except Exception as e:
            log.error('뉴스 검색 오류: %s', e)
            ui.notify(f'검색 오류: {e}', type='negative', position='top')
            progress_area.content = (
                '<div class="muted-text" style="color:var(--danger);">검색 실패</div>'
            )
        finally:
            skeleton_area.visible = False
            _yna_ctl['busy'] = False
            _yna_ctl['task'] = None
            fetch_btn_yna.text = '검색 및 요약'
            fetch_btn_yna.classes(remove='is-stop')

    def _on_yna_click():
        if _yna_ctl['busy']:
            if _yna_ctl['task'] is not None:
                _yna_ctl['task'].cancel()
            return
        _spawn(fetch_news_search())

    fetch_btn_yna.on_click(_on_yna_click)
