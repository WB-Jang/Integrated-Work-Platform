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

    def _sync_model():
        """검색 직전 사이드바 선택 모델을 에이전트에 적용 (하드코딩 방지)."""
        if not model_getter:
            return
        try:
            prov, mdl = model_getter()
            if mdl:
                agent.set_model(prov, mdl)
        except Exception as e:
            log.warning("법률검색 모델 동기화 실패: %s", e)

    # ── 페이지 헤더 ──────────────────────────────────────────────────────
    with ui.element('div').classes('page-head'):
        ui.html(
            '<div class="titles">'
            '<div class="page-title">법률 검색</div>'
            '<div class="page-subtitle">법령·감독규정을 자연어로 검색합니다.</div>'
            '</div>'
        )
        clear_btn = ui.button('대화 초기화').classes('btn-primary-mono')
        clear_btn.props('icon-right=refresh').style('display:none;')

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
        mem_status.content = (
            '<div class="mem-bar">'
            '<span>메모리</span>'
            '<div class="bar">'
            f'<div class="fill" style="width:{pct}%;"></div>'
            '</div>'
            f'<span>{chars:,} / {max_chars:,}자</span>'
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
            )
            sugg_row = ui.element('div').classes('suggestion-grid')

        scroll_area = ui.element('div').classes('chat-scroll').style('display:none;')
        with scroll_area:
            chat_inner = ui.element('div').classes('chat-inner')

        # ── Composer ────────────────────────────────────────────────────
        with ui.element('div').classes('composer-wrap'):
            with ui.element('div').classes('composer'):
                query_input = ui.textarea(
                    placeholder='법률 질문을 입력하세요 — 예: 개인정보 보호법상 정보주체의 권리는?',
                ).props('borderless autogrow rows=1 dense').classes('flex-1')
                with ui.element('div').classes('composer-actions'):
                    send_btn = ui.element('button').classes('send-btn')
                    send_btn.props('title="검색 (Enter)"')
                    with send_btn:
                        ui.html('<span class="material-symbols-outlined">arrow_upward</span>')
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

    def _add_bot_bubble(result: dict):
        answer = result.get('answer', '')
        keywords = result.get('keywords', [])
        docs = result.get('retrieved_docs', [])
        mode = result.get('search_mode', '')

        safe_answer = _html.escape(answer).replace('\n', '<br>')

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
        meta_html = ''.join(chips)

        docs_html = ''
        if docs:
            cards = []
            for d in docs[:3]:
                snippet = _html.escape(d[:220]).replace('\n', ' ')
                cards.append(
                    '<div class="result-item" style="margin-top:8px;padding:10px 14px;">'
                    f'<div style="font-size:12px;line-height:1.7;color:var(--text-2);">{snippet}…</div>'
                    '</div>'
                )
            docs_html = (
                '<div style="padding-left:30px;margin-top:6px;">'
                f'<div class="muted-label" style="margin-bottom:0;">참고 조항/판례</div>{"".join(cards)}'
                '</div>'
            )

        with chat_inner:
            ui.html(
                '<div class="msg ai">'
                '<div class="msg-role">'
                '<span class="avatar">AI</span><span>어시스턴트</span>'
                '</div>'
                f'<div class="msg-body">{safe_answer}</div>'
                + (f'<div class="msg-meta">{meta_html}</div>' if meta_html else '')
                + docs_html
                + '</div>'
            )
            # ui.run_javascript는 slot 컨텍스트 필요 — with 블록 안에서 호출
            ui.run_javascript(
                'document.querySelectorAll(".chat-scroll").forEach(s => '
                '{ s.scrollTop = s.scrollHeight; });'
            )

    _search_busy = {'v': False}

    def _set_search_busy(busy: bool):
        """답변 생성 중 전송 버튼 비활성화 (+ _search_busy 로 중복 전송 차단)."""
        _search_busy['v'] = busy
        try:
            if busy:
                send_btn.props('disabled')
                send_btn.classes(add='is-disabled')
            else:
                send_btn.props(remove='disabled')
                send_btn.classes(remove='is-disabled')
        except Exception:
            pass

    async def do_search(prompt_text: str = None):
        _apply_current_user()
        if _search_busy['v']:
            return  # 답변 생성 중 — 추가 전송 차단
        query = (prompt_text if prompt_text is not None else (query_input.value or '')).strip()
        if not query:
            return
        if not config.get("openrouter", {}).get("api_key"):
            ui.notify("config.json에 OpenRouter API 키를 입력해주세요.", type="warning", position='top')
            return
        _set_search_busy(True)
        query_input.value = ''
        try:
            await _do_search_inner(query)
        finally:
            _set_search_busy(False)
            # 늦게 도착한 입력 이벤트로 인한 잔류 텍스트 제거
            query_input.value = ''

    async def _do_search_inner(query: str):
        log.info('법률검색 질의: %s', query[:120])

        # 사이드바에서 선택한 모델을 에이전트에 동기화 (검색마다 최신 선택 반영)
        _sync_model()

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

        try:
            result = await nicegui_run.io_bound(agent.search, query)
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

        # 로딩 버블 제거하고 실제 답변 추가
        # ※ 사용자가 검색 중 '대화 초기화'를 누르거나 다른 do_search 가 chat_inner
        #    를 비웠다면 loading_bubble.delete() 가 ValueError 를 일으킴 → 안전 가드.
        try:
            loading_bubble.delete()
        except (ValueError, RuntimeError) as _del_exc:
            log.debug("loading_bubble 제거 스킵: %s", _del_exc)
        _add_bot_bubble(result)
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
    send_btn.on('click', lambda _e: asyncio.create_task(do_search()))

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

    _update_mem_status()
