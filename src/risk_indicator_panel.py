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

from nicegui import ui, run as nicegui_run
import fisis_client
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

# 지표 메타 — 파인(FINE) '은행 핵심경영지표' 구성에 맞춘 세트.
# key, label, unit, 좋은 방향(↑ or ↓), 임계값(주의/위험), 설명.
# 임계값은 일반적인 감독 기준에 근사한 값으로 시각적 색상 표시 목적.
INDICATORS = [
    {"key": "bis",         "label": "총자본비율(BIS)", "unit": "%",  "good": "up",
     "warn": 13.0, "danger": 10.5, "desc": "총자본 / 위험가중자산. 감독 권고 10.5% 이상."},
    {"key": "tier1",       "label": "기본자본비율(Tier 1)", "unit": "%", "good": "up",
     "warn": 11.5, "danger": 8.5, "desc": "기본자본 / 위험가중자산."},
    {"key": "cet1",        "label": "보통주자본비율(CET1)", "unit": "%", "good": "up",
     "warn": 9.5, "danger": 7.0, "desc": "보통주자본 / 위험가중자산."},
    {"key": "npl",         "label": "고정이하여신비율", "unit": "%", "good": "down",
     "warn": 0.7, "danger": 1.5, "desc": "고정이하여신 / 총여신. 낮을수록 자산건전성 양호."},
    {"key": "delinquency", "label": "원화대출 연체율", "unit": "%", "good": "down",
     "warn": 0.5, "danger": 1.0, "desc": "1개월 이상 연체 원화대출 / 총원화대출."},
    {"key": "roa",         "label": "총자산순이익률(ROA)", "unit": "%", "good": "up",
     "warn": 0.5, "danger": 0.2, "desc": "당기순이익 / 총자산."},
    {"key": "roe",         "label": "자기자본순이익률(ROE)", "unit": "%", "good": "up",
     "warn": 7.0, "danger": 4.0, "desc": "당기순이익 / 자기자본."},
    {"key": "nim",         "label": "순이자마진(NIM)", "unit": "%", "good": "up",
     "warn": 1.5, "danger": 1.0, "desc": "순이자이익 / 이자부자산."},
    {"key": "loan_dep",    "label": "원화예대율", "unit": "%", "good": "neutral",
     "warn": 100.0, "danger": 105.0, "desc": "원화대출금 / 원화예수금. 100% 이하 권장."},
    {"key": "lcr",         "label": "유동성커버리지비율(LCR)", "unit": "%", "good": "up",
     "warn": 105.0, "danger": 100.0, "desc": "고유동성자산 / 30일 순현금유출."},
    {"key": "total_asset", "label": "총자산", "unit": "조원", "good": "up",
     "warn": 0, "danger": 0, "desc": "은행 규모 지표."},
    {"key": "net_income",  "label": "당기순이익", "unit": "억원", "good": "up",
     "warn": 0, "danger": 0, "desc": "해당 기간 당기순이익."},
]

# 시계열 차트 묶음 (단위가 다른 총자산/당기순이익은 개별 차트)
CHART_GROUPS = [
    ("자본 적정성",      ["bis", "tier1", "cet1"]),
    ("자산 건전성",      ["npl", "delinquency"]),
    ("수익성",           ["roa", "roe", "nim"]),
    ("유동성·예대율",    ["lcr", "loan_dep"]),
    ("총자산",           ["total_asset"]),
    ("당기순이익",       ["net_income"]),
]


# ─── Mock 데이터 생성 (FISIS 코드 확정 전/조회 실패 시 폴백) ─────────────────
# 은행/지표별로 산업 평균에 가까운 분포로 생성하되, 시드를 은행 코드에 고정해
# 같은 은행은 항상 같은 값이 나오도록 한다. 주어진 분기(base_months)에 맞춰 생성.
_MOCK_BASE_RANGES = {
    "bis":         (13.5, 18.0), "tier1":      (11.0, 15.5), "cet1":     (10.0, 14.0),
    "npl":         (0.20, 0.95), "delinquency": (0.15, 0.70),
    "roa":         (0.35, 0.85), "roe":        (6.0, 11.5),  "nim":      (1.3, 2.1),
    "loan_dep":    (92.0, 102.0), "lcr":       (105.0, 145.0),
    "total_asset": (180.0, 520.0), "net_income": (2000.0, 30000.0),
}


def _mock_bank_indicators(bank_code: str, base_months: list[str]) -> dict:
    rnd = random.Random(hash(bank_code) & 0xFFFFFFFF)
    base = {k: round(rnd.uniform(*rng), 2) for k, rng in _MOCK_BASE_RANGES.items()}
    series = {k: [] for k in base}
    for k, v in base.items():
        cur = v * rnd.uniform(0.90, 1.04)
        for _ in base_months:
            cur = max(cur * rnd.uniform(0.97, 1.03), 0.01)
            series[k].append(round(cur, 2))
        series[k][-1] = v   # 마지막 분기는 정확히 base 값
    return {
        "latest": {k: s[-1] for k, s in series.items()},
        "series": series,
        "months": [fisis_client.quarter_label(m) for m in base_months],
        "base_months": list(base_months),
        "_source": "sample",
    }


# ─── FISIS 실데이터 (실패/코드미확정 시 mock 폴백) ────────────────────────────
def _get_bank_indicators(api_key: str, bank_code: str,
                         start_mm: str, end_mm: str) -> dict:
    """은행 하나의 (start_mm~end_mm) 분기 시계열. FISIS 우선, 실패 시 샘플."""
    try:
        keys = [i["key"] for i in INDICATORS]
        fetched = fisis_client.fetch_bank_indicators(bank_code, keys, start_mm, end_mm)
    except Exception as e:  # 방어적 — 어떤 경우에도 화면이 비지 않도록
        log.warning("FISIS 조회 예외 (%s): %s", bank_code, e)
        fetched = None
    if fetched:
        fetched.setdefault("_source", "fisis")
        return fetched
    base_months = fisis_client.recent_quarters(_quarters_between(start_mm, end_mm))
    return _mock_bank_indicators(bank_code, base_months)


def _quarters_between(start_mm: str, end_mm: str) -> int:
    """start_mm~end_mm(YYYYMM 분기말) 사이 분기 개수(포함)."""
    try:
        sy, sm = int(start_mm[:4]), int(start_mm[4:6])
        ey, em = int(end_mm[:4]), int(end_mm[4:6])
        n = (ey - sy) * 4 + ((em - 1) // 3 - (sm - 1) // 3) + 1
        return max(1, min(n, 40))
    except Exception:
        return 8


# ─── UI 헬퍼 ─────────────────────────────────────────────────────────────────
def _eval_status(ind: dict, value: float) -> tuple[str, str]:
    """지표 값이 정상/주의/위험 중 어디인지 판정. (status, color) 반환."""
    # 리터럴 hex 유지 — _indicator_card_html 이 "{color}1a" 로 알파값을 이어붙여
    # 배지 배경을 만들기 때문에 var(--x) 는 여기서 쓸 수 없다.
    if value is None:
        return ("자료없음", "#94a3b8")
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
    if v is None:
        return "N/A"
    if unit == "조원":
        return f"{v:,.1f} {unit}"
    if unit == "억원":
        return f"{v:,.0f} {unit}"
    return f"{v:,.2f}{unit}"


def _indicator_card_html(ind: dict, value: float, prev: float | None = None) -> str:
    status, color = _eval_status(ind, value)
    delta_html = ""
    if value is not None and prev is not None and prev != 0:
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
        for k, label in [('dive', 'DIVE 원본'), ('native', '은행별 주요 지표')]:
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
    """은행별 주요 지표 — FISIS OpenAPI 실데이터(코드 확정 시), 실패 시 샘플 폴백.

    · 기준시점(분기): 지표 카드가 그 시점 값을 표시
    · 조회 기간(시작~종료 분기): 시계열 추이 그래프 구간
    """
    api_key = os.environ.get("FSS_API_KEY", "").strip() or config.get("fss_api_key", "")

    q_opts = fisis_client.quarter_options(years_back=5)   # 최근 20개 분기(YYYYMM, 오름차순)
    _q_label = {mm: fisis_client.quarter_label(mm) for mm in q_opts}
    _def_end = q_opts[-1]
    _def_start = q_opts[-8] if len(q_opts) >= 8 else q_opts[0]

    state = {
        "selected_bank": BANKS[0]["code"],
        "start_mm": _def_start,
        "end_mm": _def_end,
        "ref_mm": _def_end,      # 기준시점(카드 스냅샷)
        "cache": {},             # bank_code -> data dict (현재 로드된 기간)
        "source": "",            # 'fisis' | 'sample'
        "loaded": False,
    }

    def _data_for(bank_code: str) -> dict:
        return state["cache"].get(bank_code) or {}

    def _ref_idx(d: dict) -> int:
        bm = d.get("base_months") or []
        if not bm:
            return 0
        try:
            return bm.index(state["ref_mm"])
        except ValueError:
            return len(bm) - 1

    # ── 헤더 ──────────────────────────────────────────────────────────────
    with ui.element('div').classes('page-head'):
        ui.html(
            '<div class="titles">'
            '<div class="page-title">은행별 주요 지표</div>'
            '<div class="page-subtitle">파인(FINE) 핵심경영지표 기반 — 자본·건전성·수익성·유동성을 분기 시계열로 확인합니다.</div>'
            '</div>'
        )

    src_label = ui.html('')   # 데이터 출처 배지 (조회 후 갱신)

    def _update_src_label():
        if state["source"] == "fisis":
            msg = '<span style="color:var(--success);">FISIS OpenAPI 실데이터</span>'
        else:
            key_note = '' if fisis_client.has_api_key() else ' · FSS_API_KEY 미설정'
            code_note = '' if fisis_client.codes_ready() else ' · 코드 매핑 확정 필요(scripts/fisis_discover.py)'
            state_note = '' if state["loaded"] else ' · [조회] 버튼을 눌러 불러오세요'
            msg = (f'<span style="color:var(--accent);">샘플 데이터</span>'
                   f'{key_note}{code_note}{state_note}')
        src_label.content = (
            f'<div style="font-size:11.5px;color:var(--text-4);margin:-6px 0 10px;">'
            f'데이터 출처: {msg}</div>'
        )

    _update_src_label()

    # ── 컨트롤 바: 조회 기간(시작~종료) + 기준시점 + 조회 ─────────────────
    _sel_props = 'outlined dense options-dense'
    with ui.element('div').style(
        'display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:14px;'
    ):
        ui.html('<span style="font-size:12px;color:var(--text-3);font-weight:600;">조회 기간</span>')
        start_sel = ui.select(options=dict(_q_label), value=state["start_mm"]).props(_sel_props).classes('w-32')
        ui.html('<span style="font-size:12px;color:var(--text-4);">~</span>')
        end_sel = ui.select(options=dict(_q_label), value=state["end_mm"]).props(_sel_props).classes('w-32')
        ui.html('<span style="font-size:12px;color:var(--text-3);font-weight:600;margin-left:6px;">기준시점</span>')
        ref_sel = ui.select(options=dict(_q_label), value=state["ref_mm"]).props(_sel_props).classes('w-32')
        load_btn = ui.button('조회').classes('btn-primary-mono')
        load_spin = ui.html('')

    def _sync_ref_options():
        """기준시점 옵션을 현재 로드된 분기(또는 [시작,종료] 범위)로 제한·정렬."""
        d0 = _data_for(state["selected_bank"])
        bm = d0.get("base_months") or [
            mm for mm in q_opts if state["start_mm"] <= mm <= state["end_mm"]
        ]
        ref_sel.set_options({mm: _q_label.get(mm, fisis_client.quarter_label(mm)) for mm in bm})
        if state["ref_mm"] not in bm:
            state["ref_mm"] = bm[-1] if bm else state["end_mm"]
        ref_sel.value = state["ref_mm"]

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
            series = d.get("series")
            months = d.get("months") or []
            cards_grid.clear()
            chart_section.clear()
            if not series or not months:
                with cards_grid:
                    ui.html(
                        '<div style="grid-column:1/-1;text-align:center;color:var(--text-4);'
                        'font-size:12.5px;padding:24px 0;">조회 기간을 선택하고 [조회] 버튼을 눌러주세요.</div>'
                    )
                return

            idx = _ref_idx(d)
            # 카드 — 기준시점 값 (직전 분기 대비 증감)
            with cards_grid:
                for ind in INDICATORS:
                    vals = series.get(ind["key"]) or []
                    cur = vals[idx] if idx < len(vals) else None
                    prev = vals[idx - 1] if idx >= 1 and idx - 1 < len(vals) else None
                    ui.html(_indicator_card_html(ind, cur, prev))

            # 시계열 차트 — 선택 기간 전체 추이
            with chart_section:
                for title, keys in CHART_GROUPS:
                    ui.html(_svg_line_chart(title, keys, series, months))

        def _on_bank_change(e):
            state["selected_bank"] = e.args if isinstance(e.args, str) else bank_select.value
            _render_detail()

        bank_select.on('update:model-value', _on_bank_change)

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
            rows = []
            has_any = False
            for b in BANKS:
                d = _data_for(b["code"])
                vals = (d.get("series") or {}).get(sel) or []
                idx = _ref_idx(d)
                v = vals[idx] if idx < len(vals) else None
                if v is not None:
                    has_any = True
                rows.append((b["name"], v))

            if not has_any:
                compare_chart.content = (
                    '<div style="text-align:center;color:var(--text-4);font-size:12.5px;'
                    'padding:24px 0;">조회 기간을 선택하고 [조회] 버튼을 눌러주세요.</div>'
                )
                compare_table.content = ''
                return

            # 정렬 (좋은 방향 우선) — 결측(None)은 뒤로
            reverse = (ind["good"] != "down")
            rows.sort(key=lambda r: (r[1] is None, -(r[1] or 0) if reverse else (r[1] or 0)))

            # 막대그래프 (가로형)
            max_v = max((r[1] for r in rows if r[1] is not None), default=0) or 1
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
                pct = (v / max_v * 100) if v is not None else 0
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
                idx_b = _ref_idx(d)
                for i in INDICATORS:
                    vals = (d.get("series") or {}).get(i["key"]) or []
                    v = vals[idx_b] if idx_b < len(vals) else None
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

    # ── 컨트롤 핸들러 ─────────────────────────────────────────────────────
    def _on_start(_e):
        state["start_mm"] = start_sel.value
    start_sel.on('update:model-value', _on_start)

    def _on_end(_e):
        state["end_mm"] = end_sel.value
    end_sel.on('update:model-value', _on_end)

    def _on_ref(_e):
        state["ref_mm"] = ref_sel.value
        _render_detail()
        _render_compare()
    ref_sel.on('update:model-value', _on_ref)

    async def _load_all():
        s, e = state["start_mm"], state["end_mm"]
        if s > e:
            s, e = e, s
        state["start_mm"], state["end_mm"] = s, e
        start_sel.value, end_sel.value = s, e
        load_btn.props(add='disable')
        load_spin.content = '<span style="color:var(--text-4);font-size:12px;">조회 중…</span>'
        try:
            def _fetch_all():
                return {b["code"]: _get_bank_indicators(api_key, b["code"], s, e) for b in BANKS}
            cache = await nicegui_run.io_bound(_fetch_all)
            state["cache"] = cache
            state["loaded"] = True
            srcs = {(d or {}).get("_source") for d in cache.values()}
            state["source"] = "fisis" if "fisis" in srcs else "sample"
            _sync_ref_options()
            _update_src_label()
            _render_detail()
            _render_compare()
            ui.notify('지표 조회 완료', type='positive', position='top')
        except Exception as ex:
            log.error("지표 조회 오류: %s", ex)
            ui.notify(f'조회 오류: {ex}', type='negative', position='top')
        finally:
            load_btn.props(remove='disable')
            load_spin.content = ''

    load_btn.on_click(_load_all)

    # 초기 탭 (Detail) 활성화 — 데이터는 [조회] 시 로드
    _switch_tab('detail')
    _render_detail()
    _render_compare()


# ─── 인라인 SVG 라인차트 ─────────────────────────────────────────────────────
# 외부 차트 라이브러리 없이 시계열을 그리는 경량 SVG 생성기.
def _svg_line_chart(title: str, keys: list[str], series: dict, quarters: list[str]) -> str:
    W, H = 360, 200
    PAD_L, PAD_R, PAD_T, PAD_B = 36, 16, 28, 28
    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B

    colors = ["#f1f5f9", "#0ea5e9", "#a78bfa", "#22c55e", "#ef4444"]

    # 전체 데이터 범위 (결측 None 제외)
    all_vals = []
    for k in keys:
        all_vals.extend(v for v in series.get(k, []) if v is not None)
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
        vals = series.get(k, [])
        # 결측(None)은 선을 끊는다 — 연속 구간별 polyline
        seg: list[str] = []
        segments: list[list[str]] = []
        for i, v in enumerate(vals):
            if v is None:
                if seg:
                    segments.append(seg); seg = []
                continue
            seg.append(f"{_x(i):.1f},{_y(v):.1f}")
        if seg:
            segments.append(seg)
        for pts in segments:
            lines.append(
                f'<polyline points="{" ".join(pts)}" fill="none" '
                f'stroke="{col}" stroke-width="1.8" />'
            )
        # 마지막 유효 점 강조
        last_i = next((i for i in range(len(vals) - 1, -1, -1) if vals[i] is not None), None)
        if last_i is not None:
            lines.append(
                f'<circle cx="{_x(last_i):.1f}" cy="{_y(vals[last_i]):.1f}" r="3" fill="{col}" />'
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
