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
import calendar
import datetime
import json as _json
import re as _re

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

    # 콜금리(Call rate)는 사용자 메일에서 읽어온다 — 서버 배포 구조이므로
    # 사용자 PC의 로컬 Outlook 브릿지(outlook_bridge.exe)를 브라우저가 호출한다.
    bridge_url = (config.get('outlook_bridge_url') or 'http://127.0.0.1:8899').rstrip('/')
    bridge_token = config.get('outlook_bridge_token', '') or ''

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
    _today = rates_scraper._now_kst().date()
    _years = list(range(_today.year - 3, _today.year + 1))
    with ui.element('div').style(
        'display:flex;align-items:center;gap:12px;padding:12px 32px;'
        'border-bottom:1px solid var(--border);flex-shrink:0;flex-wrap:wrap;'
    ):
        # 조회일 선택 — 자유 텍스트 입력을 없애 오입력을 차단(연/월/일 드롭다운)
        ui.html(
            '<span style="font-size:12px;color:var(--text-2);font-weight:500;">'
            '조회일</span>'
        )
        with ui.row().classes('items-center gap-1 no-wrap'):
            year_sel = ui.select(options=_years, value=_today.year).props(
                'outlined dense options-dense'
            ).style('width:96px;')
            ui.html('<span style="color:var(--text-4);">년</span>')
            month_sel = ui.select(options=list(range(1, 13)), value=_today.month).props(
                'outlined dense options-dense'
            ).style('width:72px;')
            ui.html('<span style="color:var(--text-4);">월</span>')
            day_sel = ui.select(
                options=list(range(1, 32)), value=_today.day
            ).props('outlined dense options-dense').style('width:72px;')
            ui.html('<span style="color:var(--text-4);">일</span>')
        refresh_btn = ui.button('조회').classes('btn-primary-mono')
        last_updated_label = ui.html(
            '<span style="color:var(--text-4);font-size:12px;"></span>'
        )

    def _days_in_month() -> int:
        try:
            return calendar.monthrange(int(year_sel.value), int(month_sel.value))[1]
        except (TypeError, ValueError):
            return 31

    def _sync_day_options(_e=None):
        """선택된 연/월에 맞춰 '일' 옵션을 해당 월의 마지막 날까지로 조정."""
        dim = _days_in_month()
        day_sel.set_options(list(range(1, dim + 1)))
        if day_sel.value and int(day_sel.value) > dim:
            day_sel.value = dim

    def _selected_ymd() -> str:
        y, m, d = year_sel.value, month_sel.value, day_sel.value
        if None in (y, m, d):
            return rates_scraper._yyyymmdd(rates_scraper.today_str())
        return f'{int(y):04d}{int(m):02d}{int(d):02d}'

    year_sel.on('update:model-value', _sync_day_options)
    month_sel.on('update:model-value', _sync_day_options)
    _sync_day_options()

    progress_bar = ui.linear_progress().props('indeterminate').classes('w-full')
    progress_bar.style('margin:0 32px;')
    progress_bar.visible = False

    # ── 본문 컨테이너 ────────────────────────────────────────────────────
    content = ui.element('div').style(
        'padding:20px 32px 0;flex:1;overflow-y:auto;'
    )
    # 콜금리(메일) 전용 슬롯 — content 를 갱신해도 유지되도록 별도 컨테이너.
    call_rate_slot = ui.element('div').style('padding:4px 32px 24px;')

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

    def _render_valuation(mv: "dict | None", err: "str | None" = None) -> str:
        if not mv or not mv.get("rows"):
            body = (
                '채권시가평가수익률 데이터 없음'
                if not err else
                '채권시가평가수익률을 불러오지 못했습니다.<br>'
                '<span style="color:var(--text-4);font-size:11.5px;">'
                f'{_html.escape(str(err))}</span>'
            )
            tone = 'var(--warning)' if err else 'var(--text-4)'
            return (
                '<div style="border:1px solid var(--border);border-radius:12px;'
                f'padding:24px;color:{tone};font-size:13px;text-align:center;'
                'line-height:1.7;">'
                f'{body}</div>'
            )
        tenors = mv.get("tenors") or []
        rows_data = mv.get("rows") or {}
        date = _html.escape(str(mv.get("date") or ""))
        source = _html.escape(str(mv.get("source") or ""))

        th_bond = (
            '<th style="text-align:left;padding:9px 12px;font-size:11px;'
            'color:var(--text-3);font-weight:600;border-bottom:1px solid var(--border);'
            'position:sticky;top:0;background:var(--bg);">채권종목</th>'
        )
        th_tenors = ''.join(
            '<th style="text-align:right;padding:9px 12px;font-size:11px;'
            'color:var(--text-3);font-weight:600;border-bottom:1px solid var(--border);'
            'position:sticky;top:0;background:var(--bg);white-space:nowrap;">'
            f'{_html.escape(str(t))}</th>'
            for t in tenors
        )
        thead = f'<tr>{th_bond}{th_tenors}</tr>'

        rows = []
        for bond_name, tenor_rates in rows_data.items():
            cells = [
                '<td style="text-align:left;padding:9px 12px;font-size:12.5px;'
                'color:var(--text);border-bottom:1px solid var(--border);'
                f'white-space:nowrap;">{_html.escape(str(bond_name))}</td>'
            ]
            for t in tenors:
                cells.append(
                    '<td style="text-align:right;padding:9px 12px;font-size:12.5px;'
                    'color:var(--text);border-bottom:1px solid var(--border);'
                    'font-variant-numeric:tabular-nums;">'
                    f'{_fmt_rate(tenor_rates.get(t))}</td>'
                )
            rows.append('<tr>' + ''.join(cells) + '</tr>')

        src_note = f' · {source}' if source else ''
        caption = (
            '<div style="display:flex;align-items:baseline;justify-content:space-between;'
            'margin-bottom:10px;">'
            '<div style="font-size:14px;font-weight:600;color:var(--text);">'
            '채권시가평가수익률 (잔존만기별, 단위: %)</div>'
            f'<div style="font-size:11.5px;color:var(--text-4);">'
            f'기준일 {date}{src_note}</div>'
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
            # 시가평가 매트릭스 (실패 시 원인/진단 노출)
            ui.html(_render_valuation(
                data.get("market_valuation"),
                data.get("market_valuation_error"),
            ))
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

    # ── 콜금리(Call rate) — 사용자 메일에서 조회 ─────────────────────────
    _CALL_RE = _re.compile(r'(\d{1,2}\.\d{2,4})')

    async def _bridge_get(path: str, params: dict, timeout: float = 30):
        """브라우저(사용자 PC)에서 127.0.0.1 브릿지로 GET. dict 반환."""
        q = dict(params)
        if bridge_token:
            q['token'] = bridge_token
        js = (
            "try {"
            f"  const base = {_json.dumps(bridge_url)};"
            f"  const params = new URLSearchParams({_json.dumps({k: str(v) for k, v in q.items()})});"
            f"  const r = await fetch(base + {_json.dumps(path)} + '?' + params.toString());"
            "  if (!r.ok) return {error: 'HTTP ' + r.status};"
            "  return await r.json();"
            "} catch (e) { return {error: '브릿지 연결 실패: ' + String(e)}; }"
        )
        res = await ui.run_javascript(js, timeout=timeout)
        return res if isinstance(res, dict) else {'error': '브릿지 응답 없음'}

    def _parse_call_rate(subject: str):
        m = _CALL_RE.search(subject or '')
        return m.group(1) if m else None

    async def _open_call_mail(entry_id: str, store_id: str):
        res = await _bridge_get('/open-email', {'entry_id': entry_id, 'store_id': store_id})
        if res.get('ok'):
            ui.notify('메일을 열었습니다.', type='positive', position='top')
        else:
            ui.notify(f"메일 열기 실패: {res.get('error', '브릿지 확인')}",
                      type='negative', position='top')

    def _render_call_rate(items: list, err: "str | None" = None):
        call_rate_slot.clear()
        with call_rate_slot:
            ui.html(
                '<div style="font-size:12px;color:var(--text-3);font-weight:600;'
                'margin:6px 0 8px;">콜금리 (Call rate) · 메일에서 조회</div>'
            )
            if err:
                ui.html(
                    '<div style="font-size:12px;color:var(--text-4);">'
                    'Outlook 브릿지 미연결 — 사용자 PC에서 <b>outlook_bridge.exe</b> 실행 필요 '
                    f'<span style="color:var(--text-4);">({_html.escape(str(err))})</span></div>'
                )
                return
            if not items:
                ui.html(
                    '<div style="font-size:12px;color:var(--text-4);">'
                    '선택한 날짜에 제목에 "Call rate"가 포함된 메일이 없습니다.</div>'
                )
                return
            for it in items:
                rate = _parse_call_rate(it.get('subject'))
                subj = _html.escape(it.get('subject') or '')
                date = _html.escape(str(it.get('date') or ''))
                with ui.element('div').style(
                    'background:var(--bg);border:1px solid var(--border);border-radius:12px;'
                    'padding:16px 20px;margin-bottom:10px;display:flex;align-items:center;'
                    'gap:20px;flex-wrap:wrap;'
                ):
                    ui.html(
                        '<div><div style="font-size:12px;color:var(--text-3);font-weight:600;'
                        'margin-bottom:4px;">Call rate</div>'
                        '<div style="font-size:28px;font-weight:700;color:var(--text);'
                        'font-variant-numeric:tabular-nums;line-height:1.1;">'
                        f'{rate or "—"}'
                        + ('<span style="font-size:15px;font-weight:500;color:var(--text-3);'
                           'margin-left:3px;">%</span>' if rate else '')
                        + '</div></div>'
                        f'<div style="flex:1;min-width:220px;font-size:12px;color:var(--text-3);'
                        f'line-height:1.5;">{subj}'
                        f'<div style="font-size:11px;color:var(--text-4);margin-top:3px;">{date}</div>'
                        '</div>'
                    )
                    ob = ui.button('메일 열기').props('outline dense no-caps')
                    ob.on_click(
                        lambda _e=None, eid=it.get('entry_id', ''), sid=it.get('store_id', ''):
                        _open_call_mail(eid, sid)
                    )

    async def _load_call_rate(ymd: str):
        try:
            d = f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}'
            res = await _bridge_get('/emails', {'start': d, 'end': d, 'attachments': '0'})
            if res.get('error'):
                _render_call_rate([], err=res['error'])
                return
            emails = res.get('emails') or []
            matches = [e for e in emails if 'call rate' in (e.get('subject') or '').lower()]
            _render_call_rate(matches)
        except Exception as ce:
            log.warning('콜금리 조회 오류: %s', ce)
            _render_call_rate([], err=str(ce))

    # ── 조회 핸들러 ──────────────────────────────────────────────────────
    async def _do_refresh(force: bool):
        if pstate["loading"]:
            return
        pstate["loading"] = True
        ymd = _selected_ymd()
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
                data = await nicegui_run.io_bound(
                    rates_scraper.get_rates, force, ymd
                )
                _show(data)
                ui.notify('금리 정보 조회 완료', type='positive', position='top')
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
            # 콜금리는 kofiabond 성공/실패와 무관하게 선택 날짜 메일에서 조회
            await _load_call_rate(ymd)

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
