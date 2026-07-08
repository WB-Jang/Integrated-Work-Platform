"""
보고서 작성 패널 UI — 모노크롬 디자인 시스템 이식판

3-column 레이아웃: 좌측 보고서 목록 · 중앙 실행 로그 · 우측 입력/채팅.
"""
import os
import json
import asyncio
import datetime
import html as _html
from pathlib import Path

from nicegui import ui, events, run as nicegui_run

from reporting_runner import REPORT_CONFIGS, run_report, get_upload_dir, analyze_fx5260_var_accounts
import activity_log
from ui_styles import req_checklist_html, step_list_html

_FX5260_STEPS = ['변동금리 분석', '금리 입력', '금리 적용', '실행']


def build_reporting_panel(config: dict):
    """보고서 작성 패널을 현재 NiceGUI 컨텍스트에 추가합니다.

    호출하는 쪽에서 ``.panel`` 컨테이너 안에 배치해 주세요 (page-head 포함).
    """

    state = {
        "selected": None,
        "upload_dir": None,
        "uploaded_files": {},
        "params": {},
        "output_files": [],
        "running": False,
        "chat_messages": [],
    }

    # ── 헤더 ─────────────────────────────────────────────────────────────
    with ui.element('div').classes('page-head'):
        ui.html(
            '<div class="titles">'
            '<div class="page-title">보고서 작성</div>'
            '<div class="page-subtitle">파일을 업로드하고 보고서를 자동으로 작성합니다.</div>'
            '</div>'
        )

    # ── 본문: 3분할 (보고서 목록 / 로그 / 입력) ──────────────────────────
    with ui.element('div').classes('tri-col-row'):

        # ── 좌측: 보고서 목록 ────────────────────────────────────────────
        with ui.element('div'):
            ui.html('<div class="muted-label">REPORTS</div>')
            report_btns = {}
            for key, cfg in REPORT_CONFIGS.items():
                btn = ui.element('div').classes('list-item')
                with btn:
                    ui.html(f'<span>{_html.escape(cfg["name"])}</span>')
                report_btns[key] = btn

        # ── 중앙: 실행 로그 ──────────────────────────────────────────────
        with ui.element('div').style('display:flex; flex-direction:column;'):
            ui.html(
                '<div class="section-card-title">'
                '<span class="material-symbols-outlined">terminal</span>실행 로그'
                '</div>'
            )
            status_badge_el = ui.html(
                '<span class="badge-idle">준비</span>'
            )

            def _set_status_badge(kind: str, label: str) -> None:
                status_badge_el.content = f'<span class="badge-{kind}">{_html.escape(label)}</span>'
            progress_bar = ui.linear_progress(value=0).props('indeterminate').classes('w-full mt-2')
            progress_bar.visible = False
            log_toggle_btn = ui.button('자세히 보기 (원시 로그)').props('flat dense no-caps').classes('mt-2').style(
                'align-self:flex-start;font-size:11.5px;color:var(--text-3);padding:2px 4px;'
            )
            log_el = ui.html(
                '<div class="log-area">'
                '<span style="color:#737373;">보고서를 선택하고 실행하세요.</span>'
                '</div>'
            )
            log_el.visible = False
            download_area = ui.column().classes('w-full mt-3')

            def _toggle_log():
                log_el.visible = not log_el.visible
                log_toggle_btn.text = (
                    '숨기기 (원시 로그)' if log_el.visible else '자세히 보기 (원시 로그)'
                )
            log_toggle_btn.on_click(_toggle_log)

        # ── 우측: 입력/채팅 ──────────────────────────────────────────────
        with ui.element('div').style('display:flex; flex-direction:column;'):
            ui.html(
                '<div class="section-card-title">'
                '<span class="material-symbols-outlined">edit_note</span>입력 / 채팅'
                '</div>'
            )

            hint_label = ui.html(
                '<div class="muted-text" style="padding:10px 12px;background:var(--bg-elev);'
                'border:1px solid var(--border);border-radius:var(--radius);margin-bottom:12px;">'
                '왼쪽에서 보고서를 선택하세요.</div>'
            )

            # 단순 보고서용 진행 요약 바 — FX5260 등 다단계(wizard) 보고서는
            # 자체 스텝퍼가 이미 진행 상태를 보여주므로 여기서는 표시하지 않는다.
            progress_summary_el = ui.html('')

            upload_area = ui.column().classes('w-full')
            param_area = ui.column().classes('w-full mt-2')
            fx5260_area = ui.column().classes('w-full mt-2')   # FX5260 변동금리 분석 전용 영역

            checklist_area = ui.html('')

            run_btn = ui.button('실행').classes('btn-primary-mono w-full mt-3')
            run_btn.visible = False

            ui.html(
                '<div class="muted-label" style="margin-top:16px;">메모 (저장되지 않음 — 세션 내 참고용)</div>'
            )
            chat_container = ui.column().classes('w-full').style(
                'background:var(--bg-elev);border:1px solid var(--border);'
                'border-radius:var(--radius);height:160px;overflow-y:auto;'
                'padding:8px;display:flex;flex-direction:column;gap:6px;'
            )
            with ui.row().classes('w-full gap-2 mt-2 no-wrap'):
                chat_input = ui.input(placeholder='메모 입력 (저장되지 않음)...').props('outlined dense').classes('flex-1')
                send_btn = ui.button('전송').classes('btn-primary-mono')

    # ─── 이벤트 / 헬퍼 ───────────────────────────────────────────────────

    param_inputs: dict = {}
    upload_widgets: dict = {}

    class _YymmValue:
        """연/월 select 두 개를 하나의 문자열 값으로 노출하는 어댑터.
        기존 코드는 param_inputs[key].value 로 문자열을 읽으므로, ui.input 과
        동일한 인터페이스(.value)만 맞추면 execute_report 등을 그대로 재사용할 수 있다."""

        def __init__(self, year_select, month_select, fmt: str):
            self._y = year_select
            self._m = month_select
            self._fmt = fmt

        @property
        def value(self) -> str:
            y, m = self._y.value, self._m.value
            if y is None or m is None:
                return ''
            if self._fmt == 'YYMM':
                return f'{y % 100:02d}{m:02d}'
            if self._fmt == 'YYYY-MM':
                return f'{y:04d}-{m:02d}'
            return f'{y:04d}{m:02d}'  # YYYYMM

        def restore(self, raw: str) -> None:
            raw = (raw or '').strip()
            if not raw:
                return
            try:
                if self._fmt == 'YYYY-MM':
                    y_s, m_s = raw.split('-')
                    y, m = int(y_s), int(m_s)
                elif self._fmt == 'YYMM':
                    y, m = int(raw[:2]) + 2000, int(raw[2:4])
                else:
                    y, m = int(raw[:4]), int(raw[4:6])
            except (ValueError, IndexError):
                return
            self._y.value = y
            self._m.value = m

    def _build_yymm_picker(label: str, fmt: str):
        """연-월 파라미터용 선택창. 자유 텍스트 입력을 없애 오입력 자체를 차단한다."""
        today = datetime.date.today()
        years = list(range(today.year - 3, today.year + 1))
        ui.html(
            f'<div style="font-size:12px;color:var(--text-2);font-weight:500;'
            f'margin-top:10px;">{_html.escape(label)}</div>'
        )
        with ui.row().classes('items-center gap-2 mt-1 no-wrap'):
            year_sel = ui.select(options=years, value=today.year).props(
                'outlined dense options-dense'
            ).style('width:96px;')
            ui.html('<span style="color:var(--text-4);">-</span>')
            month_sel = ui.select(options=list(range(1, 13)), value=today.month).props(
                'outlined dense options-dense'
            ).style('width:74px;')
        adapter = _YymmValue(year_sel, month_sel, fmt)
        year_sel.on('update:model-value', lambda _e: _refresh_checklist())
        month_sel.on('update:model-value', lambda _e: _refresh_checklist())
        return adapter

    def add_chat_message(role: str, content: str):
        state['chat_messages'].append({'role': role, 'content': content})
        safe = _html.escape(content).replace('\n', '<br>')
        if role == 'user':
            bubble = (
                f'<div style="align-self:flex-end;max-width:85%;'
                f'background:var(--accent);color:#fff;border-radius:'
                f'{6 if True else 0}px 6px 2px 6px;padding:7px 11px;font-size:12.5px;'
                f'line-height:1.55;">{safe}</div>'
            )
        else:
            bubble = (
                f'<div style="align-self:flex-start;max-width:90%;'
                f'background:var(--bg);color:var(--text-2);border:1px solid var(--border);'
                f'border-radius:6px 6px 6px 2px;padding:7px 11px;font-size:12.5px;'
                f'line-height:1.55;">{safe}</div>'
            )
        with chat_container:
            ui.html(bubble)

    def send_chat():
        msg = (chat_input.value or '').strip()
        if not msg:
            return
        chat_input.value = ''
        add_chat_message('user', msg)

    send_btn.on_click(send_chat)
    chat_input.on('keydown.enter', lambda _e=None: send_chat())

    def update_log(text: str):
        escaped = _html.escape(text).replace('\n', '<br>')
        log_el.content = f'<div class="log-area">{escaped}</div>'

    def refresh_upload_area(report_key: str):
        cfg = REPORT_CONFIGS[report_key]
        upload_area.clear()
        upload_widgets.clear()
        state['uploaded_files'].clear()

        with upload_area:
            for f_def in cfg['files']:
                fkey = f_def['key']
                hint = f_def.get('hint', '')
                ui.html(
                    f'<div style="font-size:12px;font-weight:600;color:var(--text-2);'
                    f'margin-top:10px;">'
                    f'{_html.escape(f_def["label"])} '
                    f'<span style="color:var(--text-4);font-weight:400;">'
                    f'{_html.escape(hint)}</span>'
                    f'</div>'
                )
                status_el = ui.html(
                    '<div style="color:var(--text-4);font-size:11px;margin-top:2px;">'
                    '미업로드</div>'
                )

                async def handle_upload(e: events.UploadEventArguments, _fkey=fkey, _status=status_el):
                    if state['upload_dir'] is None:
                        state['upload_dir'] = get_upload_dir(report_key)
                    upload_dir = state['upload_dir']
                    orig_name = e.file.name
                    # 한글 파일명을 subprocess stdin으로 안전하게 전달하기 위해
                    # 확장자는 유지하되 stem을 fkey 기반 ASCII 이름으로 저장
                    ext = Path(orig_name).suffix
                    safe_name = f"{_fkey}{ext}"
                    save_path = upload_dir / safe_name
                    data = await e.file.read()
                    with open(save_path, 'wb') as fp:
                        fp.write(data)
                    state['uploaded_files'][_fkey] = str(save_path)
                    _status.content = (
                        f'<div style="color:var(--text);font-size:11.5px;margin-top:2px;'
                        f'display:flex;align-items:center;gap:6px;">'
                        f'<span class="material-symbols-outlined" style="font-size:13px;color:var(--success);">check_circle</span>'
                        f'{_html.escape(orig_name)} ({len(data)//1024}KB)'
                        f'</div>'
                    )
                    ui.notify(f'{orig_name} 업로드 완료', type='positive', position='top')
                    _refresh_checklist()

                w = ui.upload(
                    on_upload=handle_upload,
                    auto_upload=True, max_files=1,
                    label='파일을 여기로 드래그하거나 클릭',
                ).props('accept=.csv,.xlsx,.xls flat bordered').classes(
                    'w-full upload-compact report-dropzone'
                )
                upload_widgets[fkey] = w

    def refresh_param_area(report_key: str):
        cfg = REPORT_CONFIGS[report_key]
        param_area.clear()
        param_inputs.clear()
        state['params'].clear()

        with param_area:
            for p_def in cfg['params']:
                pkey = p_def['key']
                label = p_def['label']
                hint = p_def.get('hint', '')
                optional = p_def.get('optional', False)
                lbl = label + (' (선택)' if optional else '')
                if p_def.get('type') == 'yymm':
                    param_inputs[pkey] = _build_yymm_picker(lbl, p_def.get('format', 'YYYYMM'))
                else:
                    inp = ui.input(label=lbl, placeholder=hint or label).props('outlined dense').classes('w-full mt-1')
                    inp.on('blur', lambda: _refresh_checklist())
                    param_inputs[pkey] = inp

    def _refresh_checklist():
        """B-2: 필수 파일/파라미터 충족 여부를 상시 체크리스트로 표시하고,
        전부 충족 전까지 실행 버튼을 비활성화한다."""
        report_key = state.get('selected')
        if not report_key:
            checklist_area.content = ''
            progress_summary_el.content = ''
            return
        cfg = REPORT_CONFIGS[report_key]
        items = []
        for f_def in cfg['files']:
            items.append((f_def['label'], f_def['key'] in state['uploaded_files']))
        for p_def in cfg['params']:
            if p_def.get('optional'):
                continue
            inp = param_inputs.get(p_def['key'])
            filled = bool((inp.value or '').strip()) if inp else False
            items.append((p_def['label'], filled))
        checklist_area.content = req_checklist_html(items)

        # 단순 보고서: 4단계 마법사를 강제하지 않는 대신, 진행 요약 한 줄만 보여준다.
        # 다단계(wizard) 보고서는 자체 스텝퍼가 이미 이 역할을 하므로 생략.
        if cfg.get('wizard'):
            progress_summary_el.content = ''
        else:
            ok_count = sum(1 for _, ok in items)
            total = len(items)
            progress_summary_el.content = (
                '<div style="display:flex;align-items:center;justify-content:space-between;'
                'font-size:12px;color:var(--text-3);padding:6px 10px;margin-bottom:10px;'
                'background:var(--bg-elev);border:1px solid var(--border);border-radius:var(--radius);">'
                f'<span style="color:var(--text-2);font-weight:600;">{_html.escape(cfg["name"])}</span>'
                f'<span>충족 항목 {ok_count}/{total}</span>'
                '</div>'
            )

        if all(ok for _, ok in items):
            run_btn.props(remove='disable')
        else:
            run_btn.props(add='disable')

    # ── FX5260 변동금리 인터랙션 ──────────────────────────────────────────
    # 원 스크립트는 변동금리 계좌를 print → 사용자가 사내 시스템에서 금리를 조회·입력하는
    # 흐름이다. 이를 UI로 옮긴다: [변동금리 분석] → 계좌 목록 → 계좌별 금리 입력 →
    # [금리 적용] 시 var_rates_json 파라미터를 자동 구성 → [실행].
    fx_state: dict = {'rate_inputs': {}}

    def refresh_fx5260_area(report_key: str):
        fx5260_area.clear()
        fx_state['rate_inputs'] = {}
        if report_key != 'fx5260':
            return
        with fx5260_area:
            ui.html('<div class="muted-label" style="margin-top:8px;">변동금리 계좌 처리</div>')
            fx_step_el = ui.html(step_list_html(_FX5260_STEPS, 0))
            ui.html(
                '<div class="muted-text" style="font-size:11.5px;color:var(--text-3);'
                'margin-bottom:6px;line-height:1.5;">'
                'CRMS·SEQ 파일 업로드와 기준년월 입력 후 [변동금리 분석]을 누르면 금리 입력이 '
                '필요한 계좌가 표시됩니다. 사내 시스템에서 조회한 금리를 입력하고 [금리 적용]을 '
                '누른 뒤 [실행]하세요.</div>'
            )
            analyze_btn = ui.button('변동금리 분석').classes('btn-primary-mono w-full mb-2')
            fx_list_area = ui.column().classes('w-full')

            async def _do_analyze():
                if 'crms' not in state['uploaded_files'] or 'seq' not in state['uploaded_files']:
                    ui.notify('CRMS·SEQ 파일을 먼저 업로드하세요.', type='warning', position='top')
                    return
                base_inp = param_inputs.get('base_yymm')
                base_raw = (base_inp.value or '').strip() if base_inp else ''
                if not base_raw:
                    ui.notify('기준년월(base_yymm)을 먼저 선택하세요.', type='warning', position='top')
                    return
                base_yymm = int(base_raw)

                accounts = await nicegui_run.io_bound(
                    analyze_fx5260_var_accounts, state['uploaded_files'], base_yymm,
                )
                fx_list_area.clear()
                fx_state['rate_inputs'] = {}

                if not accounts:
                    fx_step_el.content = step_list_html(_FX5260_STEPS, 3)
                    with fx_list_area:
                        ui.html('<div class="muted-text">변동금리 입력이 필요한 계좌가 없습니다. '
                                '바로 [실행]하세요.</div>')
                    var_inp = param_inputs.get('var_rates_json')
                    if var_inp:
                        var_inp.value = '{}'
                    return

                fx_step_el.content = step_list_html(_FX5260_STEPS, 1)
                with fx_list_area:
                    ui.html(
                        f'<div class="muted-text" style="margin:6px 0;">'
                        f'금리 입력 필요 계좌: <b>{len(accounts)}건</b></div>'
                    )
                    for acct in accounts:
                        with ui.row().classes('w-full items-center gap-2 no-wrap').style('margin-bottom:2px;'):
                            ui.html(
                                f'<span style="font-size:12px;color:var(--text-2);flex:1;'
                                f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
                                f'{_html.escape(str(acct))}</span>'
                            )
                            num = ui.number(label='금리(%)', value=0).props(
                                'outlined dense'
                            ).style('width:130px;')
                            fx_state['rate_inputs'][str(acct)] = num

                    apply_btn = ui.button('금리 적용').classes('btn-primary-mono w-full mt-2')

                    def _apply_rates():
                        rates = {}
                        for acct, num in fx_state['rate_inputs'].items():
                            try:
                                rates[acct] = float(num.value or 0)
                            except (TypeError, ValueError):
                                rates[acct] = 0.0
                        var_inp = param_inputs.get('var_rates_json')
                        if var_inp:
                            var_inp.value = json.dumps(rates, ensure_ascii=False)
                        fx_step_el.content = step_list_html(_FX5260_STEPS, 3)
                        add_chat_message('sys', f'변동금리 {len(rates)}건 적용 완료. 이제 [실행]을 누르세요.')
                        ui.notify('변동금리가 적용되었습니다. [실행]으로 보고서를 생성하세요.',
                                  type='positive', position='top')

                    apply_btn.on_click(_apply_rates)

            analyze_btn.on_click(_do_analyze)

    async def select_report(key: str):
        state['selected'] = key
        state['output_files'].clear()

        # 보고서 전환 시 이전 보고서의 채팅·안내 메시지를 초기화
        # (FX5260 등 특정 보고서 전용 안내가 다른 탭에 잔류하지 않도록)
        state['chat_messages'].clear()
        chat_container.clear()

        for k, btn in report_btns.items():
            btn.classes(remove='active')
        report_btns[key].classes(add='active')

        cfg = REPORT_CONFIGS[key]
        hint_label.content = (
            '<div class="info-block">'
            f'<div style="font-weight:600;font-size:13px;color:var(--text);">'
            f'{_html.escape(cfg["name"])}</div>'
            f'<div style="color:var(--text-3);font-size:12px;margin-top:4px;">'
            f'{_html.escape(cfg["description"])}</div>'
            '</div>'
        )

        state['upload_dir'] = get_upload_dir(key)
        refresh_upload_area(key)
        refresh_param_area(key)
        refresh_fx5260_area(key)
        run_btn.visible = True
        download_area.clear()
        _set_status_badge('idle', '준비')
        update_log(f"[{cfg['name']}] 파일을 업로드하고 파라미터를 입력한 후 실행하세요.")
        log_el.visible = False
        log_toggle_btn.text = '자세히 보기 (원시 로그)'
        _refresh_checklist()

        if key == 'fx5260':
            add_chat_message(
                'sys',
                "FX5260: CRMS·SEQ 업로드와 기준년월 입력 후 [변동금리 분석]으로 금리 입력 계좌를 확인하세요.",
            )

    for key in REPORT_CONFIGS:
        report_btns[key].on('click', lambda _e, k=key: asyncio.create_task(select_report(k)))

    async def execute_report():
        if state['running']:
            return
        report_key = state['selected']
        if not report_key:
            ui.notify('보고서를 먼저 선택하세요.', type='warning', position='top')
            return

        cfg = REPORT_CONFIGS[report_key]

        missing_files = [
            f_def['label'] for f_def in cfg['files']
            if f_def['key'] not in state['uploaded_files']
        ]
        if missing_files:
            ui.notify(f"필수 파일 미업로드: {', '.join(missing_files)}", type='warning', position='top')
            return

        params = {}
        for p_def in cfg['params']:
            pkey = p_def['key']
            raw_val = param_inputs.get(pkey)
            val = (raw_val.value or '').strip() if raw_val else ''
            if not val and not p_def.get('optional', False):
                ui.notify(f"필수 입력 누락: {p_def['label']}", type='warning', position='top')
                return
            ptype = p_def.get('type', 'str')
            try:
                if val:
                    params[pkey] = float(val) if ptype == 'float' else (int(val) if ptype == 'int' else val)
                else:
                    params[pkey] = ''
            except ValueError:
                ui.notify(f"숫자 형식 오류: {p_def['label']}", type='negative', position='top')
                return

        state['running'] = True
        progress_bar.visible = True
        run_btn.props(add='disable')
        download_area.clear()
        _set_status_badge('reviewing', '실행 중')
        update_log(f"[{cfg['name']}] 실행 중...\n")
        log_el.visible = False
        log_toggle_btn.text = '자세히 보기 (원시 로그)'
        add_chat_message('sys', f"{cfg['name']} 실행 시작")

        try:
            ok, log_text, outputs = await nicegui_run.io_bound(
                run_report, report_key, state['uploaded_files'], params,
            )
        finally:
            state['running'] = False
            progress_bar.visible = False
            run_btn.props(remove='disable')

        update_log(log_text)
        state['output_files'] = outputs

        # 입력 파일 삭제 (출력 파일은 다운로드를 위해 유지)
        output_set = set(outputs)
        for _fp in state['uploaded_files'].values():
            if _fp not in output_set:
                try:
                    if os.path.exists(_fp):
                        os.remove(_fp)
                except Exception:
                    pass

        if ok:
            _set_status_badge('done', '완료')
            add_chat_message('sys', f"{cfg['name']} 완료! 아래 다운로드 버튼을 이용하세요.")
            with download_area:
                ui.html('<div class="muted-label">다운로드</div>')
                for out_path in outputs:
                    p = Path(out_path)
                    if p.exists():
                        ui.button(
                            p.name,
                            on_click=lambda path=out_path, name=p.name:
                                ui.download(path, filename=name),
                        ).classes('btn-primary-mono w-full mb-1')
            ui.notify(f"{cfg['name']} 완료", type='positive', position='top')
            activity_log.record('report', cfg['name'], status='done')
        else:
            _set_status_badge('error', '오류')
            # 오류 시에는 원인 파악을 위해 클릭 없이 원시 로그를 바로 펼친다.
            log_el.visible = True
            log_toggle_btn.text = '숨기기 (원시 로그)'
            add_chat_message('sys', '실행 중 오류가 발생했습니다. 로그를 확인하세요.')
            ui.notify('실행 오류 발생', type='negative', position='top')
            activity_log.record('report', cfg['name'], status='error')

    run_btn.on_click(execute_report)
