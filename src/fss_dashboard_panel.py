"""
금융감독원(FSS) 관련 Risk Dashboard 패널.

표시 항목:
  - 금융감독원 보도자료
  - 금융사고 공시
  - 검사·감독 결과
  - 금융회사 경영공시

카테고리별 네이버 뉴스 검색 API로 관련 기사를 수집한다(원문 링크가 유효한 실제
기사). NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수(HF Spaces Secrets)가 필요하다.
"""
import os
import re
import html as _html
import datetime
from email.utils import parsedate_to_datetime

import requests

from nicegui import ui, run as nicegui_run
from logger import get_logger

log = get_logger("fss_dashboard")

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
            '금융감독원 보도·알림 원문 — 최신 보도자료를 직접 조회합니다 (접속 실패 시 네이버 뉴스로 폴백).'
            '</div>'
            '</div>'
        )

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
