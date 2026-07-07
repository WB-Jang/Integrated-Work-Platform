"""
법률 검색 패널 UI — 모노크롬 풀-블리드 채팅 레이아웃

기존 src/legal_panel.py 를 대체하는 드롭인 파일.
LegalSearchAgent 인터페이스(검색·메모리·DB 재로드)는 원본 그대로 사용합니다.
"""
import asyncio
import html as _html
from nicegui import ui, run as nicegui_run, app as nicegui_app

from legal_search import LegalSearchAgent
from logger import get_logger, set_current_user
import activity_log

log = get_logger("legal_panel")


def _apply_current_user() -> None:
    """현재 브라우저 세션의 이니셜을 로거 컨텍스트로 적용 (안전 호출)."""
    try:
        v = (nicegui_app.storage.user.get('initials') or '-').strip().upper()
    except Exception:
        v = '-'
    set_current_user(v or '-')

def _get_agent(config: dict, user_key: str = "") -> LegalSearchAgent:
    """유저(접속 IP)별 법률 검색 에이전트를 반환한다.

    기존에는 config 단위 전역 캐시여서 **모든 유저가 하나의 대화 메모리를
    공유**했다. 이제 user_memory 저장소에 유저별로 보관하여, 같은 IP 로
    재접속하면 본인의 대화 메모리를 그대로 이어받는다.
    (FAISS 인덱스는 legal_search._INDEX_CACHE 로 전역 공유 — 메모리 중복 없음)
    """
    import user_memory
    store = user_memory.get_user_data(user_key)
    agent = store.get('legal_agent')
    if agent is None:
        agent = LegalSearchAgent(config)
        store['legal_agent'] = agent
    return agent


def reload_agent_db(config: dict):
    """DB 재구축 후 인덱스 리로드. 인덱스 캐시는 전역 공유·in-place 갱신이므로
    아무 에이전트 하나에서 reload 하면 모든 유저 에이전트에 반영된다."""
    import user_memory
    agent = None
    for store in user_memory.all_user_data():
        a = store.get('legal_agent')
        if a is not None:
            agent = a
            break
    if agent is None:
        agent = LegalSearchAgent(config)
    agent.reload_db()


_LEGAL_SUGGESTIONS = [
    ("개인정보 보호법상 정보주체의 권리는?",
     "권리 유형과 행사 방법",
     "개인정보 보호법에서 정보주체의 권리는 무엇인가요?"),
    ("은행법 자본금 요건",
     "최저자본금과 인가 기준",
     "은행법에서 정한 최저자본금과 인가 요건을 알려줘"),
    ("외환거래법 신고 대상",
     "거래 유형별 신고 기준",
     "외환거래법상 사전 신고 대상이 되는 거래 유형은?"),
    ("자본시장법 내부자거래 규제",
     "미공개 중요정보 이용 행위",
     "자본시장법상 미공개 중요정보 이용행위 규제 내용은?"),
]


def build_legal_panel(config: dict, user_ip: str = "", persona_block: str = "",
                      model_getter=None):
    """법률 검색 패널을 현재 NiceGUI 컨텍스트에 추가합니다.

    호출하는 쪽에서 ``.panel`` 컨테이너 안에 배치해 주세요.

    Args:
        config: 앱 설정 dict
        user_ip: 접속 유저 식별자(IP) — 유저별 대화 메모리 분리에 사용
        persona_block: 해당 IP 유저의 COSTAR 페르소나 (빈 문자열이면 미적용)
        model_getter: () -> (provider, model) 콜백. 사이드바에서 선택한 모델을
            반환한다. 검색 직전 호출되어 에이전트 LLM 모델을 동기화한다.
            None 이면 config 의 legal_*_llm 기본 모델을 사용.
    """
    agent = _get_agent(config, user_ip)
    # 페르소나는 접속 IP 가 확인된 유저의 것만 주입 (빈 문자열 = 미적용)
    agent.persona_block = persona_block or ""

    def _sync_model() -> str:
        """검색 직전 사이드바 선택 모델을 에이전트에 적용 (하드코딩 방지).
        반환값은 메타칩에 표시할 모델명(실패/미설정 시 빈 문자열)."""
        if not model_getter:
            return ''
        try:
            prov, mdl = model_getter()
            if mdl:
                agent.set_model(prov, mdl)
                return mdl
        except Exception as e:
            log.warning("법률검색 모델 동기화 실패: %s", e)
        return ''

    # ── 페이지 헤더 ──────────────────────────────────────────────────────
    with ui.element('div').classes('page-head'):
        ui.html(
            '<div class="titles">'
            '<div class="page-title">법률 검색</div>'
            '<div class="page-subtitle">법령·감독규정을 자연어로 검색합니다.</div>'
            '</div>'
        )
        clear_btn = ui.button('대화 초기화').classes('btn-primary-mono')
        clear_btn.props('icon-right=refresh id=legal-clear-btn').style('display:none;')

    # ── 검색 모드 / 메모리 상태 바 ───────────────────────────────────────
    laws = agent.get_loaded_laws()
    db_loaded = bool(laws)
    faiss_ok = db_loaded

    if db_loaded and faiss_ok:
        mode_chip_html = (
            f'<span class="status-chip ok"><span class="dot"></span>'
            f'벡터 검색 (FAISS) · {len(laws)}개 법령</span>'
        )
    elif db_loaded:
        mode_chip_html = (
            '<span class="status-chip warn"><span class="dot"></span>'
            '키워드 검색 (임베딩 서버 미연결)</span>'
        )
    else:
        mode_chip_html = (
            '<span class="status-chip err"><span class="dot"></span>'
            'DB 없음 — LLM 직접 답변</span>'
        )

    status_bar = ui.element('div').classes('search-status-bar')
    with status_bar:
        ui.html(mode_chip_html)
        if laws:
            preview = ', '.join(laws[:3]) + (f' 외 {len(laws)-3}' if len(laws) > 3 else '')
            ui.html(
                '<span class="status-chip">'
                '<span class="material-symbols-outlined" style="font-size:13px;">database</span>'
                f'{_html.escape(preview)}</span>'
            )
        mem_status = ui.html('')

    def _update_mem_status():
        chars = agent._total_history_chars()
        max_chars = agent.mem_cfg.get("max_chars", 5000)
        pct = min(100, int(chars / max_chars * 100)) if max_chars else 0
        warn = pct >= 80
        fill_style = (
            f'width:{pct}%;background:var(--danger);' if warn
            else f'width:{pct}%;'
        )
        warn_html = (
            '<button class="status-banner-link" id="legal-mem-clear-hint" type="button" '
            'style="margin-left:6px;font-size:11px;">지금 초기화</button>'
            if warn else ''
        )
        mem_status.content = (
            '<div class="mem-bar">'
            f'<span style="{"color:var(--danger);" if warn else ""}">메모리</span>'
            '<div class="bar">'
            f'<div class="fill" style="{fill_style}"></div>'
            '</div>'
            f'<span style="{"color:var(--danger);" if warn else ""}">{chars:,} / {max_chars:,}자</span>'
            f'{warn_html}'
            '</div>'
        )

    # ── 채팅 영역 ────────────────────────────────────────────────────────
    chat_wrap = ui.element('div').classes('chat-wrap')
    with chat_wrap:
        empty_state = ui.element('div').classes('chat-empty')
        with empty_state:
            ui.html(
                '<div class="empty-mark">'
                '<span class="material-symbols-outlined">gavel</span>'
                '</div>'
                '<h2>법령에 관해 무엇이든 물어보세요</h2>'
                '<p>사전 구축된 법령 FAISS 인덱스에서 의미적으로 유사한 조항을 찾아 답변합니다. '
                '인용된 조항과 검색 키워드는 답변 하단에 표시됩니다.</p>'
                '<p style="font-size:11.5px;color:var(--text-4);margin-top:-8px;">'
                '검색 모드 안내 — <b>벡터 검색</b>: 임베딩 서버로 의미상 유사한 조항을 찾습니다 · '
                '<b>키워드 검색</b>: 임베딩 서버 미연결 시 키워드로 대체 검색 · '
                '<b>LLM 직접</b>: 법령 DB 없이 모델이 직접 답변합니다.</p>'
            )
            sugg_row = ui.element('div').classes('suggestion-grid')

        scroll_area = ui.element('div').classes('chat-scroll').style('display:none;')
        with scroll_area:
            chat_inner = ui.element('div').classes('chat-inner')

        # ── C-4: 대화 시작 후에도 예시 질의에 접근 가능한 접이식 칩 ────────
        with ui.element('div').classes('composer-wrap'):
            with ui.row().classes('items-center gap-2').style('padding:0 4px;'):
                sugg_toggle_btn = ui.button('예시 질의 보기').props('flat dense no-caps').style(
                    'font-size:11px;color:var(--text-3);padding:2px 6px;'
                )
            sugg_persist_row = ui.element('div').classes('suggestion-grid').style('display:none;margin:4px 0 8px;')
            with sugg_persist_row:
                for title, sub, prompt in _LEGAL_SUGGESTIONS:
                    pb = ui.element('button').classes('suggestion')
                    with pb:
                        ui.html(
                            f'<span class="s-title">{_html.escape(title)}</span>'
                            f'<span class="s-sub">{_html.escape(sub)}</span>'
                        )
                    pb.on('click', lambda _e, p=prompt: asyncio.create_task(do_search(p)))

            sugg_state = {'open': False}

            def _toggle_persist_suggestions():
                sugg_state['open'] = not sugg_state['open']
                sugg_persist_row.style(
                    'display:grid;margin:4px 0 8px;' if sugg_state['open'] else 'display:none;'
                )
                sugg_toggle_btn.text = '예시 질의 숨기기' if sugg_state['open'] else '예시 질의 보기'

            sugg_toggle_btn.on_click(_toggle_persist_suggestions)

            with ui.element('div').classes('composer'):
                query_input = ui.textarea(
                    placeholder='법률 질문을 입력하세요 — 예: 개인정보 보호법상 정보주체의 권리는?',
                ).props('borderless autogrow rows=1 dense').classes('flex-1')
                with ui.element('div').classes('composer-actions'):
                    send_btn = ui.element('button').classes('send-btn')
                    send_btn.props('title="검색 (Enter)" aria-label="검색 실행"')
                    with send_btn:
                        send_btn_icon = ui.html('<span class="material-symbols-outlined">arrow_upward</span>')
            ui.html(
                '<div class="composer-hint">'
                '<span>Shift + Enter 줄바꿈</span>'
                '<span><span class="kbd">Enter</span> 전송</span>'
                '</div>'
            )

    def _ensure_chat_visible():
        empty_state.style('display:none;')
        scroll_area.style('display:block;')
        clear_btn.style('display:inline-flex;')

    def _add_user_bubble(text: str):
        safe = _html.escape(text).replace('\n', '<br>')
        with chat_inner:
            ui.html(
                '<div class="msg user">'
                '<div class="msg-role">'
                '<span class="avatar">나</span><span>사용자</span>'
                '</div>'
                f'<div class="msg-body">{safe}</div>'
                '</div>'
            )

    _bubble_seq = {'n': 0}

    def _doc_card_html(d: str) -> str:
        snippet = _html.escape(d[:220]).replace('\n', ' ')
        full = _html.escape(d).replace('\n', '<br>')
        return (
            '<div class="result-item" style="margin-top:8px;padding:10px 14px;">'
            f'<div class="doc-snippet" style="font-size:12px;line-height:1.7;color:var(--text-2);">'
            f'{snippet}…</div>'
            f'<div class="doc-full" style="display:none;font-size:12px;line-height:1.7;'
            f'color:var(--text-2);">{full}</div>'
            '<button class="result-action-btn doc-toggle-btn" type="button" '
            'style="margin-top:6px;">전체 보기</button>'
            '</div>'
        )

    def _add_bot_bubble(result: dict, model_label: str = ''):
        answer = result.get('answer', '')
        keywords = result.get('keywords', [])
        docs = result.get('retrieved_docs', [])
        mode = result.get('search_mode', '')

        safe_answer = _html.escape(answer).replace('\n', '<br>')
        _bubble_seq['n'] += 1
        bubble_id = f'legal-answer-{_bubble_seq["n"]}'

        chips = []
        if keywords:
            kw = ', '.join(_html.escape(k) for k in keywords[:5])
            chips.append(
                '<span class="meta-chip">'
                '<span class="material-symbols-outlined">key</span>'
                f'{kw}</span>'
            )
        if docs:
            chips.append(
                '<span class="meta-chip">'
                '<span class="material-symbols-outlined">menu_book</span>'
                f'참조 조항 {len(docs)}개</span>'
            )
        mode_labels = {'vector': '벡터 검색', 'keyword': '키워드 검색', 'no_db': 'LLM 직접'}
        if mode:
            chips.append(
                '<span class="meta-chip">'
                '<span class="material-symbols-outlined">search</span>'
                f'{mode_labels.get(mode, mode)}</span>'
            )
        if model_label:
            chips.append(
                '<span class="meta-chip">'
                '<span class="material-symbols-outlined">smart_toy</span>'
                f'{_html.escape(model_label)}</span>'
            )
        meta_html = ''.join(chips)

        # C-1: 참고 조항 — 각 카드 "전체 보기" 확장 + 3개 초과분은 "N개 더 보기"
        docs_html = ''
        if docs:
            first_cards = ''.join(_doc_card_html(d) for d in docs[:3])
            more_html = ''
            if len(docs) > 3:
                extra_cards = ''.join(_doc_card_html(d) for d in docs[3:])
                more_html = (
                    f'<div class="more-docs-wrap" style="display:none;">{extra_cards}</div>'
                    '<button class="result-action-btn more-docs-btn" type="button" '
                    f'style="margin-top:6px;">{len(docs) - 3}개 더 보기</button>'
                )
            docs_html = (
                '<div style="padding-left:30px;margin-top:6px;">'
                f'<div class="muted-label" style="margin-bottom:0;">참고 조항/판례'
                ' <span style="font-weight:400;color:var(--text-4);">'
                '(원 법령·조항 식별자는 색인에 없어 본문만 표시됩니다)</span></div>'
                f'{first_cards}{more_html}'
                '</div>'
            )

        # C-3: 답변 복사 / 이어서 질문 액션
        actions_html = (
            '<div class="result-actions">'
            '<button class="result-action-btn copy-answer-btn" type="button" '
            f'data-copy-target="{bubble_id}">'
            '<span class="material-symbols-outlined">content_copy</span>복사</button>'
            '<button class="result-action-btn continue-ask-btn" type="button">'
            '<span class="material-symbols-outlined">chat</span>이어서 질문</button>'
            '</div>'
        )

        with chat_inner:
            ui.html(
                '<div class="msg ai">'
                '<div class="msg-role">'
                '<span class="avatar">AI</span><span>어시스턴트</span>'
                '</div>'
                f'<div class="msg-body">{safe_answer}</div>'
                f'<div id="{bubble_id}" style="display:none;">{_html.escape(answer)}</div>'
                + (f'<div class="msg-meta">{meta_html}</div>' if meta_html else '')
                + docs_html
                + actions_html
                + '</div>'
            )
            # ui.run_javascript는 slot 컨텍스트 필요 — with 블록 안에서 호출
            ui.run_javascript(
                'document.querySelectorAll(".chat-scroll").forEach(s => '
                '{ s.scrollTop = s.scrollHeight; });'
            )

    _search_busy = {'v': False}
    _search_task_ctl: dict = {'task': None}

    def _set_search_busy(busy: bool):
        """검색 중에는 전송 버튼을 [중지] 토글로 전환 (C-2: 스트리밍 취소 가능)."""
        _search_busy['v'] = busy
        try:
            if busy:
                send_btn.classes(add='is-stop')
                send_btn.props('title="중지"')
                send_btn_icon.content = '<span class="material-symbols-outlined">stop</span>'
            else:
                send_btn.classes(remove='is-stop')
                send_btn.props('title="검색 (Enter)"')
                send_btn_icon.content = '<span class="material-symbols-outlined">arrow_upward</span>'
        except Exception:
            pass

    async def do_search(prompt_text: str = None):
        _apply_current_user()
        if _search_busy['v']:
            return  # 답변 생성 중 — 추가 전송 차단 (중지는 send_btn 클릭 핸들러에서 별도 처리)
        query = (prompt_text if prompt_text is not None else (query_input.value or '')).strip()
        if not query:
            return
        if not config.get("openrouter", {}).get("api_key"):
            ui.notify("config.json에 OpenRouter API 키를 입력해주세요.", type="warning", position='top')
            return
        _set_search_busy(True)
        query_input.value = ''
        _search_task_ctl['task'] = asyncio.current_task()
        try:
            await _do_search_inner(query)
        except asyncio.CancelledError:
            ui.notify('검색을 중지했습니다.', type='warning', position='top')
        finally:
            _set_search_busy(False)
            _search_task_ctl['task'] = None
            # 늦게 도착한 입력 이벤트로 인한 잔류 텍스트 제거
            query_input.value = ''

    def _on_send_or_stop():
        if _search_busy['v']:
            if _search_task_ctl['task'] is not None:
                _search_task_ctl['task'].cancel()
            return
        asyncio.create_task(do_search())

    async def _do_search_inner(query: str):
        log.info('법률검색 질의: %s', query[:120])

        # 사이드바에서 선택한 모델을 에이전트에 동기화 (검색마다 최신 선택 반영)
        current_model_label = _sync_model()

        _ensure_chat_visible()
        _add_user_bubble(query)

        # 로딩 버블
        with chat_inner:
            loading_bubble = ui.html(
                '<div class="msg ai">'
                '<div class="msg-role">'
                '<span class="avatar">AI</span><span>어시스턴트</span>'
                '</div>'
                '<div class="msg-body"><span class="chat-cursor"></span></div>'
                '</div>'
            )
            # ui.run_javascript는 slot 컨텍스트 필요 — with 블록 안에서 호출
            ui.run_javascript(
                'document.querySelectorAll(".chat-scroll").forEach(s => '
                '{ s.scrollTop = s.scrollHeight; });'
            )

        import time as _t
        _search_start_ts = _t.time()

        def _stage_html(label: str) -> str:
            return (
                '<div class="msg ai">'
                '<div class="msg-role"><span class="avatar">AI</span><span>어시스턴트</span></div>'
                '<div class="msg-body" style="color:var(--text-3);display:flex;align-items:center;gap:8px;">'
                '<span class="material-symbols-outlined" '
                'style="font-size:16px;animation:spin 1.2s linear infinite;">progress_activity</span>'
                f'<span>{_html.escape(label)}</span>'
                f'<span class="progress-block-elapsed" data-elapsed-since="{_search_start_ts}">0초 경과</span>'
                '</div>'
                '</div>'
            )

        def _token_html(text: str) -> str:
            safe = _html.escape(text).replace('\n', '<br>')
            return (
                '<div class="msg ai">'
                '<div class="msg-role"><span class="avatar">AI</span><span>어시스턴트</span></div>'
                f'<div class="msg-body">{safe}<span class="chat-cursor"></span></div>'
                '</div>'
            )

        result = None
        reply_parts: list[str] = []
        try:
            async for kind, payload in agent.search_streaming(query):
                if kind == 'stage':
                    loading_bubble.content = _stage_html(payload)
                elif kind == 'token':
                    reply_parts.append(payload)
                    loading_bubble.content = _token_html(''.join(reply_parts))
                    await asyncio.sleep(0)
                elif kind == 'done':
                    result = payload
        except asyncio.CancelledError:
            try:
                partial = ''.join(reply_parts)
                loading_bubble.content = (
                    '<div class="msg ai">'
                    '<div class="msg-role">'
                    '<span class="avatar">AI</span><span>어시스턴트</span>'
                    '</div>'
                    f'<div class="msg-body">{_html.escape(partial).replace(chr(10), "<br>")}'
                    '<br><span style="color:var(--text-4);font-size:11.5px;">'
                    '(사용자에 의해 중지됨)</span></div>'
                    '</div>'
                )
            except (ValueError, RuntimeError):
                pass
            raise
        except Exception as exc:
            try:
                loading_bubble.content = (
                    '<div class="msg ai">'
                    '<div class="msg-role">'
                    '<span class="avatar">AI</span><span>어시스턴트</span>'
                    '</div>'
                    f'<div class="msg-body" style="color:var(--danger);">[오류] {_html.escape(str(exc))}</div>'
                    '</div>'
                )
            except (ValueError, RuntimeError):
                pass
            return

        # 스트리밍 버블 제거하고 최종 답변(메타칩+참고 조항 카드 포함) 렌더링
        # ※ 사용자가 검색 중 '대화 초기화'를 누르거나 다른 do_search 가 chat_inner
        #    를 비웠다면 loading_bubble.delete() 가 ValueError 를 일으킴 → 안전 가드.
        try:
            loading_bubble.delete()
        except (ValueError, RuntimeError) as _del_exc:
            log.debug("loading_bubble 제거 스킵: %s", _del_exc)
        if result is not None:
            _add_bot_bubble(result, model_label=current_model_label)
        _update_mem_status()
        activity_log.record('legal', query[:40], status='done')

    # 추천 카드 클릭 → 즉시 검색
    with sugg_row:
        for title, sub, prompt in _LEGAL_SUGGESTIONS:
            b = ui.element('button').classes('suggestion')
            with b:
                ui.html(
                    f'<span class="s-title">{_html.escape(title)}</span>'
                    f'<span class="s-sub">{_html.escape(sub)}</span>'
                )
            b.on('click', lambda _e, p=prompt: asyncio.create_task(do_search(p)))

    # Enter 키 처리 (Shift+Enter 줄바꿈, 한글 IME 조합 중 Enter 무시)
    async def _on_enter(e):
        args = e.args if isinstance(e.args, dict) else {}
        if args.get('shiftKey') or args.get('isComposing'):
            return
        await do_search()

    query_input.on('keydown.enter', _on_enter)
    send_btn.on('click', lambda _e: _on_send_or_stop())

    def clear_conversation():
        agent.clear_history()
        chat_inner.clear()
        empty_state.style('display:flex;')
        scroll_area.style('display:none;')
        clear_btn.style('display:none;')
        _update_mem_status()
        ui.notify("대화 초기화 완료", type='info', position='top')

    clear_btn.on_click(clear_conversation)

    # ── 유저별 메모리 복원 — 같은 IP 로 재접속 시 이전 대화를 다시 표시 ────
    if agent.history:
        _ensure_chat_visible()
        for m in agent.history:
            if m.get('role') == 'user':
                _add_user_bubble(m.get('content', ''))
            else:
                safe = _html.escape(m.get('content', '')).replace('\n', '<br>')
                with chat_inner:
                    ui.html(
                        '<div class="msg ai">'
                        '<div class="msg-role">'
                        '<span class="avatar">AI</span><span>어시스턴트</span>'
                        '</div>'
                        f'<div class="msg-body">{safe}</div>'
                        '</div>'
                    )
        with chat_inner:
            ui.run_javascript(
                'document.querySelectorAll(".chat-scroll").forEach(s => '
                '{ s.scrollTop = s.scrollHeight; });'
            )

    # ── C-1/C-3/C-5: 결과 카드 확장, 답변 복사/이어서 질문, 메모리 경고 클릭 위임 ──
    ui.add_body_html('''
<script>
(function(){
  document.addEventListener('click', function(e){
    const toggleBtn = e.target.closest('.doc-toggle-btn');
    if (toggleBtn) {
      const card = toggleBtn.closest('.result-item');
      const snip = card.querySelector('.doc-snippet');
      const full = card.querySelector('.doc-full');
      const showingFull = full.style.display !== 'none';
      full.style.display = showingFull ? 'none' : 'block';
      snip.style.display = showingFull ? 'block' : 'none';
      toggleBtn.textContent = showingFull ? '전체 보기' : '접기';
      return;
    }
    const moreBtn = e.target.closest('.more-docs-btn');
    if (moreBtn) {
      const wrap = moreBtn.previousElementSibling;
      const showing = wrap.style.display !== 'none';
      wrap.style.display = showing ? 'none' : 'block';
      if (!showing) {
        const n = wrap.querySelectorAll('.result-item').length;
        moreBtn.textContent = '접기';
      } else {
        moreBtn.textContent = moreBtn.dataset.origText || moreBtn.textContent;
      }
      return;
    }
    const copyBtn = e.target.closest('.copy-answer-btn');
    if (copyBtn) {
      const targetId = copyBtn.getAttribute('data-copy-target');
      const el = document.getElementById(targetId);
      if (el && navigator.clipboard) {
        navigator.clipboard.writeText(el.textContent).then(function(){
          const orig = copyBtn.innerHTML;
          copyBtn.innerHTML = '<span class="material-symbols-outlined">check</span>복사됨';
          setTimeout(function(){ copyBtn.innerHTML = orig; }, 1500);
        });
      }
      return;
    }
    const contBtn = e.target.closest('.continue-ask-btn');
    if (contBtn) {
      const wrap = contBtn.closest('.chat-wrap');
      const ta = wrap ? wrap.querySelector('.composer textarea') : null;
      if (ta) { ta.focus(); }
      return;
    }
    const memClearBtn = e.target.closest('#legal-mem-clear-hint');
    if (memClearBtn) {
      document.getElementById('legal-clear-btn')?.click();
      return;
    }
  });
})();
</script>
''')

    _update_mem_status()
