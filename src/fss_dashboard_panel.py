"""
금융감독원(FSS) Open API 기반 Risk Dashboard 패널.

표시 항목:
  - 제재·조치 현황
  - 금융사고 공시
  - 검사·감독 결과
  - 금융회사 경영공시 (보도자료 기반 대체)

FSS Open API가 응답하지 않을 경우 연합뉴스 RSS 카테고리별 키워드 검색으로 대체.
"""
import html as _html
import datetime

import requests
import feedparser

from nicegui import ui, run as nicegui_run
from logger import get_logger

log = get_logger("fss_dashboard")

# ── FSS Open API 엔드포인트 ───────────────────────────────────────────────────
# 구 open.fss.or.kr 서비스 종료 → www.fss.or.kr 이전, 파라미터 auth→authKey
# 현재 확인된 동작 엔드포인트: fcnInfo.jsp (금융소비자뉴스/보도자료)
_BASE = "http://www.fss.or.kr/fss/kr/openApi/api"
_FSS_FCN_URL = f"{_BASE}/fcnInfo.jsp"

# 대시보드 4개 카테고리 — FSS API는 fcnInfo(보도자료)만 동작 확인됨;
# 나머지는 연합뉴스 RSS 키워드 폴백으로 채움
_ENDPOINTS = {
    "금융감독원 보도자료": _FSS_FCN_URL,
    "금융사고 공시":       None,
    "검사·감독 결과":      None,
    "금융회사 경영공시":   None,
}

# 카테고리별 연합뉴스 폴백 키워드
_YONHAP_FALLBACK_KEYWORDS = {
    "금융감독원 보도자료": ["금감원 보도자료", "금융감독원 발표", "금감원 공지", "금감원"],
    "금융사고 공시":       ["금융사고", "금감원 공시", "횡령", "사기", "금융범죄"],
    "검사·감독 결과":      ["금감원 검사", "금융감독원 검사", "금감원 감독", "현장검사"],
    "금융회사 경영공시":   ["금융회사 공시", "경영공시", "금감원 공개", "지배구조"],
}

_YONHAP_RSS_URLS = [
    "https://www.yna.co.kr/rss/economy.xml",
    "https://www.yna.co.kr/rss/market.xml",
]

_REQUESTS_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _fetch_fss_fcn(api_key: str, count: int = 10) -> list[dict]:
    """
    FSS fcnInfo API (금융소비자뉴스/보도자료) 호출.
    www.fss.or.kr 이전 후 확인된 유일한 동작 엔드포인트.
    """
    try:
        today = datetime.date.today().strftime("%Y%m%d")
        start = (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
        resp = requests.get(
            _FSS_FCN_URL,
            params={
                "authKey": api_key,
                "pageCount": max(count, 5),
                "apiType": "json",
                "startDate": start,
                "endDate": today,
            },
            headers=_REQUESTS_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        import json as _json
        parsed = _json.loads(resp.content.decode("euc-kr", errors="replace"))
        raw = parsed.get("reponse", {}).get("result", [])
        return [
            {
                "title":   item.get("subject", "").strip(),
                "url":     item.get("originUrl", "").strip(),
                "regDate": item.get("regDate", "")[:10],
                "content": "",
            }
            for item in raw[:count]
            if item.get("subject")
        ]
    except Exception as exc:
        log.warning("FSS fcnInfo API 호출 실패: %s", exc)
        return []


def _fetch_yonhap_entries_cached() -> list[dict]:
    """연합뉴스 RSS를 가져옵니다 (경제+시장 합산, 중복 제거)."""
    entries: dict[str, dict] = {}
    for rss_url in _YONHAP_RSS_URLS:
        try:
            feed = feedparser.parse(rss_url)
            for e in feed.entries:
                link = e.get("link", "")
                if link and link not in entries:
                    entries[link] = {
                        "title": e.get("title", "").strip(),
                        "url": link,
                        "summary": e.get("summary", "").strip(),
                        "regDate": "",
                    }
                    t = e.get("published_parsed")
                    if t:
                        try:
                            entries[link]["regDate"] = (
                                f"{t.tm_year}-{t.tm_mon:02d}-{t.tm_mday:02d}"
                            )
                        except Exception:
                            pass
        except Exception as exc:
            log.warning("연합뉴스 RSS 파싱 오류 (%s): %s", rss_url, exc)
    return list(entries.values())


def _search_yonhap_for_category(
    yonhap_entries: list[dict], keywords: list[str], count: int
) -> list[dict]:
    """연합뉴스 항목에서 카테고리 키워드에 매칭되는 기사를 반환."""
    # 개별 어절로도 확장 (복합 키워드 처리)
    expanded: list[str] = []
    seen: set[str] = set()
    for kw in keywords:
        kw_lo = kw.lower()
        if kw_lo not in seen:
            expanded.append(kw_lo)
            seen.add(kw_lo)
        for tok in kw_lo.split():
            if len(tok) >= 2 and tok not in seen:
                expanded.append(tok)
                seen.add(tok)

    results = []
    for e in yonhap_entries:
        text = (e["title"] + " " + e["summary"]).lower()
        if any(kw in text for kw in expanded):
            results.append({
                "title": e["title"],
                "url": e["url"],
                "regDate": e.get("regDate", ""),
                "content": e.get("summary", "")[:200],
                "_source": "연합뉴스",
            })
            if len(results) >= count:
                break
    return results


def _fetch_all_categories(api_key: str, count: int = 10) -> dict[str, list[dict]]:
    """4개 카테고리를 수집합니다.
    - '금융감독원 보도자료': FSS fcnInfo API → 실패 시 연합뉴스 대체
    - 나머지 3개: 연합뉴스 RSS 키워드 검색 (해당 FSS API 엔드포인트 미확인)
    """
    yonhap_entries: list[dict] | None = None

    results = {}
    for label, fss_url in _ENDPOINTS.items():
        items: list[dict] = []

        # FSS API가 있는 카테고리만 먼저 시도
        if fss_url and api_key:
            items = _fetch_fss_fcn(api_key, count)
            if items:
                log.info("FSS API '%s': %d건", label, len(items))

        if not items:
            if yonhap_entries is None:
                yonhap_entries = _fetch_yonhap_entries_cached()
            kws = _YONHAP_FALLBACK_KEYWORDS.get(label, [])
            items = _search_yonhap_for_category(yonhap_entries, kws, count)
            if items:
                log.info("FSS '%s' → 연합뉴스 대체 %d건", label, len(items))
            else:
                log.info("FSS '%s' → 연합뉴스도 결과 없음", label)

        results[label] = items
    return results


def build_fss_dashboard_panel(config: dict):
    """Risk DashBoard 패널을 현재 NiceGUI 컨텍스트에 렌더링합니다."""

    fss_api_key = config.get("fss_api_key", "").strip()
    state = {"data": {}, "last_updated": None}

    # ── 헤더 ─────────────────────────────────────────────────────────────
    with ui.element('div').classes('page-head'):
        ui.html(
            '<div class="titles">'
            '<div class="page-title">Risk DashBoard</div>'
            '<div class="page-subtitle">'
            '금융감독원 Open API 기반 — 제재·사고·검사·경영공시 현황을 한눈에 확인합니다.'
            '</div>'
            '</div>'
        )

    # ── API 키 없을 때 경고 배너 ──────────────────────────────────────────
    if not fss_api_key:
        with ui.element('div').style(
            'margin:16px 32px;padding:12px 16px;'
            'background:#fef3c7;border:1px solid #d97706;border-radius:8px;'
            'font-size:13px;color:#92400e;'
        ):
            ui.html(
                '<b>⚠ FSS API 키 미설정</b> — config.json의 <code>fss_api_key</code> 값을 입력하면 '
                '실제 데이터를 불러옵니다. 현재는 연합뉴스 RSS로 대체됩니다.'
            )

    # ── 컨트롤 바 ────────────────────────────────────────────────────────
    with ui.element('div').style(
        'display:flex;align-items:center;gap:12px;padding:12px 32px;'
        'border-bottom:1px solid var(--border);flex-shrink:0;'
    ):
        count_input = ui.number(
            label='카테고리별 조회 건수', value=5, min=1, max=20, step=1,
        ).props('outlined dense hide-bottom-space').style('width:180px;')

        refresh_btn = ui.button('데이터 조회').classes('btn-primary-mono')
        last_updated_label = ui.html('<span style="color:var(--text-4);font-size:12px;"></span>')

    # ── 대시보드 그리드 ──────────────────────────────────────────────────
    dashboard_grid = ui.element('div').style(
        'display:grid;grid-template-columns:1fr 1fr;gap:16px;'
        'padding:20px 32px;flex:1;overflow-y:auto;'
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
            return ""
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
            icon_map = {
                "제재·조치 현황":    ("gavel",           "#dc2626"),
                "금융사고 공시":    ("warning",          "#d97706"),
                "검사·감독 결과":   ("manage_search",    "#1d4ed8"),
                "금융회사 경영공시": ("domain",           "#166534"),
            }
            for category, items in data.items():
                icon_name, icon_color = icon_map.get(category, ("info", "var(--text-3)"))
                with ui.element('div').style(
                    'background:var(--bg);border:1px solid var(--border);'
                    'border-radius:12px;padding:16px;display:flex;flex-direction:column;'
                    'min-height:280px;'
                ):
                    # 카드 헤더
                    is_yonhap = items and items[0].get("_source") == "연합뉴스"
                    source_note = (
                        '<span style="font-size:10.5px;color:var(--text-4);margin-left:6px;">'
                        '연합뉴스 대체</span>'
                    ) if is_yonhap else ""
                    ui.html(
                        f'<div style="display:flex;align-items:center;gap:8px;'
                        f'margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid var(--border);">'
                        f'<span class="material-symbols-outlined" '
                        f'style="font-size:18px;color:{icon_color};">{icon_name}</span>'
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
                            'padding:20px 0;">데이터 없음 (FSS API 및 연합뉴스 검색 결과 없음)</div>'
                        )
                    else:
                        for item in items:
                            _render_item(item)

    # ── 조회 핸들러 ──────────────────────────────────────────────────────
    async def refresh_dashboard():
        count = int(count_input.value or 5)
        progress_bar.visible = True
        refresh_btn.props(add='disable')
        last_updated_label.content = (
            '<span style="color:var(--text-4);font-size:12px;">조회 중…</span>'
        )

        try:
            data = await nicegui_run.io_bound(_fetch_all_categories, fss_api_key, count)

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
                '<span style="color:#b91c1c;font-size:12px;">조회 실패</span>'
            )
        finally:
            progress_bar.visible = False
            refresh_btn.props(remove='disable')

    refresh_btn.on_click(refresh_dashboard)

    # 초기 빈 그리드 렌더링
    with dashboard_grid:
        for category in _ENDPOINTS:
            icon_map = {
                "제재·조치 현황":    ("gavel",           "#dc2626"),
                "금융사고 공시":    ("warning",          "#d97706"),
                "검사·감독 결과":   ("manage_search",    "#1d4ed8"),
                "금융회사 경영공시": ("domain",           "#166534"),
            }
            icon_name, icon_color = icon_map.get(category, ("info", "var(--text-3)"))
            with ui.element('div').style(
                'background:var(--bg);border:1px solid var(--border);'
                'border-radius:12px;padding:16px;min-height:240px;'
                'display:flex;flex-direction:column;align-items:center;justify-content:center;'
            ):
                ui.html(
                    f'<span class="material-symbols-outlined" '
                    f'style="font-size:32px;color:var(--border-strong);margin-bottom:10px;">'
                    f'{icon_name}</span>'
                    f'<div style="font-size:13px;font-weight:600;color:var(--text-3);">'
                    f'{_html.escape(category)}</div>'
                    f'<div style="font-size:12px;color:var(--text-4);margin-top:4px;">'
                    f'조회 버튼을 눌러 데이터를 불러오세요</div>'
                )
