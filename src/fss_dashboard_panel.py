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

# ── 네이버 뉴스 검색 API ──────────────────────────────────────────────────────
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
    """4개 카테고리를 네이버 뉴스 검색으로 수집한다(원문 링크가 유효한 실제 기사).

    api_key 인자는 호출부 호환을 위해 유지하나 사용하지 않는다(네이버 자격증명은
    NAVER_CLIENT_ID/SECRET 환경변수 사용).
    """
    results = {}
    for label, query in _CATEGORY_QUERIES.items():
        items = _fetch_naver_news(query, count)
        log.info("네이버 뉴스 '%s': %d건", label, len(items))
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
            '네이버 뉴스 검색 기반 — 보도자료·사고·검사·경영공시 관련 기사를 한눈에 확인합니다.'
            '</div>'
            '</div>'
        )

    # ── 네이버 검색 자격증명 없을 때 경고 배너 ────────────────────────────
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
                '<b>⚠ 네이버 검색 자격증명 미설정</b> — '
                '<code>NAVER_CLIENT_ID</code> / <code>NAVER_CLIENT_SECRET</code> 환경변수(HF Spaces Secrets)를 '
                '설정하면 뉴스 기사를 불러옵니다.'
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
                "제재·조치 현황":    ("gavel",           "#ef4444"),
                "금융사고 공시":    ("warning",          "#f59e0b"),
                "검사·감독 결과":   ("manage_search",    "#3b82f6"),
                "금융회사 경영공시": ("domain",           "#22c55e"),
            }
            for category, items in data.items():
                icon_name, icon_color = icon_map.get(category, ("info", "var(--text-3)"))
                with ui.element('div').style(
                    'background:var(--bg);border:1px solid var(--border);'
                    'border-radius:12px;padding:16px;display:flex;flex-direction:column;'
                    'min-height:280px;'
                ):
                    # 카드 헤더
                    is_naver = items and items[0].get("_source") == "네이버뉴스"
                    source_note = (
                        '<span style="font-size:10.5px;color:var(--text-4);margin-left:6px;">'
                        '네이버뉴스</span>'
                    ) if is_naver else ""
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
                            'padding:20px 0;">데이터 없음 (네이버 뉴스 검색 결과 없음)</div>'
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
                '<span style="color:var(--danger);font-size:12px;">조회 실패</span>'
            )
        finally:
            progress_bar.visible = False
            refresh_btn.props(remove='disable')

    refresh_btn.on_click(refresh_dashboard)

    # 초기 빈 그리드 렌더링
    with dashboard_grid:
        for category in _CATEGORY_QUERIES:
            icon_map = {
                "제재·조치 현황":    ("gavel",           "#ef4444"),
                "금융사고 공시":    ("warning",          "#f59e0b"),
                "검사·감독 결과":   ("manage_search",    "#3b82f6"),
                "금융회사 경영공시": ("domain",           "#22c55e"),
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
