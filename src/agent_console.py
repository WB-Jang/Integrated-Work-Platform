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


# ── 플래너(LLM) ────────────────────────────────────────────────────────────────
_PLANNER_SYSTEM = """당신은 사내 통합업무플랫폼을 조종하는 작업 계획 수립 에이전트입니다.

[Context]
사용자는 금융기관 내부 업무 담당자입니다. 주어진 도구만으로 자연어 명령을 실행합니다.

[Objective]
사용자의 명령을 정확하게 수행하기 위한 단계별 실행 계획을 수립하세요.

[사용 가능한 도구]
{tool_catalog}

[Tone]
실무적이고 명확하게. 추측 기반의 계획은 수립하지 마세요.

[Rules]
- 반드시 위 목록에 있는 도구만 사용하세요. 없는 도구는 만들지 마세요.
- 각 단계(step)는 하나의 도구 호출입니다. 꼭 필요한 단계만 최소한으로 구성하세요.
- 도구로 처리할 수 없는 명령이면 steps 를 빈 배열로 두고 message 에 이유를 적으세요.
- 명령을 정확히 수행하기에 필수 정보(날짜 범위, 분석 대상, 검색 범위 등)가 불명확하거나 누락된 경우,
  steps 를 빈 배열로 두고 clarification_needed 를 true 로 설정한 뒤 questions 에 질문을 나열하세요.
  단, 도구의 기본값으로 충분히 처리 가능한 경우는 바로 계획을 수립하세요.
- 출력은 아래 JSON 형식만 출력합니다. 다른 설명/마크다운 금지.

[Response — 출력 형식(JSON)]:
{{"clarification_needed": false, "questions": [], "message": "사용자에게 보여줄 한 줄 요약", "steps": [{{"tool": "도구이름", "args": {{}}, "reason": "이 단계가 필요한 이유"}}]}}"""


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


def plan_command(command: str, create_llm, model_id) -> dict:
    """LLM 으로 명령을 실행 계획(steps)으로 변환. 블로킹 — io_bound 로 호출.

    Returns dict with keys:
      clarification_needed (bool), questions (list[str]),
      message (str), steps (list[dict])
    """
    from langchain_core.messages import SystemMessage, HumanMessage
    llm = create_llm(model_id=model_id)
    sys_prompt = _PLANNER_SYSTEM.format(tool_catalog=_tool_catalog_text())
    resp = llm.invoke([SystemMessage(content=sys_prompt), HumanMessage(content=command)])
    data = _parse_plan_json(getattr(resp, "content", "") or "")

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
        "clarification_needed": clarification_needed,
        "questions": questions,
        "message": data.get("message", ""),
        "steps": valid_steps,
    }


# ── UI ────────────────────────────────────────────────────────────────────────

_STATUS_META = {
    "대기":   ("#92400e", "#fef3c7", "#d97706"),
    "실행중": ("#1e40af", "#dbeafe", "#3b82f6"),
    "완료":   ("#15803d", "#dcfce7", "#22c55e"),
    "건너뜀": ("#525252", "#f5f5f5", "#a3a3a3"),
    "실패":   ("#b91c1c", "#fee2e2", "#ef4444"),
}


def build_agent_panel(parent, state, create_llm, config):
    """AI 에이전트 콘솔 패널.

    호출하는 쪽에서 ``.panel`` 컨테이너 안에 배치 (page-head 포함).
    """
    with parent:
        with ui.element('div').classes('page-head'):
            ui.html(
                '<div class="titles">'
                '<div class="page-title">AI 에이전트 콘솔 <span style="font-size:12px;'
                'color:var(--text-3);font-weight:500;">(PoC)</span></div>'
                '<div class="page-subtitle">명령을 입력하면 실행 계획을 세우고, 각 단계를 '
                '승인하면 해당 기능을 실행합니다. 정보가 부족한 경우 에이전트가 추가 정보를 요청합니다.</div>'
                '</div>'
            )

        with ui.element('div').style(
            'flex:1; overflow:auto; padding:24px 32px; max-width:920px; margin:0 auto; width:100%;'
        ):
            # 사용 가능한 도구 안내
            tool_chips = "".join(
                f'<span style="display:inline-block;padding:3px 10px;margin:0 6px 6px 0;'
                f'font-size:12px;border:1px solid var(--border);border-radius:999px;'
                f'background:var(--bg-elev);color:var(--text-2);">{_html.escape(m["label"])}</span>'
                for m in AGENT_TOOLS.values()
            )
            ui.html(
                '<div class="muted-label">사용 가능한 도구</div>'
                f'<div style="margin:6px 0 14px;">{tool_chips}</div>'
            )

            # 명령 입력
            with ui.row().classes('w-full gap-2 no-wrap items-end'):
                cmd_input = ui.textarea(
                    placeholder='예) 구축된 법령 DB 목록 알려줘 / 개인정보보호법에서 가명정보 처리 기준 찾아줘',
                ).props('outlined autogrow rows=1 dense').classes('flex-1')
                plan_btn = ui.button('계획 수립').classes('btn-primary-mono')

            # 플래너 메시지
            plan_msg = ui.html('')

            # ── Clarification(추가 정보 요청) 영역 ─────────────────────────
            clarif_area = ui.element('div').classes('w-full')
            clarif_area.visible = False

            # 실행 계획(step 카드) 영역
            ui.html('<div class="muted-label" style="margin-top:18px;">실행 계획</div>')
            plan_area = ui.column().classes('w-full mt-1')
            with plan_area:
                ui.html('<div class="muted-text">명령을 입력하고 [계획 수립]을 누르세요.</div>')

            # 패널 상태
            pstate: dict = {
                'steps': [], 'cards': [],
                'original_command': '',
                'clarif_inputs': [],
            }

            # ── step 게이팅: 첫 '대기' step 만 승인/건너뛰기 활성화 ──────────
            def _first_pending() -> int:
                for i, st in enumerate(pstate['steps']):
                    if st['status'] == '대기':
                        return i
                return -1

            def _set_status(i: int, status: str):
                pstate['steps'][i]['status'] = status
                card = pstate['cards'][i]
                fg, bg, bd = _STATUS_META.get(status, ('#525252', '#f5f5f5', '#a3a3a3'))
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
                except Exception as e:
                    result_box.content = (
                        '<div style="margin-top:8px;padding:10px 12px;border-radius:var(--radius);'
                        'background:#fee2e2;border:1px solid #ef4444;font-size:13px;color:#b91c1c;">'
                        f'실행 오류: {_html.escape(str(e))}</div>'
                    )
                    _set_status(i, '실패')
                    log.error("도구 실행 오류 (%s): %s", step['tool'], e)
                _refresh_gating()

            def _skip_step(i: int):
                _set_status(i, '건너뜀')
                _refresh_gating()

            def _render_steps(steps: list):
                plan_area.clear()
                pstate['steps'] = [
                    {'tool': s['tool'], 'args': s['args'], 'reason': s['reason'], 'status': '대기'}
                    for s in steps
                ]
                pstate['cards'] = []
                if not steps:
                    with plan_area:
                        ui.html('<div class="muted-text">실행할 도구 단계가 없습니다.</div>')
                    return
                with plan_area:
                    for i, s in enumerate(steps):
                        meta = AGENT_TOOLS[s['tool']]
                        args_txt = ', '.join(f'{k}={v}' for k, v in (s['args'] or {}).items()) or '인자 없음'
                        ro = ' · 읽기전용' if meta.get('read_only') else ''
                        with ui.element('div').style(
                            'border:1px solid var(--border);border-radius:var(--radius-lg);'
                            'padding:14px 16px;margin-bottom:10px;background:var(--bg);'
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

            def _show_clarification(questions: list):
                """LLM 이 추가 정보를 요청할 때 질문 입력 폼을 표시한다."""
                clarif_area.visible = True
                clarif_area.clear()
                pstate['clarif_inputs'] = []
                with clarif_area:
                    with ui.element('div').style(
                        'margin-top:14px;padding:14px 16px;border-radius:var(--radius-lg);'
                        'border:1px solid #f59e0b;background:#fffbeb;'
                    ):
                        ui.html(
                            '<div style="font-size:13px;font-weight:600;color:#92400e;margin-bottom:10px;">'
                            '에이전트가 정확한 계획 수립을 위해 추가 정보를 요청합니다</div>'
                        )
                        for q in questions:
                            ui.html(
                                f'<div style="font-size:12.5px;color:#78350f;margin:8px 0 4px;">'
                                f'{_html.escape(str(q))}</div>'
                            )
                            inp = ui.textarea().props('outlined autogrow rows=1 dense').classes('w-full')
                            inp.style('font-size:13px;')
                            pstate['clarif_inputs'].append((str(q), inp))
                    with ui.row().classes('gap-2 mt-2'):
                        submit_btn = ui.button('답변 제출 후 계획 수립').classes('btn-primary-mono btn-sm')
                        cancel_btn = ui.button('취소').classes('btn-mono btn-sm')

                    async def _submit_clarif():
                        answers = []
                        for q_text, inp_widget in pstate['clarif_inputs']:
                            ans = (inp_widget.value or '').strip()
                            if ans:
                                answers.append(f"Q: {q_text}\nA: {ans}")
                        if not answers:
                            ui.notify('답변을 입력하세요.', type='warning', position='top')
                            return
                        clarif_area.visible = False
                        clarif_area.clear()
                        enriched = (
                            pstate['original_command']
                            + '\n\n[추가 정보]\n'
                            + '\n'.join(answers)
                        )
                        await _invoke_planner(enriched)

                    def _cancel_clarif():
                        clarif_area.visible = False
                        clarif_area.clear()
                        plan_btn.props(remove='disable')

                    submit_btn.on('click', lambda _e: asyncio.create_task(_submit_clarif()))
                    cancel_btn.on('click', lambda _e: _cancel_clarif())

            async def _invoke_planner(command: str):
                plan_msg.content = '<div class="muted-text" style="margin-top:8px;">계획 수립 중…</div>'
                plan_area.clear()
                try:
                    model_id = state.get('selected_model_id')
                    result = await nicegui_run.io_bound(plan_command, command, create_llm, model_id)

                    if result.get('clarification_needed') and result.get('questions'):
                        plan_msg.content = ''
                        _show_clarification(result['questions'])
                        log.info("플래너 clarification 요청: %s", result['questions'])
                        return

                    msg = result.get('message', '')
                    plan_msg.content = (
                        '<div style="margin-top:8px;padding:8px 12px;border-radius:var(--radius);'
                        'background:var(--bg-elev);border:1px solid var(--border);font-size:13px;'
                        f'color:var(--text);">{_html.escape(msg)}</div>'
                    ) if msg else ''
                    _render_steps(result.get('steps', []))
                except Exception as e:
                    plan_msg.content = (
                        '<div style="margin-top:8px;color:#b91c1c;font-size:13px;">'
                        f'계획 수립 오류: {_html.escape(str(e))}</div>'
                    )
                    log.error("계획 수립 오류: %s", e)
                finally:
                    plan_btn.props(remove='disable')

            async def _make_plan():
                command = (cmd_input.value or '').strip()
                if not command:
                    ui.notify('명령을 입력하세요.', type='warning', position='top')
                    return
                pstate['original_command'] = command
                plan_btn.props(add='disable')
                clarif_area.visible = False
                clarif_area.clear()
                await _invoke_planner(command)

            plan_btn.on('click', lambda _e: asyncio.create_task(_make_plan()))
