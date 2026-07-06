"""
AI 에이전트 콘솔 (PoC) — 채팅창으로 앱 기능을 제어하는 Agentic System.

흐름: 사용자 자연어 명령 → LLM 이 '실행 계획(steps)' 수립 → 각 step 을
사용자에게 보고 → step 마다 승인(권한)을 받은 뒤에만 해당 도구를 실행 → 결과 보고.

PoC 범위: 도구 2종.
  1) list_legal_db  — 법령 벡터 DB 목록 조회 (read-only)
  2) search_legal   — 법률 검색 (질의 기반 RAG 응답)

도구를 추가하려면 AGENT_TOOLS 에 항목을 등록하면 된다.
"""
import asyncio
import json
import os
import re
import html as _html

from nicegui import ui, run as nicegui_run

from logger import get_logger

log = get_logger("agent_console")

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── 도구(handler) 구현 ────────────────────────────────────────────────────────
# 각 handler 는 (ctx: dict, args: dict) -> str (사용자에게 보여줄 결과 텍스트).
# ctx = {"config": dict, "state": dict, "create_llm": callable}
# 블로킹 작업이므로 UI 에서 nicegui_run.io_bound 로 호출한다.

def _tool_list_legal_db(ctx: dict, args: dict) -> str:
    config = ctx["config"]
    from legal_db_builder import list_law_indexes
    db_cfg = config.get("legal_db", {})
    db_dir = os.path.join(_BASE_DIR, db_cfg.get("faiss_dir", "./legal_db").lstrip("./"))
    rows = list_law_indexes(db_dir)
    if not rows:
        return "구축된 법령 DB가 없습니다."
    lines = [f"구축된 법령 DB {len(rows)}개:"]
    for r in rows:
        lines.append(
            f"  • {r['law_name']} — {r.get('doc_count', 0)}건 "
            f"(index {r.get('index_kb', 0)}KB / store {r.get('store_kb', 0)}KB)"
        )
    return "\n".join(lines)


def _tool_search_legal(ctx: dict, args: dict) -> str:
    config = ctx["config"]
    state = ctx.get("state") or {}
    query = (args.get("query") or "").strip()
    if not query:
        return "[오류] 검색어(query)가 비어 있습니다."
    # 법률검색 탭과 동일한 유저(IP)별 에이전트를 공유 — 대화 메모리 연속 + 인덱스 재로드 방지
    from legal_panel import _get_agent
    agent = _get_agent(config, state.get("client_ip", ""))
    agent.persona_block = state.get("persona_block", "") or ""
    res = agent.search(query)
    mode = {"vector": "벡터검색", "keyword": "키워드검색", "no_db": "DB없음(일반지식)"}.get(
        res.get("search_mode", ""), res.get("search_mode", "")
    )
    kws = ", ".join(res.get("keywords", []) or [])
    docs = res.get("retrieved_docs", []) or []
    out = [
        f"[검색 모드] {mode}   [추출 키워드] {kws}   [참조 조항] {len(docs)}건",
        "",
        res.get("answer", "(응답 없음)"),
    ]
    return "\n".join(out)


def _office_com_available() -> bool:
    if os.name != "nt":
        return False
    try:
        import win32com.client  # noqa: F401
        return True
    except Exception:
        return False


def _tool_convert_pdf(ctx: dict, args: dict) -> str:
    """현재 세션의 'PDF 변환' 업로드 폴더에 있는 파일을 PDF로 일괄 변환."""
    import queue as _queue
    state = ctx.get("state") or {}
    # PDF 변환 탭은 접속 시 발급되는 uuid 폴더(pdf_session_dir)를 사용
    sess = state.get("pdf_session_dir") or state.get("session_dir", "anon")
    base = os.path.join(_BASE_DIR, "uploads", "pdf", sess)
    input_dir = os.path.join(base, "input")
    output_dir = os.path.join(base, "output")

    files = [
        f for f in (os.listdir(input_dir) if os.path.isdir(input_dir) else [])
        if not f.startswith("~$")
    ]
    if not files:
        return ("변환할 파일이 없습니다. 먼저 [PDF 변환] 탭에서 Word/PowerPoint 파일을 "
                "업로드한 뒤 이 단계를 실행하세요. (업로드 파일은 세션별로 관리됩니다)")

    os.makedirs(output_dir, exist_ok=True)
    logq: "_queue.Queue" = _queue.Queue()
    try:
        if _office_com_available():
            import pythoncom
            pythoncom.CoInitialize()
            try:
                from ppt_word2pdf import convert_each_to_pdf, cleanup_gen_py
                convert_each_to_pdf(input_dir, output_dir, log_queue=logq)
                cleanup_gen_py()
            finally:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
            out_dir = output_dir
            engine = "Microsoft Office"
        else:
            from pdf_converter_Libre import batch_convert_to_pdf
            batch_convert_to_pdf(input_dir, log_queue=logq)
            out_dir = os.path.join(input_dir, "pdf_output")
            engine = "LibreOffice"
        pdfs = [f for f in os.listdir(out_dir) if f.lower().endswith(".pdf")] \
            if os.path.isdir(out_dir) else []
        return (f"[PDF 변환 완료] 엔진: {engine}\n"
                f"대상 {len(files)}개 → PDF {len(pdfs)}개 생성.\n"
                f"[PDF 변환] 탭에서 '변환 시작'을 누르면 결과 ZIP을 내려받을 수 있습니다.")
    except Exception as e:
        return f"[PDF 변환 실패] {e}"


def _tool_analyze_mail(ctx: dict, args: dict) -> str:
    """Outlook 메일을 조회해 LLM으로 분석. (로컬 Windows + Outlook 필요)"""
    import datetime as _dt
    state = ctx.get("state") or {}
    create_llm = ctx["create_llm"]

    def _parse_date(v, default):
        try:
            return _dt.date.fromisoformat(str(v)[:10])
        except Exception:
            return default

    today = _dt.date.today()
    end = _parse_date(args.get("end_date"), today)
    start = _parse_date(args.get("start_date"), end - _dt.timedelta(days=7))
    sender = (args.get("sender") or "").strip()
    recipient = (args.get("recipient") or "").strip()
    task = (args.get("task") or "메일 내용을 요약하고 핵심 사항을 정리해줘").strip()

    try:
        from outlook_agent import get_emails, analyze_emails
        emails = get_emails(start, end, sender, recipient, include_attachments=False)
    except Exception as e:
        return ("[메일 조회 실패] 로컬 Outlook 연결이 필요합니다(Windows + Outlook 실행). "
                f"오류: {e}")

    if not emails:
        return (f"{start} ~ {end} 기간에 조건(발신:{sender or '-'} / 수신:{recipient or '-'})에 "
                "해당하는 메일이 없습니다.")

    llm = create_llm(model_id=state.get("selected_model_id"))
    try:
        analysis = analyze_emails(emails, task, llm)
    except Exception as e:
        return f"[메일 분석 실패] {e}"
    return (f"[메일 분석] 기간 {start} ~ {end} · {len(emails)}건 · 작업: {task}\n\n{analysis}")


# ── 도구 레지스트리 ───────────────────────────────────────────────────────────
AGENT_TOOLS: dict = {
    "list_legal_db": {
        "label": "법령 DB 목록 조회",
        "description": "구축되어 있는 법령 벡터 DB 목록과 각 DB의 문서 수/용량을 조회한다. 인자 없음.",
        "params": {},          # 인자 스키마 (이름: 설명)
        "read_only": True,
        "handler": _tool_list_legal_db,
    },
    "search_legal": {
        "label": "법률 검색",
        "description": "법령/감독규정 벡터 DB에서 사용자 질문과 관련된 조항을 검색하고 근거와 함께 답변한다.",
        "params": {"query": "검색할 법률 질문 또는 키워드 (필수)"},
        "read_only": False,
        "handler": _tool_search_legal,
    },
    "convert_pdf": {
        "label": "PDF 변환",
        "description": ("현재 세션의 [PDF 변환] 탭에 업로드된 Word/PowerPoint 파일들을 PDF로 "
                        "일괄 변환한다. 인자 없음. (사전에 PDF 변환 탭에서 파일 업로드 필요)"),
        "params": {},
        "read_only": False,
        "handler": _tool_convert_pdf,
    },
    "analyze_mail": {
        "label": "메일 분석",
        "description": ("로컬 Outlook에서 기간/발신자/수신자 조건으로 메일을 조회하고 LLM으로 "
                        "요약·분석한다. 날짜는 YYYY-MM-DD. 미지정 시 최근 7일."),
        "params": {
            "start_date": "조회 시작일 YYYY-MM-DD (선택, 기본=종료일-7일)",
            "end_date": "조회 종료일 YYYY-MM-DD (선택, 기본=오늘)",
            "sender": "발신자 이름/이메일 일부 (선택)",
            "recipient": "수신자 이름/이메일 일부 (선택)",
            "task": "수행할 분석 작업 (선택, 예: 'A건 진행상황 정리')",
        },
        "read_only": False,
        "handler": _tool_analyze_mail,
    },
}


# ── 에이전트(LLM) — 안내인 + 작업 계획 수립 전문가 듀얼 모드 ──────────────────
_PLATFORM_GUIDE = """[플랫폼 기능 안내]
- 문서복합분석: DOCX/PDF/HWP 문서 오타 교정·논리 검증·Business Tone&Manner 검사
- 문서요약: 계층적 Map-Reduce 요약 또는 분량 축약
- 문서질의응답: 업로드한 문서(들)를 RAG 로 LLM 과 자유 대화
- 법률검색: 법령 FAISS 벡터 DB 기반 RAG 질의응답
- PDF변환: Word/PPT 일괄 PDF 변환
- 보고서작성: 템플릿 기반 재무데이터 자동 보고서 생성 (자유 주제 작문이 아님)
- 메일분석: Outlook 연동 (로컬 Windows + Outlook 필요)
- 규제동향: 금감원·한은·금융위 보도자료 LLM 요약
- Risk Dashboard / Risk Indicator Dashboard: 금감원 Open API·은행 재무지표 모니터링
- DB관리: 법령별 FAISS 벡터 DB 구축 (관리자 전용)"""

_PLANNER_SYSTEM = """당신은 사내 통합업무플랫폼(Integrated Work Platform)의 AI 에이전트입니다.
사용자는 금융기관 내부 업무 담당자입니다. 아래 두 역할을 대화 맥락에 따라 스스로 판단해 수행합니다.

[역할 1 — 플랫폼 안내인]
사용자가 플랫폼 사용법·기능 설명·"어떻게 하면 되는지" 같은 일반적인 질문을 하면, 아래 안내 자료를 바탕으로
친절하고 구체적으로 직접 답변하세요. 이 경우 도구를 실행할 필요가 없습니다 (mode="guide").

{platform_guide}

[역할 2 — 작업 계획 수립 전문가]
사용자가 구체적인 작업 수행을 요청하면(아래 도구 중 하나 이상으로 처리 가능한 경우), 정확하고 신뢰할 수 있는
단계별 실행 계획을 수립하세요 (mode="plan").
- 반드시 도구 목록에 있는 도구만 사용하세요. 없는 도구는 만들지 마세요.
- 각 단계(step)는 하나의 도구 호출입니다. 꼭 필요한 단계만 최소한으로 구성하세요.
- 계획의 품질이 최우선입니다. 명령을 정확히 수행하기에 필수 정보(날짜 범위, 분석 대상, 검색 범위, 조건 등)가
  불명확하거나 누락되었으면 절대 추측으로 채우지 말고, steps 를 빈 배열로 둔 채 clarification_needed 를
  true 로 설정하고 questions 에 필요한 질문을 구체적으로 나열하세요. 도구의 기본값만으로 충분히 고품질의
  계획이 가능한 경우에만 바로 계획을 수립하세요.
- 사용자가 clarification 질문에 답하면, 그 답변을 반영해 계획의 완성도를 다시 검토한 뒤 계획을 수립하거나
  여전히 불명확하면 추가로 되물으세요.
- 도구로 처리할 수 없는 요청이면 steps 를 비우고 mode="guide" 로 전환해 이유와 대안을 안내하세요.

[사용 가능한 도구]
{tool_catalog}

[Tone]
실무적이고 명확하게.

[출력 형식 — 반드시 아래 JSON 만 출력. 다른 설명/마크다운 금지]
{{"mode": "guide" 또는 "plan", "message": "guide 모드면 답변 전문, plan 모드면 한 줄 요약", "clarification_needed": false, "questions": [], "steps": [{{"tool": "도구이름", "args": {{}}, "reason": "이 단계가 필요한 이유"}}]}}"""


def _tool_catalog_text() -> str:
    lines = []
    for name, meta in AGENT_TOOLS.items():
        params = meta.get("params", {})
        if params:
            param_desc = "; ".join(f"{k}: {v}" for k, v in params.items())
        else:
            param_desc = "없음"
        lines.append(f"- {name} ({meta['label']}): {meta['description']} | 인자: {param_desc}")
    return "\n".join(lines)


def _parse_plan_json(raw: str) -> dict:
    raw = (raw or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    m2 = re.search(r"\{.*\}", raw, re.DOTALL)
    if m2:
        try:
            return json.loads(m2.group(0))
        except Exception:
            pass
    return {}


def plan_command(history: list[dict], create_llm, model_id) -> dict:
    """LLM 으로 대화 맥락을 안내 답변 또는 실행 계획(steps)으로 변환.

    블로킹 — io_bound 로 호출.

    Args:
        history: [{"role": "user"|"assistant", "content": str}, ...] — 마지막
            원소가 이번에 처리할 사용자 메시지. clarification 후속 답변을
            포함한 전체 대화 맥락을 그대로 전달하면 LLM 이 스스로 이전 질문에
            대한 답인지 판단해 계획을 완성한다.

    Returns dict with keys:
      mode ("guide"|"plan"), clarification_needed (bool),
      questions (list[str]), message (str), steps (list[dict])
    """
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
    llm = create_llm(model_id=model_id)
    sys_prompt = _PLANNER_SYSTEM.format(
        platform_guide=_PLATFORM_GUIDE, tool_catalog=_tool_catalog_text(),
    )
    msgs = [SystemMessage(content=sys_prompt)]
    for h in history:
        msgs.append(
            HumanMessage(content=h["content"]) if h.get("role") == "user"
            else AIMessage(content=h["content"])
        )
    resp = llm.invoke(msgs)
    data = _parse_plan_json(getattr(resp, "content", "") or "")

    mode = data.get("mode") if data.get("mode") in ("guide", "plan") else "plan"
    clarification_needed = bool(data.get("clarification_needed", False))
    questions = [str(q) for q in (data.get("questions") or []) if q]

    # 유효성 검증: 등록된 도구만 남긴다.
    valid_steps = []
    for s in data.get("steps", []) or []:
        tool = s.get("tool")
        if tool in AGENT_TOOLS:
            valid_steps.append({
                "tool": tool,
                "args": s.get("args", {}) or {},
                "reason": s.get("reason", ""),
            })
        else:
            log.warning("플래너가 미등록 도구 요청: %s", tool)
    return {
        "mode": mode,
        "clarification_needed": clarification_needed,
        "questions": questions,
        "message": data.get("message", ""),
        "steps": valid_steps,
    }


# ── UI ────────────────────────────────────────────────────────────────────────

_STATUS_META = {
    "대기":   ("#f59e0b", "rgba(245,158,11,.12)", "rgba(245,158,11,.35)"),
    "실행중": ("#0ea5e9", "rgba(14,165,233,.12)", "rgba(14,165,233,.35)"),
    "완료":   ("#22c55e", "rgba(34,197,94,.1)", "rgba(34,197,94,.3)"),
    "건너뜀": ("rgba(148,163,184,.7)", "rgba(255,255,255,.05)", "rgba(255,255,255,.15)"),
    "실패":   ("#ef4444", "rgba(239,68,68,.1)", "rgba(239,68,68,.3)"),
}


_AGENT_SUGGESTIONS = [
    ("이 플랫폼은 어떻게 쓰나요?",
     "전체 기능 개요와 사용법 안내",
     "이 플랫폼에 어떤 기능들이 있고 각각 어떻게 쓰는지 알려줘"),
    ("구축된 법령 DB 목록 알려줘",
     "법령 벡터 DB 조회 (읽기전용)",
     "구축된 법령 DB 목록 알려줘"),
    ("개인정보보호법에서 가명정보 처리 기준 찾아줘",
     "법률 검색 실행 계획 수립",
     "개인정보보호법에서 가명정보 처리 기준을 찾아줘"),
    ("이번주 메일 정리해줘",
     "필수 정보가 없으면 먼저 되물어봄",
     "이번주 받은 메일 정리해줘"),
]


def build_agent_panel(parent, state, create_llm, config):
    """AI 에이전트 패널 — 풀스크린 채팅 (법률 검색과 동일한 레이아웃).

    호출하는 쪽에서 ``.panel`` 컨테이너 안에 배치 (page-head 포함).

    듀얼 모드:
      - 안내인: 플랫폼 사용법/기능을 묻는 질문에는 직접 답변한다.
      - 작업 계획 수립 전문가: 구체적인 작업 요청에는 도구 기반 실행 계획을
        세우고, 정보가 불명확하면 계획을 낮은 품질로 만드는 대신 반드시
        되묻는다. 사용자의 다음 채팅 메시지가 그 답변으로 처리된다(전체
        대화 맥락을 매번 LLM 에 전달하므로 별도 폼이 필요 없다).
    """
    history: list[dict] = []   # [{'role': 'user'|'assistant', 'content': str}, ...] — LLM 컨텍스트

    with parent:
        with ui.element('div').classes('page-head'):
            ui.html(
                '<div class="titles">'
                '<div class="page-title">AI 에이전트</div>'
                '<div class="page-subtitle">플랫폼 사용법을 안내하거나, 작업 요청을 실행 계획으로 '
                '세워드립니다. 정보가 부족하면 먼저 되물어 계획의 완성도를 높입니다.</div>'
                '</div>'
            )

        chat_wrap = ui.element('div').classes('chat-wrap')
        with chat_wrap:
            empty_state = ui.element('div').classes('chat-empty')
            with empty_state:
                ui.html(
                    '<div class="empty-mark">'
                    '<span class="material-symbols-outlined">smart_toy</span>'
                    '</div>'
                    '<h2>무엇을 도와드릴까요?</h2>'
                    '<p>플랫폼 사용법을 물어보셔도 되고, "~해줘" 처럼 작업을 요청하시면 '
                    '실행 계획을 세워 단계별로 승인받아 처리합니다.</p>'
                )
                sugg_row = ui.element('div').classes('suggestion-grid')

            scroll_area = ui.element('div').classes('chat-scroll').style('display:none;')
            with scroll_area:
                chat_inner = ui.element('div').classes('chat-inner')

            with ui.element('div').classes('composer-wrap'):
                with ui.element('div').classes('composer'):
                    cmd_input = ui.textarea(
                        placeholder='무엇이든 물어보거나 작업을 요청하세요…',
                    ).props('borderless autogrow rows=1 dense').classes('flex-1')
                    with ui.element('div').classes('composer-actions'):
                        send_btn = ui.element('button').classes('send-btn')
                        send_btn.props('title="전송 (Enter)"')
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

        def _scroll_bottom():
            with chat_inner:
                ui.run_javascript(
                    'document.querySelectorAll(".chat-scroll").forEach(s => '
                    '{ s.scrollTop = s.scrollHeight; });'
                )

        def _add_user_bubble(text: str):
            safe = _html.escape(text).replace('\n', '<br>')
            with chat_inner:
                ui.html(
                    '<div class="msg user">'
                    '<div class="msg-role"><span class="avatar">나</span><span>사용자</span></div>'
                    f'<div class="msg-body">{safe}</div>'
                    '</div>'
                )

        def _add_ai_text_bubble(text: str, is_error: bool = False):
            safe = _html.escape(text).replace('\n', '<br>')
            color = 'color:var(--danger);' if is_error else ''
            with chat_inner:
                ui.html(
                    '<div class="msg ai">'
                    '<div class="msg-role"><span class="avatar">AI</span><span>어시스턴트</span></div>'
                    f'<div class="msg-body" style="{color}">{safe}</div>'
                    '</div>'
                )

        def _add_ai_loading_bubble():
            with chat_inner:
                bubble = ui.html(
                    '<div class="msg ai">'
                    '<div class="msg-role"><span class="avatar">AI</span><span>어시스턴트</span></div>'
                    '<div class="msg-body"><span class="chat-cursor"></span></div>'
                    '</div>'
                )
            return bubble

        _THINKING_STAGES = [
            '요청을 분석하고 있습니다…',
            '플랫폼 기능과 대조하고 있습니다…',
            '실행 계획을 정리하고 있습니다…',
        ]

        async def _animate_stage_bubble(bubble):
            """LLM 호출이 끝날 때까지 로딩 버블의 문구를 순환시켜, 실제 진행 단계는
            알 수 없지만(단일 JSON 호출이라 중간 단계 훅이 없음) 모델이 계속
            작업 중임을 사용자가 실시간으로 느낄 수 있도록 한다."""
            i = 0
            try:
                while True:
                    await asyncio.sleep(1.4)
                    label = _THINKING_STAGES[i % len(_THINKING_STAGES)]
                    bubble.content = (
                        '<div class="msg ai">'
                        '<div class="msg-role"><span class="avatar">AI</span><span>어시스턴트</span></div>'
                        '<div class="msg-body" style="color:var(--text-3);display:flex;align-items:center;gap:8px;">'
                        '<span class="material-symbols-outlined" '
                        'style="font-size:16px;animation:spin 1.2s linear infinite;">progress_activity</span>'
                        f'{label}</div>'
                        '</div>'
                    )
                    i += 1
            except asyncio.CancelledError:
                pass

        # ── step 게이팅 (플랜 카드 1개당 독립된 상태) ──────────────────────
        def _add_plan_bubble(message: str, steps: list):
            """실행 계획 말풍선 — STEP 카드(승인/건너뛰기)를 메시지 안에 렌더링."""
            pstate: dict = {
                'steps': [
                    {'tool': s['tool'], 'args': s['args'], 'reason': s['reason'], 'status': '대기'}
                    for s in steps
                ],
                'cards': [],
            }

            def _first_pending() -> int:
                for i, st in enumerate(pstate['steps']):
                    if st['status'] == '대기':
                        return i
                return -1

            def _set_status(i: int, status: str):
                pstate['steps'][i]['status'] = status
                card = pstate['cards'][i]
                fg, bg, bd = _STATUS_META.get(
                    status, ('rgba(148,163,184,.7)', 'rgba(255,255,255,.05)', 'rgba(255,255,255,.15)'),
                )
                card['badge'].content = (
                    f'<span style="padding:2px 10px;border-radius:999px;font-size:11.5px;'
                    f'font-weight:600;color:{fg};background:{bg};border:1px solid {bd};">'
                    f'{status}</span>'
                )

            def _refresh_gating():
                running = any(st['status'] == '실행중' for st in pstate['steps'])
                cur = -1 if running else _first_pending()
                for i, card in enumerate(pstate['cards']):
                    active = (i == cur)
                    for b in (card['approve'], card['skip']):
                        if active:
                            b.props(remove='disable')
                        else:
                            b.props(add='disable')

            async def _run_step(i: int):
                step = pstate['steps'][i]
                meta = AGENT_TOOLS[step['tool']]
                _set_status(i, '실행중')
                _refresh_gating()
                for b in (pstate['cards'][i]['approve'], pstate['cards'][i]['skip']):
                    b.props(add='disable')
                result_box = pstate['cards'][i]['result']
                result_box.content = '<div class="muted-text">실행 중…</div>'
                try:
                    ctx = {'config': config, 'state': state, 'create_llm': create_llm}
                    text = await nicegui_run.io_bound(meta['handler'], ctx, step['args'])
                    safe = _html.escape(text).replace('\n', '<br>')
                    result_box.content = (
                        '<div style="margin-top:8px;padding:10px 12px;border-radius:var(--radius);'
                        'background:var(--bg-elev);border:1px solid var(--border);font-size:13px;'
                        'line-height:1.6;color:var(--text);white-space:normal;">'
                        f'{safe}</div>'
                    )
                    _set_status(i, '완료')
                    log.info("도구 실행 완료: %s args=%s", step['tool'], step['args'])
                    # 실행 결과를 대화 맥락에 남겨 이후 질의응답/계획 수립에 반영되도록 함
                    history.append({
                        'role': 'assistant',
                        'content': f"[{meta['label']} 실행 결과]\n{text}",
                    })
                except Exception as e:
                    result_box.content = (
                        '<div style="margin-top:8px;padding:10px 12px;border-radius:var(--radius);'
                        'background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.35);'
                        'font-size:13px;color:var(--danger);">'
                        f'실행 오류: {_html.escape(str(e))}</div>'
                    )
                    _set_status(i, '실패')
                    log.error("도구 실행 오류 (%s): %s", step['tool'], e)
                _refresh_gating()

            def _skip_step(i: int):
                _set_status(i, '건너뜀')
                _refresh_gating()

            with chat_inner:
                with ui.element('div').classes('msg ai'):
                    ui.html(
                        '<div class="msg-role"><span class="avatar">AI</span><span>어시스턴트</span></div>'
                        f'<div class="msg-body">{_html.escape(message)}</div>'
                        if message else
                        '<div class="msg-role"><span class="avatar">AI</span><span>어시스턴트</span></div>'
                    )
                    if not steps:
                        ui.html(
                            '<div class="muted-text" style="padding-left:30px;">'
                            '실행할 도구 단계가 없습니다.</div>'
                        )
                    else:
                        with ui.element('div').style('padding-left:30px;margin-top:6px;'):
                            for i, s in enumerate(steps):
                                meta = AGENT_TOOLS[s['tool']]
                                args_txt = ', '.join(
                                    f'{k}={v}' for k, v in (s['args'] or {}).items()
                                ) or '인자 없음'
                                ro = ' · 읽기전용' if meta.get('read_only') else ''
                                with ui.element('div').style(
                                    'border:1px solid var(--border);border-radius:var(--radius-lg);'
                                    'padding:14px 16px;margin-bottom:10px;background:var(--bg-elev);'
                                ):
                                    with ui.row().classes('w-full items-center no-wrap'):
                                        ui.html(
                                            f'<div style="flex:1;">'
                                            f'<div style="font-size:13.5px;font-weight:600;color:var(--text);">'
                                            f'STEP {i + 1}. {_html.escape(meta["label"])}'
                                            f'<span style="font-weight:400;color:var(--text-3);font-size:12px;">'
                                            f'  ({_html.escape(s["tool"])}{ro})</span></div>'
                                            f'<div style="font-size:12px;color:var(--text-2);margin-top:3px;">'
                                            f'인자: {_html.escape(args_txt)}</div>'
                                            f'<div style="font-size:12px;color:var(--text-3);margin-top:2px;">'
                                            f'사유: {_html.escape(s["reason"] or "-")}</div>'
                                            f'</div>'
                                        )
                                        badge = ui.html('')
                                    result = ui.html('')
                                    with ui.row().classes('gap-2 mt-2'):
                                        approve = ui.button(
                                            '승인 후 실행',
                                            on_click=lambda _e, idx=i: asyncio.create_task(_run_step(idx)),
                                        ).classes('btn-primary-mono btn-sm')
                                        skip = ui.button(
                                            '건너뛰기',
                                            on_click=lambda _e, idx=i: _skip_step(idx),
                                        ).classes('btn-mono btn-sm')
                                pstate['cards'].append(
                                    {'badge': badge, 'result': result, 'approve': approve, 'skip': skip}
                                )
                                _set_status(i, '대기')
            _refresh_gating()

        _busy = {'v': False}

        def _set_busy(busy: bool):
            _busy['v'] = busy
            try:
                if busy:
                    send_btn.props('disabled')
                    send_btn.classes(add='is-disabled')
                else:
                    send_btn.props(remove='disabled')
                    send_btn.classes(remove='is-disabled')
            except Exception:
                pass

        async def _send(text_override: str = None):
            text = (text_override if text_override is not None else cmd_input.value or '').strip()
            if not text or _busy['v']:
                return
            _set_busy(True)
            cmd_input.value = ''
            try:
                _ensure_chat_visible()
                _add_user_bubble(text)
                history.append({'role': 'user', 'content': text})
                loading = _add_ai_loading_bubble()
                _scroll_bottom()
                stage_task = asyncio.create_task(_animate_stage_bubble(loading))

                model_id = state.get('selected_model_id')
                try:
                    result = await nicegui_run.io_bound(
                        plan_command, list(history), create_llm, model_id,
                    )
                except Exception as e:
                    loading.delete()
                    _add_ai_text_bubble(f'계획 수립 오류: {e}', is_error=True)
                    log.error("에이전트 처리 오류: %s", e)
                    return
                finally:
                    stage_task.cancel()

                loading.delete()

                if result.get('clarification_needed') and result.get('questions'):
                    q_text = '정확한 계획을 세우려면 아래 정보가 필요합니다:\n' + '\n'.join(
                        f'· {q}' for q in result['questions']
                    )
                    history.append({'role': 'assistant', 'content': q_text})
                    _add_ai_text_bubble(q_text)
                    log.info("에이전트 clarification 요청: %s", result['questions'])
                elif result.get('mode') == 'guide' or not result.get('steps'):
                    msg = result.get('message') or '요청을 이해하지 못했습니다. 다시 말씀해 주세요.'
                    history.append({'role': 'assistant', 'content': msg})
                    _add_ai_text_bubble(msg)
                else:
                    msg = result.get('message', '')
                    history.append({
                        'role': 'assistant',
                        'content': (msg + '\n' if msg else '') + '\n'.join(
                            f"- {s['tool']}({s['args']})" for s in result['steps']
                        ),
                    })
                    _add_plan_bubble(msg, result['steps'])

                if len(history) > 40:
                    history[:] = history[-30:]
                _scroll_bottom()
            finally:
                _set_busy(False)

        with sugg_row:
            for title, sub, prompt in _AGENT_SUGGESTIONS:
                b = ui.element('button').classes('suggestion')
                with b:
                    ui.html(
                        f'<span class="s-title">{_html.escape(title)}</span>'
                        f'<span class="s-sub">{_html.escape(sub)}</span>'
                    )
                b.on('click', lambda _e, p=prompt: asyncio.create_task(_send(p)))

        async def _on_enter(e):
            args = e.args if isinstance(e.args, dict) else {}
            if args.get('shiftKey') or args.get('isComposing'):
                return
            await _send()

        cmd_input.on('keydown.enter', _on_enter)
        send_btn.on('click', lambda _e: asyncio.create_task(_send()))
