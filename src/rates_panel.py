"""
금리 정보 패널 — 금융투자협회 채권정보센터(kofiabond.or.kr) 기반.

표시:
  - CD 91일 금리 (강조 카드)
  - 채권시가평가수익률 매트릭스 (행: 국고채권 1/2/3/5년, 열: 5개 평가사)

갱신:
  - 패널 열람 시 오늘자 데이터가 없으면 자동 조회(on-show 훅).
  - 상단 '갱신' 버튼으로 수동 재조회.

데이터/저장은 rates_scraper 모듈이 담당한다.
"""
import html as _html
import asyncio

from nicegui import ui, run as nicegui_run

from logger import get_logger
import rates_scraper

log = get_logger("rates_panel")


def _fmt_rate(v) -> str:
    """수익률(%) 표시. None/비수치는 '-'."""
    if v is None:
        return "-"
    try:
        return f"{float(v):.3f}"
    except (TypeError, ValueError):
        return _html.escape(str(v))


def build_rates_panel(config: dict, app_state: "dict | None" = None):
    """금리 정보 패널을 현재 NiceGUI 컨텍스트에 렌더링합니다.

    app_state 가 주어지면 on-show 훅(_tab_show_hooks['rates'])을 등록하여
    패널 열람 시 오늘자 데이터가 없을 때 자동 조회한다.
    """
    pstate = {"loading": False}

    # ── 헤더 ─────────────────────────────────────────────────────────────
    with ui.element('div').classes('page-head'):
        ui.html(
            '<div class="titles">'
            '<div class="page-title">금리 모니터</div>'
            '<div class="page-subtitle">'
            '금융투자협회 채권정보센터 — CD 91일 금리와 채권시가평가수익률(국고채권)을 '
            '한 화면에서 확인합니다.'
            '</div>'
            '</div>'
        )

    # ── 컨트롤 바 ────────────────────────────────────────────────────────
    with ui.element('div').style(
        'display:flex;align-items:center;gap:12px;padding:12px 32px;'
        'border-bottom:1px solid var(--border);flex-shrink:0;'
    ):
        refresh_btn = ui.button('갱신').classes('btn-primary-mono')
        last_updated_label = ui.html(
            '<span style="color:var(--text-4);font-size:12px;"></span>'
        )

    progress_bar = ui.linear_progress().props('indeterminate').classes('w-full')
    progress_bar.style('margin:0 32px;')
    progress_bar.visible = False

    # ── 본문 컨테이너 ────────────────────────────────────────────────────
    content = ui.element('div').style(
        'padding:20px 32px;flex:1;overflow-y:auto;'
    )

    # ── 렌더링 ───────────────────────────────────────────────────────────
    def _render_empty(message: str, tone: str = "info"):
        color = {
            "info": "var(--text-4)",
            "warning": "var(--warning)",
            "danger": "var(--danger)",
        }.get(tone, "var(--text-4)")
        content.clear()
        with content:
            ui.html(
                f'<div style="text-align:center;color:{color};font-size:13px;'
                f'padding:48px 0;line-height:1.7;">{message}</div>'
            )

    def _render_cd91(cd: "dict | None"):
        if not cd:
            return (
                '<div style="background:var(--bg);border:1px solid var(--border);'
                'border-radius:12px;padding:18px 20px;min-width:220px;">'
                '<div style="font-size:12px;color:var(--text-3);font-weight:600;'
                'margin-bottom:6px;">CD 91일</div>'
                '<div style="font-size:13px;color:var(--text-4);">데이터 없음</div>'
                '</div>'
            )
        rate = _fmt_rate(cd.get("rate"))
        date = _html.escape(str(cd.get("date") or ""))
        return (
            '<div style="background:var(--bg);border:1px solid var(--border);'
            'border-radius:12px;padding:18px 20px;min-width:220px;">'
            '<div style="font-size:12px;color:var(--text-3);font-weight:600;'
            'margin-bottom:6px;">CD 91일 금리</div>'
            f'<div style="font-size:30px;font-weight:700;color:var(--text);'
            f'font-variant-numeric:tabular-nums;line-height:1.1;">{rate}'
            '<span style="font-size:16px;font-weight:500;color:var(--text-3);'
            'margin-left:3px;">%</span></div>'
            f'<div style="font-size:11px;color:var(--text-4);margin-top:6px;">'
            f'기준일 {date}</div>'
            '</div>'
        )

    def _render_valuation(mv: "dict | None") -> str:
        if not mv or not mv.get("bonds"):
            return (
                '<div style="border:1px solid var(--border);border-radius:12px;'
                'padding:24px;color:var(--text-4);font-size:13px;text-align:center;">'
                '채권시가평가수익률 데이터 없음</div>'
            )
        companies = mv.get("companies") or []
        bonds = mv.get("bonds") or {}
        date = _html.escape(str(mv.get("date") or ""))

        th_bond = (
            '<th style="text-align:left;padding:9px 12px;font-size:11px;'
            'color:var(--text-3);font-weight:600;border-bottom:1px solid var(--border);'
            'position:sticky;top:0;background:var(--bg);">채권종목</th>'
        )
        th_companies = ''.join(
            '<th style="text-align:right;padding:9px 12px;font-size:11px;'
            'color:var(--text-3);font-weight:600;border-bottom:1px solid var(--border);'
            'position:sticky;top:0;background:var(--bg);white-space:nowrap;">'
            f'{_html.escape(str(c))}</th>'
            for c in companies
        )
        thead = f'<tr>{th_bond}{th_companies}</tr>'

        # 행 순서: BOND_LABELS 우선, 그 외 응답에 있는 나머지 종목 이어붙임
        ordered_labels = [b for b in rates_scraper.BOND_LABELS if b in bonds]
        ordered_labels += [b for b in bonds if b not in ordered_labels]

        rows = []
        for label in ordered_labels:
            row_data = bonds.get(label, {})
            cells = [
                '<td style="text-align:left;padding:9px 12px;font-size:12.5px;'
                'color:var(--text);border-bottom:1px solid var(--border);'
                f'white-space:nowrap;">{_html.escape(str(label))}</td>'
            ]
            for c in companies:
                cells.append(
                    '<td style="text-align:right;padding:9px 12px;font-size:12.5px;'
                    'color:var(--text);border-bottom:1px solid var(--border);'
                    'font-variant-numeric:tabular-nums;">'
                    f'{_fmt_rate(row_data.get(c))}</td>'
                )
            rows.append('<tr>' + ''.join(cells) + '</tr>')

        caption = (
            '<div style="display:flex;align-items:baseline;justify-content:space-between;'
            'margin-bottom:10px;">'
            '<div style="font-size:14px;font-weight:600;color:var(--text);">'
            '채권시가평가수익률 (단위: %)</div>'
            f'<div style="font-size:11.5px;color:var(--text-4);">기준일 {date}</div>'
            '</div>'
        )
        table = (
            '<div style="border:1px solid var(--border);border-radius:var(--radius);'
            'overflow:auto;max-height:520px;background:var(--bg);">'
            '<table style="width:100%;border-collapse:collapse;">'
            f'<thead>{thead}</thead><tbody>{"".join(rows)}</tbody></table></div>'
        )
        return caption + table

    def _render_data(data: dict):
        content.clear()
        with content:
            # 상단: CD91 카드 + 조회 시각
            fetched = _html.escape(str(data.get("fetched_at") or ""))
            ui.html(
                '<div style="display:flex;gap:16px;flex-wrap:wrap;'
                'align-items:stretch;margin-bottom:22px;">'
                + _render_cd91(data.get("cd_91")) +
                '</div>'
            )
            # 시가평가 매트릭스
            ui.html(_render_valuation(data.get("market_valuation")))
            if fetched:
                ui.html(
                    f'<div style="font-size:11px;color:var(--text-4);margin-top:14px;">'
                    f'최종 조회: {fetched}</div>'
                )

    def _show(data: "dict | None"):
        """캐시/조회 결과를 화면에 반영."""
        if data and (data.get("cd_91") or data.get("market_valuation")):
            _render_data(data)
            stale = rates_scraper.is_stale(data)
            note = ' · <span style="color:var(--warning);">갱신 필요</span>' if stale else ''
            last_updated_label.content = (
                f'<span style="color:var(--text-4);font-size:12px;">'
                f'기준일 {_html.escape(str(data.get("date") or ""))}{note}</span>'
            )
        else:
            _render_empty(
                "표시할 금리 데이터가 없습니다.<br>상단 <b>갱신</b> 버튼을 눌러 조회하세요."
            )

    # ── 조회 핸들러 ──────────────────────────────────────────────────────
    async def _do_refresh(force: bool):
        if pstate["loading"]:
            return
        pstate["loading"] = True
        # on-show 훅에서 asyncio.create_task 로 호출되면 slot/client 컨텍스트가
        # 없어 ui.notify 등이 실패한다. content 컨테이너 슬롯을 명시적으로 진입해
        # 배경 task 에서도 UI 갱신이 가능하도록 한다.
        with content:
            progress_bar.visible = True
            refresh_btn.props(add='disable')
            last_updated_label.content = (
                '<span style="color:var(--text-4);font-size:12px;">조회 중…</span>'
            )
            try:
                data = await nicegui_run.io_bound(rates_scraper.get_rates, force)
                _show(data)
                ui.notify('금리 정보 갱신 완료', type='positive', position='top')
            except rates_scraper.RatesNotConfiguredError as e:
                # 실제 요청이 아직 연결되지 않은 상태 — 경고로 안내(오류 아님)
                log.warning("금리 조회 미설정: %s", e)
                _render_empty(
                    "금리 조회 요청이 아직 설정되지 않았습니다.<br>"
                    "kofiabond 네트워크 요청 캡처 연결 후 조회가 가능합니다.",
                    tone="warning",
                )
                last_updated_label.content = (
                    '<span style="color:var(--warning);font-size:12px;">설정 대기</span>'
                )
            except Exception as e:
                log.error("금리 조회 오류: %s", e)
                ui.notify(f'조회 오류: {e}', type='negative', position='top')
                # 조회 실패해도 기존 캐시가 있으면 유지 표시
                cached = rates_scraper.load_rates()
                if cached:
                    _show(cached)
                last_updated_label.content = (
                    '<span style="color:var(--danger);font-size:12px;">조회 실패</span>'
                )
            finally:
                progress_bar.visible = False
                refresh_btn.props(remove='disable')
                pstate["loading"] = False

    refresh_btn.on_click(lambda: asyncio.create_task(_do_refresh(force=True)))

    # ── 초기 표시: 캐시가 있으면 즉시 렌더 ───────────────────────────────
    _show(rates_scraper.load_rates())

    # ── 열람 시 자동 조회(on-show 훅) ────────────────────────────────────
    def _on_show():
        """패널이 열릴 때 호출 — 오늘자 데이터가 없으면 자동 조회."""
        cached = rates_scraper.load_rates()
        if rates_scraper.is_stale(cached) and not pstate["loading"]:
            asyncio.create_task(_do_refresh(force=False))

    if app_state is not None:
        app_state.setdefault('_tab_show_hooks', {})['rates'] = _on_show
