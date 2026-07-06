"""
보고서 작성 패널 UI — 모노크롬 디자인 시스템 이식판

3-column 레이아웃: 좌측 보고서 목록 · 중앙 실행 로그 · 우측 입력/채팅.
"""
import os
import json
import asyncio
import html as _html
from pathlib import Path

from nicegui import ui, events, run as nicegui_run

from reporting_runner import REPORT_CONFIGS, run_report, get_upload_dir, analyze_fx5260_var_accounts
import activity_log


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
            log_el = ui.html(
                '<div class="log-area">'
                '<span style="color:#737373;">보고서를 선택하고 실행하세요.</span>'
                '</div>'
            )
            progress_bar = ui.linear_progress(value=0).props('indeterminate').classes('w-full mt-2')
            progress_bar.visible = False
            download_area = ui.column().classes('w-full mt-3')

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

            upload_area = ui.column().classes('w-full')
            param_area = ui.column().classes('w-full mt-2')
            fx5260_area = ui.column().classes('w-full mt-2')   # FX5260 변동금리 분석 전용 영역

            run_btn = ui.button('실행').classes('btn-primary-mono w-full mt-3')
            run_btn.visible = False

            ui.html(
                '<div class="muted-label" style="margin-top:16px;">메모 / 추가 입력</div>'
            )
            chat_container = ui.column().classes('w-full').style(
                'background:var(--bg-elev);border:1px solid var(--border);'
                'border-radius:var(--radius);height:160px;overflow-y:auto;'
                'padding:8px;display:flex;flex-direction:column;gap:6px;'
            )
            with ui.row().classes('w-full gap-2 mt-2 no-wrap'):
                chat_input = ui.input(placeholder='메시지 입력...').props('outlined dense').classes('flex-1')
                send_btn = ui.button('전송').classes('btn-primary-mono')

    # ─── 이벤트 / 헬퍼 ───────────────────────────────────────────────────

    param_inputs: dict = {}
    upload_widgets: dict = {}

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
                        f'<span class="material-symbols-outlined" style="font-size:13px;color:#16a34a;">check_circle</span>'
                        f'{_html.escape(orig_name)} ({len(data)//1024}KB)'
                        f'</div>'
                    )
                    ui.notify(f'{orig_name} 업로드 완료', type='positive', position='top')

                w = ui.upload(
                    on_upload=handle_upload,
                    auto_upload=True, max_files=1,
                ).props('accept=.csv,.xlsx,.xls flat bordered').classes('w-full')
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
                inp = ui.input(label=lbl, placeholder=hint or label).props('outlined dense').classes('w-full mt-1')
                param_inputs[pkey] = inp

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
                    ui.notify('기준년월(base_yymm)을 먼저 입력하세요.', type='warning', position='top')
                    return
                try:
                    base_yymm = int(base_raw)
                except ValueError:
                    ui.notify('기준년월은 숫자 6자리(YYYYMM)여야 합니다.', type='negative', position='top')
                    return

                accounts = await nicegui_run.io_bound(
                    analyze_fx5260_var_accounts, state['uploaded_files'], base_yymm,
                )
                fx_list_area.clear()
                fx_state['rate_inputs'] = {}

                if not accounts:
                    with fx_list_area:
                        ui.html('<div class="muted-text">변동금리 입력이 필요한 계좌가 없습니다. '
                                '바로 [실행]하세요.</div>')
                    var_inp = param_inputs.get('var_rates_json')
                    if var_inp:
                        var_inp.value = '{}'
                    return

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
        update_log(f"[{cfg['name']}] 파일을 업로드하고 파라미터를 입력한 후 실행하세요.")

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
        update_log(f"[{cfg['name']}] 실행 중...\n")
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
            add_chat_message('sys', '실행 중 오류가 발생했습니다. 로그를 확인하세요.')
            ui.notify('실행 오류 발생', type='negative', position='top')
            activity_log.record('report', cfg['name'], status='error')

    run_btn.on_click(execute_report)
