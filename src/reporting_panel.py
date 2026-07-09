"""
보고서 작성 패널 UI — 모노크롬 디자인 시스템 이식판

3-column 레이아웃: 좌측 보고서 목록 · 중앙 파일 업로드/파라미터 입력 ·
우측 AI 어시스턴트 채팅 + 실행 로그.
"""
import os
import json
import asyncio
import datetime
import html as _html
from pathlib import Path

from nicegui import ui, app, events, run as nicegui_run

from reporting_runner import REPORT_CONFIGS, run_report, get_upload_dir, analyze_fx5260_var_accounts
import activity_log
import llm_status
from ui_styles import req_checklist_html, step_list_html

_FX5260_STEPS = ['변동금리 분석', '금리 입력', '금리 적용', '실행']


def build_reporting_panel(config: dict, create_llm_fn, app_state: dict):
    """보고서 작성 패널을 현재 NiceGUI 컨텍스트에 추가합니다.

    호출하는 쪽에서 ``.panel`` 컨테이너 안에 배치해 주세요 (page-head 포함).

    Args:
        create_llm_fn: ``app.py`` 의 ``create_llm(model_id=None)`` 팩토리.
            우측 AI 어시스턴트 채팅이 이 함수로 LLM 을 생성해 사용한다.
        app_state: 상단 네비게이션의 ``selected_model_id``/``persona_block`` 등을
            담고 있는 페이지 전역 state dict (QA 패널과 동일한 것을 공유).
    """

    state = {
        "selected": None,
        "upload_dir": None,
        "uploaded_files": {},
        "params": {},
        "output_files": [],
        "running": False,
        "last_log_text": "",
    }

    # ── 헤더 ─────────────────────────────────────────────────────────────
    with ui.element('div').classes('page-head'):
        ui.html(
            '<div class="titles">'
            '<div class="page-title">보고서 작성</div>'
            '<div class="page-subtitle">파일을 업로드하고 보고서를 자동으로 작성합니다.</div>'
            '</div>'
        )

    # ── 본문: 3분할 (보고서 목록 / 업로드·파라미터 / AI 어시스턴트+로그) ──
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

        # ── 중앙: 파일 업로드 / 파라미터 입력 ─────────────────────────────
        with ui.element('div').style('display:flex; flex-direction:column;'):
            ui.html(
                '<div class="section-card-title">'
                '<span class="material-symbols-outlined">edit_note</span>파일 업로드 / 파라미터'
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

            # 반복 실행 편의 — 저장된 직전 파라미터가 있을 때만 노출.
            # 파일은 세션마다 재업로드가 필요하므로 값만 복원한다.
            restore_btn = ui.button('직전 설정으로 실행').props('outline dense no-caps').classes('w-full mt-2')
            restore_btn.visible = False

        # ── 우측: AI 어시스턴트 채팅 + 실행 로그 ──────────────────────────
        with ui.element('div').style('display:flex; flex-direction:column;'):
            ui.html(
                '<div class="section-card-title">'
                '<span class="material-symbols-outlined">smart_toy</span>AI 어시스턴트'
                '</div>'
            )
            with ui.element('div').classes('chat-wrap').style(
                'flex:0 0 340px; height:340px; border:1px solid var(--border);'
                'border-radius:var(--radius);margin-bottom:16px;'
            ):
                chat_empty_el = ui.element('div').classes('chat-empty')
                with chat_empty_el:
                    ui.html(
                        '<div class="empty-mark">'
                        '<span class="material-symbols-outlined">smart_toy</span>'
                        '</div>'
                        '<h2 style="font-size:14px;">보고서 작성에 대해 물어보세요</h2>'
                        '<p style="font-size:12px;">필요한 파일·파라미터, 진행 상태, 직전 실행 '
                        '결과나 오류 원인 등을 답해드립니다.</p>'
                    )

                chat_scroll_el = ui.element('div').classes('chat-scroll').style('display:none;')
                with chat_scroll_el:
                    chat_inner_el = ui.element('div').classes('chat-inner')

                with ui.element('div').classes('composer-wrap'):
                    with ui.element('div').classes('composer'):
                        assistant_input = ui.textarea(
                            placeholder='보고서 작성에 대해 질문하세요…',
                        ).props('borderless autogrow rows=1 dense').classes('flex-1')

                        with ui.element('div').classes('composer-actions'):
                            assistant_clear_btn = ui.element('button').classes('icon-btn')
                            assistant_clear_btn.props('title="대화 초기화" aria-label="대화 초기화"')
                            with assistant_clear_btn:
                                ui.html('<span class="material-symbols-outlined">restart_alt</span>')

                            assistant_send_btn = ui.element('button').classes('send-btn')
                            assistant_send_btn.props('title="전송 (Enter)" aria-label="메시지 전송"')
                            with assistant_send_btn:
                                ui.html('<span class="material-symbols-outlined">arrow_upward</span>')

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

    # ─── 이벤트 / 헬퍼 ───────────────────────────────────────────────────

    param_inputs: dict = {}
    upload_widgets: dict = {}

    def _saved_params_for(report_key: str) -> dict:
        return app.storage.user.get('report_last_params', {}).get(report_key, {})

    def _save_params_for(report_key: str, values: dict) -> None:
        store = app.storage.user.setdefault('report_last_params', {})
        store[report_key] = values
        app.storage.user['report_last_params'] = store

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

    # ── AI 어시스턴트 채팅 ────────────────────────────────────────────────
    # QA 패널(app.py _build_qa_panel)과 동일한 chat-wrap/msg 마크업·스트리밍
    # 패턴을 재사용한다. 다만 참고 문서 대신 [보고서 카탈로그]+[현재 상태]를
    # 컨텍스트로 주입해, 보고서 작성 방식·진행 상태·직전 실행 결과에 대한
    # 질의에 답할 수 있게 한다.
    assistant_chat: list[dict] = []

    def _msg_html(role: str, content: str, with_cursor: bool = False) -> str:
        is_user = (role == 'user')
        cls = 'msg user' if is_user else 'msg ai'
        avatar = '나' if is_user else 'AI'
        label = '사용자' if is_user else '어시스턴트'
        body = _html.escape(content).replace('\n', '<br>') if content else ''
        cursor = '<span class="chat-cursor"></span>' if with_cursor else ''
        return (
            f'<div class="{cls}">'
            f'<div class="msg-role"><span class="avatar">{avatar}</span><span>{label}</span></div>'
            f'<div class="msg-body">{body}{cursor}</div>'
            f'</div>'
        )

    def _show_chat_empty(visible: bool):
        chat_empty_el.style(f'display:{"flex" if visible else "none"};')
        chat_scroll_el.style(f'display:{"none" if visible else "block"};')

    def _scroll_chat_to_bottom():
        with chat_inner_el:
            ui.run_javascript(
                'document.querySelectorAll(".chat-scroll").forEach('
                's => { s.scrollTop = s.scrollHeight; });'
            )

    def _render_assistant_chat():
        chat_inner_el.clear()
        if not assistant_chat:
            _show_chat_empty(True)
            return
        _show_chat_empty(False)
        with chat_inner_el:
            for msg in assistant_chat:
                ui.html(_msg_html(msg['role'], msg['content']))
        _scroll_chat_to_bottom()

    def _report_catalog_text() -> str:
        lines = []
        for cfg in REPORT_CONFIGS.values():
            files = ', '.join(f['label'] for f in cfg['files']) or '없음'
            params = ', '.join(p['label'] for p in cfg['params']) or '없음'
            lines.append(f"- {cfg['name']}: {cfg['description']} | 필요 파일: {files} | 파라미터: {params}")
        return '\n'.join(lines)

    def _current_context_text() -> str:
        report_key = state.get('selected')
        if not report_key:
            return '(아직 보고서를 선택하지 않음)'
        cfg = REPORT_CONFIGS[report_key]
        uploaded = ', '.join(
            f_def['label'] for f_def in cfg['files'] if f_def['key'] in state['uploaded_files']
        ) or '없음'
        missing = ', '.join(
            f_def['label'] for f_def in cfg['files'] if f_def['key'] not in state['uploaded_files']
        ) or '없음'
        params_filled = ', '.join(
            f"{p_def['label']}={param_inputs[p_def['key']].value}"
            for p_def in cfg['params']
            if param_inputs.get(p_def['key']) and (param_inputs[p_def['key']].value or '').strip()
        ) or '없음'
        recent_hist = [
            f"{it['title']} ({it['badge_label']})"
            for it in activity_log.recent(20)
            if it['sub'].startswith('보고서 작성')
        ][:5]
        hist_block = '\n'.join(recent_hist) if recent_hist else '없음'
        last_log = (state.get('last_log_text') or '').strip()
        return (
            f"선택된 보고서: {cfg['name']}\n"
            f"업로드 완료된 파일: {uploaded}\n"
            f"미업로드 파일: {missing}\n"
            f"입력된 파라미터: {params_filled}\n"
            f"최근 보고서 실행 이력:\n{hist_block}\n"
            f"직전 실행 로그(최대 1000자):\n{last_log[:1000] if last_log else '(아직 실행 이력 없음)'}"
        )

    _assistant_busy = {'v': False}

    def _set_assistant_busy(busy: bool):
        _assistant_busy['v'] = busy
        try:
            if busy:
                assistant_send_btn.props('disabled')
                assistant_send_btn.classes(add='is-disabled')
            else:
                assistant_send_btn.props(remove='disabled')
                assistant_send_btn.classes(remove='is-disabled')
        except Exception:
            pass

    async def send_assistant_message():
        if not llm_status.guard():
            return
        if _assistant_busy['v']:
            return
        q = (assistant_input.value or '').strip()
        if not q:
            return
        _set_assistant_busy(True)
        assistant_input.value = ''
        try:
            await _do_send_assistant(q)
        finally:
            _set_assistant_busy(False)
            assistant_input.value = ''

    async def _do_send_assistant(q: str):
        assistant_chat.append({'role': 'user', 'content': q})
        _show_chat_empty(False)
        with chat_inner_el:
            ui.html(_msg_html('user', q))
            stream_bubble = ui.html(_msg_html('assistant', '', with_cursor=True))

        try:
            history_lines = []
            for m in assistant_chat[:-1]:
                role = '사용자' if m['role'] == 'user' else 'AI'
                history_lines.append(f'{role}: {m["content"]}')
            history_block = '\n'.join(history_lines) if history_lines else '(없음)'

            system_prompt = (
                '당신은 사내 보고서 자동화 플랫폼의 보고서 작성 도우미입니다. '
                '사용자가 각 보고서의 작성 방법·필요한 파일·파라미터, 현재 진행 상태, '
                '직전 실행 결과나 오류의 원인을 물으면 아래 [보고서 카탈로그]와 '
                '[현재 상태]에 근거해 한국어로 간결하게 답변하세요. '
                '근거로 확인할 수 없는 내용은 추측하지 말고 모른다고 답하세요.'
            )
            if app_state.get('persona_block'):
                system_prompt += '\n\n' + app_state['persona_block']

            user_prompt = (
                f'[보고서 카탈로그]\n{_report_catalog_text()}\n\n'
                f'[현재 상태]\n{_current_context_text()}\n\n'
                f'[이전 대화]\n{history_block}\n\n'
                f'[사용자 질문]\n{q}'
            )

            from langchain_core.messages import SystemMessage, HumanMessage
            llm = create_llm_fn(model_id=app_state.get('selected_model_id'))
            reply_parts: list[str] = []

            try:
                async for chunk in llm.astream([
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ]):
                    token = getattr(chunk, 'content', None)
                    if token:
                        reply_parts.append(token)
                        stream_bubble.content = _msg_html(
                            'assistant', ''.join(reply_parts), with_cursor=True
                        )
                        await asyncio.sleep(0)
                answer = ''.join(reply_parts)
            except Exception:
                def _sync_invoke():
                    resp = llm.invoke([
                        SystemMessage(content=system_prompt),
                        HumanMessage(content=user_prompt),
                    ])
                    return getattr(resp, 'content', None) or str(resp)
                answer = await nicegui_run.io_bound(_sync_invoke)

            final = answer or '(빈 응답)'
            stream_bubble.content = _msg_html('assistant', final)
            assistant_chat.append({'role': 'assistant', 'content': final})
            _scroll_chat_to_bottom()
        except Exception as e:
            err = f'답변 생성 중 오류가 발생했습니다: {e}'
            stream_bubble.content = _msg_html('assistant', err)
            assistant_chat.append({'role': 'assistant', 'content': err})

    async def clear_assistant_chat():
        assistant_chat.clear()
        _render_assistant_chat()

    assistant_send_btn.on('click', lambda _e: asyncio.create_task(send_assistant_message()))
    assistant_clear_btn.on('click', lambda _e: asyncio.create_task(clear_assistant_chat()))
    if not llm_status.is_available():
        assistant_send_btn.props('disabled')
        assistant_send_btn.classes(add='is-disabled')

    def _on_assistant_enter(_e):
        args = _e.args if isinstance(_e.args, dict) else {}
        if args.get('shiftKey') or args.get('isComposing'):
            return  # 줄바꿈 / 한글 IME 조합 중
        asyncio.create_task(send_assistant_message())
    assistant_input.on('keydown.enter', _on_assistant_enter)

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
                        ui.notify('변동금리가 적용되었습니다. [실행]으로 보고서를 생성하세요.',
                                  type='positive', position='top')

                    apply_btn.on_click(_apply_rates)

            analyze_btn.on_click(_do_analyze)

    async def select_report(key: str):
        state['selected'] = key
        state['output_files'].clear()

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
        restore_btn.visible = bool(_saved_params_for(key))
        download_area.clear()
        _set_status_badge('idle', '준비')
        update_log(f"[{cfg['name']}] 파일을 업로드하고 파라미터를 입력한 후 실행하세요.")
        log_el.visible = False
        log_toggle_btn.text = '자세히 보기 (원시 로그)'
        _refresh_checklist()

    for key in REPORT_CONFIGS:
        report_btns[key].on('click', lambda _e, k=key: asyncio.create_task(select_report(k)))

    def _validate_and_build_params(cfg: dict):
        """필수 파일/파라미터를 검증하고 params dict 를 만든다.
        실패 시 notify 를 띄우고 None 을 반환한다."""
        missing_files = [
            f_def['label'] for f_def in cfg['files']
            if f_def['key'] not in state['uploaded_files']
        ]
        if missing_files:
            ui.notify(f"필수 파일 미업로드: {', '.join(missing_files)}", type='warning', position='top')
            return None

        params = {}
        for p_def in cfg['params']:
            pkey = p_def['key']
            raw_val = param_inputs.get(pkey)
            val = (raw_val.value or '').strip() if raw_val else ''
            if not val and not p_def.get('optional', False):
                ui.notify(f"필수 입력 누락: {p_def['label']}", type='warning', position='top')
                return None
            ptype = p_def.get('type', 'str')
            try:
                if val:
                    params[pkey] = float(val) if ptype == 'float' else (int(val) if ptype == 'int' else val)
                else:
                    params[pkey] = ''
            except ValueError:
                ui.notify(f"숫자 형식 오류: {p_def['label']}", type='negative', position='top')
                return None
        return params

    async def execute_report(report_key: str, cfg: dict, params: dict):
        if state['running']:
            return

        state['running'] = True
        progress_bar.visible = True
        run_btn.props(add='disable')
        download_area.clear()
        _set_status_badge('reviewing', '실행 중')
        update_log(f"[{cfg['name']}] 실행 중...\n")
        log_el.visible = False
        log_toggle_btn.text = '자세히 보기 (원시 로그)'

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
        state['last_log_text'] = log_text

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
            saved_vals = {pkey: (inp.value or '') for pkey, inp in param_inputs.items()}
            _save_params_for(report_key, saved_vals)
            restore_btn.visible = True
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
            ui.notify('실행 오류 발생', type='negative', position='top')
            activity_log.record('report', cfg['name'], status='error')

    def _fill_saved_params(report_key: str) -> None:
        saved = _saved_params_for(report_key)
        for pkey, val in saved.items():
            inp = param_inputs.get(pkey)
            if inp is None:
                continue
            if hasattr(inp, 'restore'):
                inp.restore(val)
            else:
                inp.value = val
        _refresh_checklist()

    def _run_summary_html(cfg: dict, params: dict) -> str:
        """실행 직전 확인 요약: 보고서명 · 파일명(용량) · 기준월 · 첨부 파일 수."""
        file_lines = []
        for f_def in cfg['files']:
            fp = state['uploaded_files'].get(f_def['key'])
            if fp and os.path.exists(fp):
                size_kb = os.path.getsize(fp) // 1024
                file_lines.append(
                    f"{_html.escape(f_def['label'])}: {_html.escape(Path(fp).name)} ({size_kb}KB)"
                )
        yymm_keys = ('yymm', 'bfyymm', 'base_yymm', 'base_ym')
        yymm_vals = [str(params[k]) for k in yymm_keys if params.get(k)]
        lines = [f"<b>{_html.escape(cfg['name'])}</b>"] + file_lines
        if yymm_vals:
            lines.append(f"기준월: {_html.escape(', '.join(yymm_vals))}")
        lines.append(f"첨부 파일: {len(state['uploaded_files'])}건")
        return (
            '<div style="font-size:12.5px;color:var(--text-2);line-height:1.85;'
            'background:var(--bg-elev);border:1px solid var(--border);'
            'border-radius:var(--radius);padding:10px 14px;margin:8px 0;">'
            + '<br>'.join(lines) +
            '</div>'
        )

    def _confirm_before_run():
        report_key = state['selected']
        if not report_key:
            ui.notify('보고서를 먼저 선택하세요.', type='warning', position='top')
            return
        cfg = REPORT_CONFIGS[report_key]
        params = _validate_and_build_params(cfg)
        if params is None:
            return

        dlg = ui.dialog().props('persistent')
        with dlg, ui.card():
            ui.html(
                '<div class="section-card-title">'
                '<span class="material-symbols-outlined">fact_check</span>실행 전 확인'
                '</div>'
            )
            ui.html(_run_summary_html(cfg, params))
            with ui.row().classes('w-full justify-end gap-2 mt-2'):
                ui.button('취소', on_click=dlg.close).props('flat dense no-caps')

                def _confirm():
                    dlg.close()
                    asyncio.create_task(execute_report(report_key, cfg, params))

                ui.button('실행', on_click=_confirm).classes('btn-primary-mono')
        dlg.open()

    def _run_with_saved():
        _fill_saved_params(state['selected'])
        _confirm_before_run()

    run_btn.on_click(_confirm_before_run)
    restore_btn.on_click(_run_with_saved)

    _render_assistant_chat()
