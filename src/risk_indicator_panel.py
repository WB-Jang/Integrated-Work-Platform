"""
Risk Indicator Dashboard — 은행 재무 건전성 지표 패널.

은행별 핵심 재무 지표(BIS 자기자본비율, NPL ratio, ROA, ROE, 유동성,
총자산 등)와 추세 그래프를 한 화면에서 비교할 수 있도록 표시.

데이터 소스:
  - 금융감독원 OpenAPI (FSS_API_KEY 환경변수 필요)
  - 호출 실패/키 부재 시 자동으로 mock 데이터로 대체

탭 구성:
  1. 단일 은행 상세 — 선택 은행의 지표 카드 + 분기별 시계열
  2. 은행 비교 — 모든 은행을 정렬 가능한 테이블 + 막대그래프로 비교
"""
from __future__ import annotations

import os
import datetime
import html as _html
import random

import requests

from nicegui import ui
from logger import get_logger

log = get_logger("risk_indicator")


# ─── 상수 ────────────────────────────────────────────────────────────────────
# 주요 시중·특수 은행 목록 (개별 은행 단위 화면 + 비교 화면 공용)
BANKS = [
    {"code": "kb",      "name": "KB국민은행"},
    {"code": "shinhan", "name": "신한은행"},
    {"code": "hana",    "name": "하나은행"},
    {"code": "woori",   "name": "우리은행"},
    {"code": "nh",      "name": "NH농협은행"},
    {"code": "ibk",     "name": "IBK기업은행"},
    {"code": "kdb",     "name": "KDB산업은행"},
    {"code": "scfb",    "name": "SC제일은행"},
    {"code": "citi",    "name": "한국씨티은행"},
]

# 지표 메타 — key, label, unit, 좋은 방향(↑ or ↓), 임계값(주의/위험)
# 임계값은 일반적인 감독 기준에 근사한 값으로 시각적 색상 표시 목적
INDICATORS = [
    {"key": "bis",        "label": "BIS 자기자본비율", "unit": "%",  "good": "up",
     "warn": 13.0, "danger": 10.5, "desc": "총자본 / 위험가중자산. 감독 권고 10.5% 이상."},
    {"key": "tier1",      "label": "기본자본비율(Tier 1)", "unit": "%", "good": "up",
     "warn": 11.5, "danger": 8.5, "desc": "보통주자본 + 기타기본자본 비율."},
    {"key": "npl",        "label": "고정이하여신비율(NPL)", "unit": "%", "good": "down",
     "warn": 0.7, "danger": 1.5, "desc": "부실여신/총여신. 낮을수록 자산건전성 양호."},
    {"key": "roa",        "label": "ROA (총자산순이익률)", "unit": "%", "good": "up",
     "warn": 0.5, "danger": 0.2, "desc": "당기순이익/총자산. 수익성 지표."},
    {"key": "roe",        "label": "ROE (자기자본순이익률)", "unit": "%", "good": "up",
     "warn": 7.0, "danger": 4.0, "desc": "당기순이익/자기자본."},
    {"key": "liquidity",  "label": "유동성커버리지비율(LCR)", "unit": "%", "good": "up",
     "warn": 105.0, "danger": 100.0, "desc": "30일간 순현금유출 대비 고유동성자산."},
    {"key": "loan_dep",   "label": "예대율", "unit": "%", "good": "neutral",
     "warn": 100.0, "danger": 105.0, "desc": "총대출/총예수금. 100% 부근 권장."},
    {"key": "total_asset","label": "총자산", "unit": "조원", "good": "up",
     "warn": 0, "danger": 0, "desc": "은행 규모 지표."},
]

# 월 라벨 (최근 n개월, 기준월 선택창에서 사용)
def _recent_months(n: int = 12) -> list[str]:
    today = datetime.date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return list(reversed(out))


# ─── Mock 데이터 생성 ────────────────────────────────────────────────────────
# 실제 FSS API 응답 스키마가 확정되기 전까지 사용. 은행/지표별로
# 산업 평균에 가까운 합리적인 분포로 무작위 생성하되, 시드를 은행 코드에
# 고정하여 같은 은행은 항상 같은 값이 나오도록 함.
def _mock_bank_indicators(bank_code: str) -> dict:
    rnd = random.Random(hash(bank_code) & 0xFFFFFFFF)
    base = {
        "bis":         round(rnd.uniform(13.5, 18.0), 2),
        "tier1":       round(rnd.uniform(11.0, 15.5), 2),
        "npl":         round(rnd.uniform(0.20, 0.95), 2),
        "roa":         round(rnd.uniform(0.35, 0.85), 2),
        "roe":         round(rnd.uniform(6.0, 11.5), 2),
        "liquidity":   round(rnd.uniform(105.0, 145.0), 1),
        "loan_dep":    round(rnd.uniform(92.0, 102.0), 1),
        "total_asset": round(rnd.uniform(180.0, 520.0), 1),
    }
    # 월별 시계열 — 마지막 달은 base 값, 앞으로 갈수록 ±3~4% 변동
    months = _recent_months(12)
    series = {k: [] for k in base}
    for k, v in base.items():
        cur = v * rnd.uniform(0.93, 1.05)
        for _ in months:
            cur = max(cur * rnd.uniform(0.97, 1.03), 0.01)
            series[k].append(round(cur, 2))
        series[k][-1] = v   # 마지막 달은 정확히 base 값
    return {"latest": base, "series": series, "months": months}


# ─── FSS API 호출 (실패 시 mock) ──────────────────────────────────────────────
# 현재 금감원 OpenAPI 중 은행별 재무 지표를 직접 노출하는 표준 엔드포인트가
# 공개되어 있지 않습니다. 향후 정식 엔드포인트가 확정되면 _fetch_from_fss
# 내부만 교체하면 됩니다. 그 전까지는 mock 데이터를 그대로 사용합니다.
def _fetch_from_fss(api_key: str, bank_code: str) -> dict | None:
    if not api_key:
        return None
    try:
        # placeholder: 향후 실제 엔드포인트로 교체
        # 예) requests.get(f"https://api.fss.or.kr/.../{bank_code}",
        #                  params={"authKey": api_key}, timeout=15)
        return None
    except Exception as e:
        log.warning("FSS API 호출 실패 (%s): %s", bank_code, e)
        return None


def _get_bank_indicators(api_key: str, bank_code: str) -> dict:
    fetched = _fetch_from_fss(api_key, bank_code)
    if fetched is not None:
        return fetched
    return _mock_bank_indicators(bank_code)


# ─── UI 헬퍼 ─────────────────────────────────────────────────────────────────
def _eval_status(ind: dict, value: float) -> tuple[str, str]:
    """지표 값이 정상/주의/위험 중 어디인지 판정. (status, color) 반환."""
    # 리터럴 hex 유지 — _indicator_card_html 이 "{color}1a" 로 알파값을 이어붙여
    # 배지 배경을 만들기 때문에 var(--x) 는 여기서 쓸 수 없다.
    if ind["good"] == "up":
        if value < ind["danger"]:
            return ("위험", "#ef4444")
        if value < ind["warn"]:
            return ("주의", "#f59e0b")
        return ("양호", "#22c55e")
    if ind["good"] == "down":
        if value > ind["danger"]:
            return ("위험", "#ef4444")
        if value > ind["warn"]:
            return ("주의", "#f59e0b")
        return ("양호", "#22c55e")
    return ("표시", "#94a3b8")  # neutral


def _format_value(v, unit: str) -> str:
    if unit == "조원":
        return f"{v:,.1f} {unit}"
    return f"{v:,.2f}{unit}"


def _indicator_card_html(ind: dict, value: float, prev: float | None = None) -> str:
    status, color = _eval_status(ind, value)
    delta_html = ""
    if prev is not None and prev != 0:
        diff = value - prev
        pct = diff / prev * 100
        arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "—")
        # 좋은 방향이면 녹색, 나쁜 방향이면 빨강
        good = (
            (ind["good"] == "up" and diff > 0)
            or (ind["good"] == "down" and diff < 0)
        )
        d_color = "var(--success)" if good else ("var(--danger)" if diff != 0 else "var(--text-3)")
        delta_html = (
            f'<span style="font-size:12px;color:{d_color};font-weight:500;">'
            f'{arrow} {abs(pct):.2f}%</span>'
        )
    return (
        '<div style="border:1px solid var(--border);border-radius:var(--radius);'
        'background:var(--bg);padding:16px;display:flex;flex-direction:column;'
        'gap:8px;min-height:120px;">'
        f'<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">'
        f'  <div style="font-size:12.5px;color:var(--text-3);font-weight:500;">'
        f'    {_html.escape(ind["label"])}'
        f'  </div>'
        f'  <span style="font-size:10px;font-weight:600;padding:2px 8px;'
        f'  border-radius:10px;color:{color};background:{color}1a;">{status}</span>'
        f'</div>'
        f'<div style="display:flex;align-items:baseline;gap:6px;">'
        f'  <div style="font-size:22px;font-weight:700;color:var(--text);">'
        f'    {_format_value(value, ind["unit"])}'
        f'  </div>'
        f'  {delta_html}'
        f'</div>'
        f'<div style="font-size:11.5px;color:var(--text-4);line-height:1.5;">'
        f'  {_html.escape(ind["desc"])}'
        f'</div>'
        '</div>'
    )


# ─── DIVE(금융감독원 금융통계 시각화) 임베드 ────────────────────────────────
# diva.fss.or.kr = FISIS(금융통계정보시스템)의 시각화 프론트엔드. 원천 데이터는
# FISIS OpenAPI(fisis.fss.or.kr/openapi)로 공개되나, 사용자 요청에 따라 DIVE 화면을
# 그대로 임베드해 감독원 데이터를 직접 조회하도록 한다.
_DIVE_URL = "https://diva.fss.or.kr/"


def _build_dive_embed():
    """DIVE 원본 화면을 iframe으로 임베드. 정부 사이트가 X-Frame-Options로 임베드를
    제한할 수 있으므로 '새 창 열기' 링크를 항상 함께 노출한다."""
    with ui.element('div').classes('page-head'):
        ui.html(
            '<div class="titles">'
            '<div class="page-title">Risk Indicator Dashboard</div>'
            '<div class="page-subtitle">금융감독원 DIVE(금융통계 시각화)에서 은행 재무·건전성 데이터를 직접 조회합니다.</div>'
            '</div>'
        )

    with ui.element('div').style(
        'display:flex;align-items:center;gap:12px;margin:-4px 0 10px;flex-wrap:wrap;'
    ):
        ui.html(
            '<span style="font-size:11.5px;color:var(--text-4);">'
            '화면이 비어 보이면 감독원 사이트가 임베드를 제한한 것입니다 — 오른쪽 버튼으로 새 창에서 열어주세요.</span>'
        )
        ui.link('DIVE 새 창에서 열기 ↗', target=_DIVE_URL, new_tab=True).style(
            'font-size:12px;font-weight:600;color:var(--text);text-decoration:none;'
            'border:1px solid var(--border);border-radius:6px;padding:5px 12px;'
        )

    ui.html(
        f'<iframe src="{_DIVE_URL}" title="FSS DIVE" '
        f'referrerpolicy="no-referrer" '
        f'style="width:100%;height:calc(100vh - 230px);min-height:560px;'
        f'border:1px solid var(--border);border-radius:8px;background:#fff;"></iframe>'
    )


# ─── 메인 빌더 ───────────────────────────────────────────────────────────────
def build_risk_indicator_panel(config: dict):
    """Risk Indicator Dashboard 패널 — DIVE 임베드(기본) + 참고 지표(샘플) 보조 뷰."""
    # 상단 뷰 전환기: DIVE 원본(기본) / 참고 지표(샘플)
    with ui.element('div').style(
        'display:flex;gap:4px;border-bottom:1px solid var(--border);'
        'margin-bottom:14px;padding-top:4px;'
    ):
        view_state = ['dive']  # 'dive' | 'native'
        view_btns: dict = {}
        for k, label in [('dive', 'DIVE 원본'), ('native', '참고 지표 (샘플)')]:
            b = ui.element('button').style('cursor:pointer;')
            with b:
                ui.html(f'<span>{label}</span>')
            view_btns[k] = b

    dive_container = ui.element('div')
    native_container = ui.element('div')

    def _view_btn_style(active: bool) -> str:
        weight = '600' if active else '500'
        color = 'var(--text)' if active else 'var(--text-3)'
        border = 'var(--text)' if active else 'transparent'
        return (
            f'background:transparent;border:none;border-bottom:2px solid {border};'
            f'padding:9px 14px;cursor:pointer;font-size:13px;font-weight:{weight};'
            f'color:{color};transition:all .15s;'
        )

    def _switch_view(key: str):
        view_state[0] = key
        for k, b in view_btns.items():
            b.style(_view_btn_style(k == key))
        dive_container.style(f'display:{"block" if key == "dive" else "none"};')
        native_container.style(f'display:{"block" if key == "native" else "none"};')

    view_btns['dive'].on('click', lambda _e: _switch_view('dive'))
    view_btns['native'].on('click', lambda _e: _switch_view('native'))

    with dive_container:
        _build_dive_embed()

    with native_container:
        _build_native_dashboard(config)

    _switch_view('dive')


def _build_native_dashboard(config: dict):
    """(참고용) 은행별 지표 카드·비교 — 실 FISIS 연동 전까지 샘플 데이터로 표시."""

    api_key = os.environ.get("FSS_API_KEY", "").strip() or config.get("fss_api_key", "")
    has_real_data = bool(_fetch_from_fss(api_key, BANKS[0]["code"]))  # 현재는 항상 False

    months_list = _recent_months(12)

    state = {
        "selected_bank": BANKS[0]["code"],
        "month_idx": len(months_list) - 1,  # 기본값: 최신월
        "cache": {},  # bank_code -> indicators dict
    }

    def _data_for(bank_code: str) -> dict:
        if bank_code not in state["cache"]:
            state["cache"][bank_code] = _get_bank_indicators(api_key, bank_code)
        return state["cache"][bank_code]

    # ── 헤더 ──────────────────────────────────────────────────────────────
    with ui.element('div').classes('page-head'):
        ui.html(
            '<div class="titles">'
            '<div class="page-title">Risk Indicator Dashboard</div>'
            '<div class="page-subtitle">은행별 자본·자산건전성·수익성·유동성 지표를 한 화면에서 모니터링합니다.</div>'
            '</div>'
        )

    # 데이터 출처 안내
    src_msg = (
        '<span style="color:var(--success);">FSS Open API 연동</span>'
        if has_real_data else
        '<span style="color:var(--accent);">샘플 데이터 표시 중</span> · 실데이터 연동 대기 (FSS_API_KEY 설정 필요)'
    )
    ui.html(
        f'<div style="font-size:11.5px;color:var(--text-4);margin:-6px 0 10px;">'
        f'데이터 출처: {src_msg}</div>'
    )

    # 기준월 선택 — 단일 은행 상세/은행 비교 탭 공용
    with ui.element('div').style(
        'display:flex;align-items:center;gap:10px;margin-bottom:14px;'
    ):
        ui.html(
            '<span style="font-size:12px;color:var(--text-3);font-weight:600;">'
            '기준월</span>'
        )
        month_select = ui.select(
            options={i: m for i, m in enumerate(months_list)},
            value=state["month_idx"],
        ).props('outlined dense options-dense').classes('w-32')

    # ── 탭 ────────────────────────────────────────────────────────────────
    with ui.element('div').style(
        'display:flex;gap:4px;border-bottom:1px solid var(--border);margin-bottom:14px;'
    ):
        tab_state = ['detail']  # 'detail' | 'compare'
        tab_btns: dict = {}
        for k, label in [('detail', '단일 은행 상세'), ('compare', '은행 비교')]:
            btn = ui.element('button').style(
                'background:transparent;border:none;border-bottom:2px solid transparent;'
                'padding:9px 14px;cursor:pointer;font-size:13px;font-weight:500;'
                'color:var(--text-3);transition:all .15s;'
            )
            with btn:
                ui.html(f'<span>{label}</span>')
            tab_btns[k] = btn

    # 탭 컨텐츠 컨테이너
    detail_container = ui.element('div')
    compare_container = ui.element('div')

    def _tab_btn_style(active: bool) -> str:
        if active:
            return (
                'background:transparent;border:none;'
                'border-bottom:2px solid var(--text);'
                'padding:9px 14px;cursor:pointer;font-size:13px;font-weight:600;'
                'color:var(--text);transition:all .15s;'
            )
        return (
            'background:transparent;border:none;'
            'border-bottom:2px solid transparent;'
            'padding:9px 14px;cursor:pointer;font-size:13px;font-weight:500;'
            'color:var(--text-3);transition:all .15s;'
        )

    def _switch_tab(key: str):
        tab_state[0] = key
        for k, b in tab_btns.items():
            b.style(_tab_btn_style(k == key))
        detail_container.style(f'display:{"block" if key == "detail" else "none"};')
        compare_container.style(f'display:{"block" if key == "compare" else "none"};')

    tab_btns['detail'].on('click', lambda _e: _switch_tab('detail'))
    tab_btns['compare'].on('click', lambda _e: _switch_tab('compare'))

    # ─────────────────────────────────────────────────────────────────────
    # ▶ 단일 은행 상세 탭
    # ─────────────────────────────────────────────────────────────────────
    with detail_container:
        # 은행 선택
        with ui.element('div').style(
            'display:flex;align-items:center;gap:10px;margin-bottom:14px;'
        ):
            ui.html(
                '<span style="font-size:12px;color:var(--text-3);font-weight:600;">'
                '은행 선택</span>'
            )
            bank_select = ui.select(
                options={b["code"]: b["name"] for b in BANKS},
                value=state["selected_bank"],
            ).props('outlined dense options-dense').classes('w-64')

        # 지표 카드 그리드
        cards_grid = ui.element('div').style(
            'display:grid;'
            'grid-template-columns:repeat(auto-fit, minmax(220px, 1fr));'
            'gap:12px;margin-bottom:20px;'
        )

        # 시계열 그래프 — Quasar plotly가 무겁고 NiceGUI 인라인 차트가 단순하므로
        # 자체 인라인 SVG 라인차트로 표시 (의존성 추가 없이 깔끔)
        chart_section = ui.element('div').style(
            'display:grid;'
            'grid-template-columns:repeat(auto-fit, minmax(360px, 1fr));'
            'gap:12px;'
        )

        def _render_detail():
            d = _data_for(state["selected_bank"])
            series = d["series"]
            months = d["months"]
            idx = state["month_idx"]
            latest = {k: v[idx] for k, v in series.items()}

            # 카드 — 선택된 기준월 시점 값 (전월 대비 증감 표시)
            cards_grid.clear()
            with cards_grid:
                for ind in INDICATORS:
                    prev = series[ind["key"]][idx - 1] if idx >= 1 else None
                    ui.html(_indicator_card_html(ind, latest[ind["key"]], prev))

            # 시계열 차트 — 기준월까지의 추이
            trunc_series = {k: v[:idx + 1] for k, v in series.items()}
            trunc_months = months[:idx + 1]
            chart_section.clear()
            with chart_section:
                # 자본/자산건전성/수익성/유동성 4개 묶음
                groups = [
                    ("자본 적정성",    ["bis", "tier1"]),
                    ("자산 건전성",    ["npl"]),
                    ("수익성",         ["roa", "roe"]),
                    ("유동성·예대율",  ["liquidity", "loan_dep"]),
                ]
                for title, keys in groups:
                    ui.html(_svg_line_chart(title, keys, trunc_series, trunc_months))

        def _on_bank_change(e):
            state["selected_bank"] = e.args if isinstance(e.args, str) else bank_select.value
            _render_detail()

        bank_select.on('update:model-value', _on_bank_change)

        # 초기 렌더
        _render_detail()

    # ─────────────────────────────────────────────────────────────────────
    # ▶ 은행 비교 탭
    # ─────────────────────────────────────────────────────────────────────
    with compare_container:
        # 지표 선택 (어떤 지표 기준으로 가로 비교)
        with ui.element('div').style(
            'display:flex;align-items:center;gap:10px;margin-bottom:14px;'
        ):
            ui.html(
                '<span style="font-size:12px;color:var(--text-3);font-weight:600;">'
                '비교 지표</span>'
            )
            ind_select = ui.select(
                options={i["key"]: i["label"] for i in INDICATORS},
                value="bis",
            ).props('outlined dense options-dense').classes('w-72')

        compare_chart = ui.html('')
        compare_table = ui.html('')

        def _render_compare():
            sel = ind_select.value
            ind = next(i for i in INDICATORS if i["key"] == sel)
            idx = state["month_idx"]
            rows = []
            for b in BANKS:
                d = _data_for(b["code"])
                rows.append((b["name"], d["series"][sel][idx]))

            # 정렬 (좋은 방향 우선)
            reverse = (ind["good"] != "down")
            rows.sort(key=lambda r: r[1], reverse=reverse)

            # 막대그래프 (가로형)
            max_v = max(r[1] for r in rows) or 1
            bars_html = ['<div style="display:flex;flex-direction:column;gap:6px;'
                         'padding:14px 18px;border:1px solid var(--border);'
                         'border-radius:var(--radius);background:var(--bg);'
                         'margin-bottom:14px;">']
            bars_html.append(
                f'<div style="font-size:12.5px;font-weight:600;color:var(--text);'
                f'margin-bottom:8px;">{_html.escape(ind["label"])} 비교 '
                f'<span style="color:var(--text-4);font-weight:400;font-size:11px;">'
                f'({"내림차순" if reverse else "오름차순"})</span></div>'
            )
            for name, v in rows:
                pct = v / max_v * 100
                status, color = _eval_status(ind, v)
                bars_html.append(
                    '<div style="display:flex;align-items:center;gap:10px;font-size:12.5px;">'
                    f'<span style="width:100px;color:var(--text-2);white-space:nowrap;'
                    f'overflow:hidden;text-overflow:ellipsis;">{_html.escape(name)}</span>'
                    '<div style="flex:1;height:18px;background:var(--bg-elev);'
                    'border-radius:4px;overflow:hidden;position:relative;">'
                    f'<div style="height:100%;width:{pct:.1f}%;background:{color};'
                    'transition:width .2s;"></div></div>'
                    f'<span style="width:90px;text-align:right;color:var(--text);'
                    f'font-weight:600;">{_format_value(v, ind["unit"])}</span>'
                    '</div>'
                )
            bars_html.append('</div>')
            compare_chart.content = ''.join(bars_html)

            # 테이블 — 모든 지표를 한눈에
            thead = (
                '<tr>'
                '<th style="text-align:left;padding:8px 10px;font-size:11px;'
                'color:var(--text-3);font-weight:600;border-bottom:1px solid var(--border);'
                'position:sticky;top:0;background:var(--bg);">은행</th>'
                + ''.join(
                    f'<th style="text-align:right;padding:8px 10px;font-size:11px;'
                    f'color:var(--text-3);font-weight:600;border-bottom:1px solid var(--border);'
                    f'position:sticky;top:0;background:var(--bg);" '
                    f'title="{_html.escape(i["desc"])}">{_html.escape(i["label"])}'
                    f'<br><span style="font-weight:400;color:var(--text-4);">'
                    f'({i["unit"]})</span></th>'
                    for i in INDICATORS
                )
                + '</tr>'
            )
            tbody_rows = []
            for b in BANKS:
                d = _data_for(b["code"])
                cells = [
                    f'<td style="padding:8px 10px;font-size:12.5px;color:var(--text);'
                    f'font-weight:500;border-bottom:1px solid var(--border);">'
                    f'{_html.escape(b["name"])}</td>'
                ]
                for i in INDICATORS:
                    v = d["series"][i["key"]][idx]
                    status, color = _eval_status(i, v)
                    cells.append(
                        f'<td style="padding:8px 10px;font-size:12.5px;'
                        f'text-align:right;color:{color};font-variant-numeric:tabular-nums;'
                        f'border-bottom:1px solid var(--border);">'
                        f'{_format_value(v, i["unit"])}</td>'
                    )
                tbody_rows.append('<tr>' + ''.join(cells) + '</tr>')

            compare_table.content = (
                '<div style="border:1px solid var(--border);border-radius:var(--radius);'
                'overflow:auto;max-height:560px;background:var(--bg);">'
                '<table style="width:100%;border-collapse:collapse;">'
                f'<thead>{thead}</thead>'
                f'<tbody>{"".join(tbody_rows)}</tbody>'
                '</table></div>'
            )

        ind_select.on(
            'update:model-value', lambda _e: _render_compare()
        )
        _render_compare()

    # 기준월 변경 시 두 탭 모두 갱신
    def _on_month_change(_e):
        state["month_idx"] = month_select.value
        _render_detail()
        _render_compare()

    month_select.on('update:model-value', _on_month_change)

    # 초기 탭 (Detail) 활성화
    _switch_tab('detail')


# ─── 인라인 SVG 라인차트 ─────────────────────────────────────────────────────
# 외부 차트 라이브러리 없이 시계열을 그리는 경량 SVG 생성기.
def _svg_line_chart(title: str, keys: list[str], series: dict, quarters: list[str]) -> str:
    W, H = 360, 200
    PAD_L, PAD_R, PAD_T, PAD_B = 36, 16, 28, 28
    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B

    colors = ["#f1f5f9", "#0ea5e9", "#a78bfa", "#22c55e", "#ef4444"]

    # 전체 데이터 범위
    all_vals = []
    for k in keys:
        all_vals.extend(series.get(k, []))
    if not all_vals:
        return ""
    vmin, vmax = min(all_vals), max(all_vals)
    if vmin == vmax:
        vmin -= 1
        vmax += 1
    span = vmax - vmin

    n = len(quarters)
    if n < 2:
        return ""
    step_x = plot_w / (n - 1)

    def _x(i): return PAD_L + i * step_x
    def _y(v): return PAD_T + plot_h - (v - vmin) / span * plot_h

    # Y축 4단계 그리드
    grid = []
    for g in range(5):
        y = PAD_T + g * plot_h / 4
        val = vmax - g * span / 4
        grid.append(
            f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}" '
            f'stroke="rgba(255,255,255,.1)" stroke-width="1" />'
        )
        grid.append(
            f'<text x="{PAD_L - 4}" y="{y + 3:.1f}" font-size="9" '
            f'text-anchor="end" fill="rgba(148,163,184,.6)">{val:.1f}</text>'
        )

    # X축 분기 라벨 (시작/중간/끝 정도만)
    xlabels = []
    label_idx = [0, n // 2, n - 1]
    for i in label_idx:
        xlabels.append(
            f'<text x="{_x(i):.1f}" y="{H - 8}" font-size="9" '
            f'text-anchor="middle" fill="rgba(148,163,184,.6)">{_html.escape(quarters[i])}</text>'
        )

    # 시리즈 라인
    lines = []
    legend = []
    for ki, k in enumerate(keys):
        col = colors[ki % len(colors)]
        pts = " ".join(f"{_x(i):.1f},{_y(v):.1f}" for i, v in enumerate(series[k]))
        lines.append(
            f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.8" />'
        )
        # 마지막 점 강조
        last_x = _x(n - 1)
        last_y = _y(series[k][-1])
        lines.append(
            f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3" fill="{col}" />'
        )
        ind_label = next((i["label"] for i in INDICATORS if i["key"] == k), k)
        legend.append(
            f'<span style="display:inline-flex;align-items:center;gap:5px;'
            f'font-size:11px;color:var(--text-3);">'
            f'<span style="display:inline-block;width:10px;height:2px;background:{col};">'
            f'</span>{_html.escape(ind_label)}</span>'
        )

    svg = (
        f'<svg width="100%" height="{H}" viewBox="0 0 {W} {H}" '
        f'preserveAspectRatio="none" style="display:block;">'
        + ''.join(grid)
        + ''.join(xlabels)
        + ''.join(lines)
        + '</svg>'
    )

    return (
        '<div style="border:1px solid var(--border);border-radius:var(--radius);'
        'background:var(--bg);padding:14px 16px;">'
        f'<div style="font-size:12.5px;font-weight:600;color:var(--text);'
        f'margin-bottom:6px;">{_html.escape(title)}</div>'
        f'<div style="display:flex;gap:14px;flex-wrap:wrap;margin-bottom:6px;">'
        f'{"".join(legend)}</div>'
        f'{svg}'
        '</div>'
    )
