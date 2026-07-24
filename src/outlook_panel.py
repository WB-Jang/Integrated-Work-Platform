"""
Outlook 메일 분석 패널 UI — 모노크롬 디자인 시스템 이식판

좌측 필터 컬럼 + 우측 탭 (메일 목록 / LLM 분석 / 답장 초안).
"""
import asyncio
import datetime
import html as _html
import json as _json
import sys

from nicegui import ui, run as nicegui_run
from nicegui import context as _ng_context

from logger import get_logger

log = get_logger("outlook_panel")


def _is_outlook_available() -> bool:
    """로컬 Outlook(COM) 사용 가능 여부. Linux/HF Spaces 에서는 항상 False."""
    if sys.platform != 'win32':
        return False
    try:
        import winreg
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, 'Outlook.Application')
        return True
    except Exception:
        return False


_OUTLOOK_UNAVAILABLE_MSG = (
    '본 환경(HF Spaces / Linux)에서는 로컬 Outlook 연동을 사용할 수 없습니다. '
    '메뉴와 UI는 기능 미리보기 용도로 노출되며, 메일 조회·분석·답장 생성은 '
    '로컬 데스크톱(Windows + Outlook 설치) 환경에서만 동작합니다.'
)


def build_outlook_panel(config: dict, create_llm_fn, persona_block: str = ""):
    """Outlook 메일 분석 패널.

    호출하는 쪽에서 ``.panel`` 컨테이너 안에 배치해 주세요 (page-head 포함).

    Args:
        config: 앱 설정 dict
        create_llm_fn: create_llm(model_id=...) 함수 참조
        persona_block: 접속 IP 로 확인된 유저의 COSTAR 페르소나
            (빈 문자열 = 미적용. 답장 초안 생성 시 작성자 스타일로 반영)
    """
    state = {
        'emails': [],
        'selected_idx': None,
        'model_id': None,
        'persona_block': persona_block or '',
    }

    # 서버 배포 구조: 사용자 PC의 Outlook은 각 PC에서 실행되는 로컬 브릿지를 통해
    # 접근한다. 브라우저(사용자 PC)가 127.0.0.1 브릿지를 호출 → 본인 Outlook 조회.
    bridge_url = (config.get('outlook_bridge_url') or 'http://127.0.0.1:8899').rstrip('/')
    bridge_token = config.get('outlook_bridge_token', '') or ''

    # 백그라운드 태스크(asyncio.create_task)로 실행하면 NiceGUI 슬롯/클라이언트
    # 컨텍스트가 유실되어 ui.run_javascript/ui.notify 가 "slot stack is empty" 로
    # 실패한다. 패널 빌드 시점의 client 를 캡처해 태스크 내부에서 with 로 복원한다.
    _client = _ng_context.client

    def _spawn(coro):
        async def _wrapped():
            with _client:
                await coro
        return asyncio.create_task(_wrapped())

    # ── 헤더 ─────────────────────────────────────────────────────────────
    with ui.element('div').classes('page-head'):
        ui.html(
            '<div class="titles">'
            '<div class="page-title">메일 분석</div>'
            '<div class="page-subtitle">Outlook 수발신 내역을 조회하고 LLM으로 분석합니다.</div>'
            '</div>'
        )

    # 브릿지 연결 상태 배지 (사용자 PC의 로컬 브릿지 실행 여부를 표시)
    bridge_status = ui.html('')

    def _set_bridge_status(html_inner: str):
        bridge_status.content = (
            '<div style="margin:0 0 16px;padding:10px 14px;border-radius:8px;'
            'font-size:12.5px;line-height:1.55;border:1px solid var(--border);'
            'background:var(--bg);">' + html_inner + '</div>'
        )

    _set_bridge_status(
        '<span style="color:var(--text-4);">Outlook 브릿지 연결 확인 중…</span>'
    )

    # ── 본문 — 좌측 필터 / 우측 탭 ──────────────────────────────────────
    with ui.element('div').classes('filter-result-row'):

        # ── 좌측: 조회 조건 ──────────────────────────────────────────────
        with ui.element('div').classes('filter-col'):
            ui.html(
                '<div class="section-card-title">'
                '<span class="material-symbols-outlined">tune</span>조회 조건'
                '</div>'
            )

            today = datetime.date.today()
            default_start = (today - datetime.timedelta(days=30)).strftime('%Y-%m-%d')
            default_end = today.strftime('%Y-%m-%d')

            start_input = ui.input('시작일 (YYYY-MM-DD)', value=default_start).props('outlined dense').classes('w-full mb-2')
            end_input   = ui.input('종료일 (YYYY-MM-DD)', value=default_end).props('outlined dense').classes('w-full mb-3')

            ui.html('<div class="muted-label">필터 (빈칸 = 전체)</div>')
            sender_input = ui.input('발신자 이름/이메일').props('outlined dense').classes('w-full mb-2')
            recip_input  = ui.input('수신자 이름/이메일').props('outlined dense').classes('w-full mb-3')

            att_check = ui.checkbox('첨부파일 텍스트 추출 (DOCX/PDF)').classes('mb-3')

            fetch_btn = ui.button('메일 조회').classes('btn-primary-mono w-full')
            fetch_status = ui.html(
                '<div class="muted-text" style="margin-top:8px;"></div>'
            )

        # ── 우측: 탭 ─────────────────────────────────────────────────────
        with ui.element('div').classes('result-col'):
            with ui.tabs().classes('w-full') as tabs:
                ui.tab('list',     label='메일 목록')
                ui.tab('analysis', label='LLM 분석')
                ui.tab('reply',    label='답장 초안')

            with ui.tab_panels(tabs, value='list').classes('w-full').style('flex:1; overflow:auto;'):

                # ── 탭 1: 메일 목록 ──────────────────────────────────────
                with ui.tab_panel('list'):
                    mail_count_label = ui.html(
                        '<div class="muted-text">조회 조건을 설정하고 메일 조회를 클릭하세요.</div>'
                    )
                    mail_list_container = ui.column().classes('w-full mt-2')

                # ── 탭 2: LLM 분석 ───────────────────────────────────────
                with ui.tab_panel('analysis'):
                    analysis_task_input = ui.textarea(
                        label='분석 요청',
                        placeholder='예: 지난 한 달간 프로젝트 A 관련 진행사항 정리\n     이슈 사항과 담당자 추출',
                    ).props('outlined autogrow rows=3').classes('w-full mb-2')

                    analyze_btn = ui.button('LLM 분석 시작').classes('btn-primary-mono mb-2')
                    analysis_progress = ui.linear_progress().props('indeterminate').classes('w-full')
                    analysis_progress.visible = False

                    analysis_result = ui.html(
                        '<div class="muted-text" style="padding:12px 0;">'
                        '분석 결과가 여기에 표시됩니다.</div>'
                    )

                # ── 탭 3: 답장 초안 ──────────────────────────────────────
                with ui.tab_panel('reply'):
                    reply_mail_label = ui.html(
                        '<div class="muted-text">메일 목록에서 답장할 메일을 선택하세요.</div>'
                    )
                    reply_inst_input = ui.textarea(
                        label='답장 지시사항',
                        placeholder='예: 수신 확인 및 다음 주 미팅 일정 조율을 요청하는 답장',
                    ).props('outlined autogrow rows=3').classes('w-full mt-2 mb-2')
                    with ui.row().classes('gap-2 mb-2 items-center'):
                        reply_btn = ui.button('초안 생성').classes('btn-primary-mono')
                        open_draft_btn = ui.button('Outlook에 초안 열기').classes('btn-primary-mono')
                        open_draft_btn.visible = False
                    reply_progress = ui.linear_progress().props('indeterminate').classes('w-full')
                    reply_progress.visible = False
                    reply_result = ui.html(
                        '<div class="muted-text" style="padding:12px 0;">'
                        '초안이 여기에 표시됩니다.</div>'
                    )

    # ─── 이벤트 핸들러 ──────────────────────────────────────────────────

    def _set_fetch_status(text: str):
        fetch_status.content = (
            f'<div class="muted-text" style="margin-top:8px;">'
            f'{_html.escape(text)}</div>'
        )

    # 실행 중 취소용 컨트롤
    _fetch_ctl = {'task': None, 'busy': False}
    _analyze_ctl = {'task': None, 'busy': False}

    # ── 로컬 브릿지 호출 (브라우저=사용자 PC 에서 fetch 실행) ────────────────
    async def _bridge_fetch(path: str, params: dict, timeout: float = 180):
        """사용자 브라우저에서 127.0.0.1 브릿지로 GET 요청. dict 반환(오류 시 {'error':...})."""
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
        if not isinstance(res, dict):
            return {'error': '브릿지 응답 없음 (브릿지 실행/연결 확인)'}
        return res

    async def _bridge_post(path: str, payload: dict, timeout: float = 30):
        """브라우저에서 127.0.0.1 브릿지로 POST(JSON). dict 반환."""
        url = bridge_url + path + (f'?token={bridge_token}' if bridge_token else '')
        js = (
            "try {"
            f"  const r = await fetch({_json.dumps(url)}, {{"
            "     method: 'POST', headers: {'Content-Type': 'application/json'},"
            f"     body: JSON.stringify({_json.dumps(payload)}) }});"
            "  if (!r.ok) return {ok:false, error: 'HTTP ' + r.status};"
            "  return await r.json();"
            "} catch (e) { return {ok:false, error: '브릿지 연결 실패: ' + String(e)}; }"
        )
        res = await ui.run_javascript(js, timeout=timeout)
        if not isinstance(res, dict):
            return {'ok': False, 'error': '브릿지 응답 없음'}
        return res

    async def _check_bridge():
        try:
            res = await _bridge_fetch('/health', {}, timeout=8)
        except Exception as e:
            res = {'error': str(e)}
        if res.get('ok'):
            mbox = _html.escape(str(res.get('mailbox') or '(메일함 확인 불가)'))
            _set_bridge_status(
                '<span style="color:var(--success);font-weight:600;">● Outlook 브릿지 연결됨</span>'
                f' <span style="color:var(--text-4);">— 메일함: {mbox}</span>'
            )
            return True
        _set_bridge_status(
            '<span style="color:var(--warning);font-weight:600;">● Outlook 브릿지 미연결</span> '
            '<span style="color:var(--text-3);">— 사용자 PC에서 <b>outlook_bridge.exe</b> 실행 후 '
            '“메일 조회”를 눌러주세요. (Outlook 로그인 필요)</span>'
        )
        return False

    async def fetch_emails():
        try:
            start_date = datetime.date.fromisoformat((start_input.value or '').strip())
            end_date   = datetime.date.fromisoformat((end_input.value or '').strip())
        except ValueError:
            ui.notify('날짜 형식을 YYYY-MM-DD로 입력하세요.', type='warning', position='top')
            return

        _set_fetch_status('조회 중… (사용자 PC Outlook)')
        _fetch_ctl['busy'] = True
        _fetch_ctl['task'] = asyncio.current_task()
        fetch_btn.text = '중지'
        fetch_btn.classes(add='is-stop')
        mail_list_container.clear()

        try:
            res = await _bridge_fetch('/emails', {
                'start': start_date.isoformat(),
                'end': end_date.isoformat(),
                'sender': (sender_input.value or '').strip(),
                'recipient': (recip_input.value or '').strip(),
                'attachments': '1' if att_check.value else '0',
            })
            if res.get('error'):
                await _check_bridge()
                raise RuntimeError(res['error'])
            emails = res.get('emails') or []
            state['emails'] = emails
            _render_mail_list(emails)
            mail_count_label.content = (
                f'<div class="info-block">'
                f'<b>조회 결과: {len(emails)}건</b>'
                f'</div>'
            )
            _set_fetch_status(f'{len(emails)}건 조회 완료')
            log.info('메일 조회 완료(브릿지): %d건', len(emails))
            ui.notify(f'{len(emails)}건 조회 완료', type='positive', position='top')
            await _check_bridge()
        except asyncio.CancelledError:
            log.info('메일 조회 취소됨')
            _set_fetch_status('조회 중지됨')
            ui.notify('메일 조회를 중지했습니다.', type='warning', position='top')
        except Exception as e:
            log.error('메일 조회 오류: %s', e)
            ui.notify(f'조회 오류: {e}', type='negative', position='top')
            _set_fetch_status('조회 실패')
        finally:
            _fetch_ctl['busy'] = False
            _fetch_ctl['task'] = None
            fetch_btn.text = '메일 조회'
            fetch_btn.classes(remove='is-stop')

    def _render_mail_list(emails: list[dict]):
        mail_list_container.clear()
        with mail_list_container:
            for i, e in enumerate(emails):
                direction = e.get('direction', '')
                tag_cls = 'tag solid' if direction == '발신' else 'tag'
                subj = _html.escape(e.get('subject') or '(제목 없음)')
                sender = _html.escape(e.get('sender') or '')
                to_list = e.get('to') or e.get('recipients') or []
                cc_list = e.get('cc') or []
                to_str = _html.escape(', '.join(to_list[:3]))
                date_str = e.get('date', '')
                reply_status = e.get('reply_status') or ''

                # 회신/전달 여부 뱃지 (Outlook PR_LAST_VERB_EXECUTED 기반)
                reply_chip = ''
                if reply_status:
                    reply_chip = (
                        f'<span class="tag" style="color:#a78bfa;border-color:rgba(167,139,250,.4);" '
                        f'title="{_html.escape(reply_status)}">↩ '
                        f'{_html.escape(reply_status.split(" ")[0])}</span>'
                    )
                cc_line = ''
                if cc_list:
                    cc_line = (
                        f'<span style="color:var(--text-4);">참조: '
                        f'{_html.escape(", ".join(cc_list[:3]))}'
                        f'{" 외" if len(cc_list) > 3 else ""}</span>'
                    )

                card = ui.element('div').classes('mail-item')
                card.props('title="클릭하면 Outlook에서 메일이 열립니다"')
                with card:
                    ui.html(
                        f'<div class="mail-subject">{subj}</div>'
                        f'<div class="mail-meta">'
                        f'<span class="{tag_cls}">{_html.escape(direction)}</span>'
                        + reply_chip +
                        f'<span>{sender} → {to_str}</span>'
                        + cc_line +
                        f'<span style="margin-left:auto;color:var(--text-4);">'
                        f'{_html.escape(date_str)}</span>'
                        f'</div>'
                    )
                card.on('click', lambda _ev, idx=i: asyncio.create_task(_select_mail(idx)))

    async def _select_mail(idx: int):
        state['selected_idx'] = idx
        e = state['emails'][idx]
        subj = _html.escape(e.get('subject') or '')
        sender = _html.escape(e.get('sender') or '')
        to_str = _html.escape(', '.join((e.get('to') or e.get('recipients') or [])[:5]))
        cc_str = _html.escape(', '.join((e.get('cc') or [])[:5]))
        reply_status = e.get('reply_status') or '회신 이력 없음'
        reply_mail_label.content = (
            '<div class="info-block">'
            f'<b>선택된 메일:</b> {subj}<br>'
            f'<span style="color:var(--text-3);font-size:11.5px;">'
            f'발신자: {sender} · {_html.escape(e.get("date",""))}<br>'
            f'수신자(To): {to_str}'
            + (f'<br>참조(CC): {cc_str}' if cc_str else '')
            + f'<br>회신 여부: {_html.escape(reply_status)}'
            '</span>'
            '</div>'
        )
        # 시각적으로 선택 표시
        for i, item in enumerate(mail_list_container):
            try:
                if i == idx:
                    item.classes(add='selected')
                else:
                    item.classes(remove='selected')
            except Exception:
                pass

        # 클릭한 메일을 로컬 Outlook 창에서 바로 열기
        entry_id = e.get('entry_id') or ''
        if entry_id:
            try:
                from outlook_agent import open_email
                ok = await nicegui_run.io_bound(
                    open_email, entry_id, e.get('store_id') or '',
                )
                if ok:
                    ui.notify(
                        f'Outlook에서 열기: {(e.get("subject") or "")[:40]}',
                        position='top',
                    )
                else:
                    ui.notify('메일을 여는 데 실패했습니다 (Outlook 연결 확인).',
                              type='warning', position='top')
            except Exception as exc:
                log.warning('메일 열기 오류: %s', exc)
                ui.notify(f'메일 열기 오류: {exc}', type='warning', position='top')
        else:
            ui.notify(f'선택: {(e.get("subject") or "")[:40]}', position='top')

    async def run_analysis():
        if not state['emails']:
            ui.notify('먼저 메일을 조회하세요.', type='warning', position='top')
            return
        task = (analysis_task_input.value or '').strip()
        if not task:
            ui.notify('분석 요청 내용을 입력하세요.', type='warning', position='top')
            return

        analysis_progress.visible = True
        _analyze_ctl['busy'] = True
        _analyze_ctl['task'] = asyncio.current_task()
        analyze_btn.text = '중지'
        analyze_btn.classes(add='is-stop')
        analysis_result.content = (
            '<div class="muted-text" style="padding:12px 0;">분석 중…</div>'
        )

        try:
            llm = create_llm_fn(model_id=state.get('model_id'))
            from outlook_agent import analyze_emails
            result = await nicegui_run.io_bound(
                analyze_emails, state['emails'], task, llm,
            )
            safe = _html.escape(result).replace('\n', '<br>')
            analysis_result.content = (
                '<div style="background:var(--bg);border:1px solid var(--border);'
                'border-radius:var(--radius-lg);padding:16px;font-size:13.5px;'
                'line-height:1.75;color:var(--text);">'
                f'{safe}</div>'
            )
            log.info('메일 분석 완료 (task: %s...)', task[:40])
            ui.notify('분석 완료', type='positive', position='top')
        except asyncio.CancelledError:
            log.info('메일 분석 취소됨')
            analysis_result.content = (
                '<div class="muted-text" style="color:var(--warning);padding:12px 0;">분석을 중지했습니다.</div>'
            )
            ui.notify('분석을 중지했습니다.', type='warning', position='top')
        except Exception as e:
            log.error('메일 분석 오류: %s', e)
            ui.notify(f'분석 오류: {e}', type='negative', position='top')
        finally:
            analysis_progress.visible = False
            _analyze_ctl['busy'] = False
            _analyze_ctl['task'] = None
            analyze_btn.text = 'LLM 분석 시작'
            analyze_btn.classes(remove='is-stop')

    async def run_reply():
        idx = state.get('selected_idx')
        if idx is None:
            ui.notify('답장할 메일을 선택하세요.', type='warning', position='top')
            return
        inst = (reply_inst_input.value or '').strip()
        if not inst:
            ui.notify('답장 지시사항을 입력하세요.', type='warning', position='top')
            return

        reply_progress.visible = True
        reply_btn.props(add='disable')
        reply_result.content = (
            '<div class="muted-text" style="padding:12px 0;">초안 생성 중…</div>'
        )

        try:
            llm = create_llm_fn(model_id=state.get('model_id'))
            from outlook_agent import create_reply_draft
            # 유저별 페르소나(COSTAR) — 접속 IP 로 확인된 본인 것만 전달됨
            draft = await nicegui_run.io_bound(
                create_reply_draft, state['emails'][idx], inst, llm,
                state.get('persona_block', ''),
            )
            safe = _html.escape(draft).replace('\n', '<br>')
            reply_result.content = (
                '<div style="background:var(--bg);border:1px solid var(--border);'
                'border-radius:var(--radius-lg);padding:16px;font-size:13.5px;'
                'line-height:1.75;color:var(--text);">'
                f'{safe}</div>'
            )
            state['last_draft'] = draft
            state['last_draft_idx'] = idx
            open_draft_btn.visible = True   # 본인 Outlook 에 초안 열기 가능
            log.info('답장 초안 생성 완료')
            ui.notify('초안 생성 완료', type='positive', position='top')
        except Exception as e:
            log.error('답장 초안 오류: %s', e)
            ui.notify(f'초안 오류: {e}', type='negative', position='top')
        finally:
            reply_progress.visible = False
            reply_btn.props(remove='disable')

    async def open_draft_in_outlook():
        """생성된 초안을 사용자 PC Outlook 에 회신 초안 창으로 연다(브릿지 POST)."""
        draft = state.get('last_draft')
        idx = state.get('last_draft_idx')
        if not draft or idx is None:
            ui.notify('먼저 초안을 생성하세요.', type='warning', position='top')
            return
        email = state['emails'][idx]
        open_draft_btn.props(add='disable')
        try:
            res = await _bridge_post('/reply-draft', {
                'entry_id': email.get('entry_id', ''),
                'store_id': email.get('store_id', ''),
                'body': draft,
                'reply_all': False,
            })
            if res.get('ok'):
                ui.notify('Outlook에 회신 초안을 열었습니다.', type='positive', position='top')
            else:
                ui.notify(f"초안 열기 실패: {res.get('error', '브릿지 확인')}",
                          type='negative', position='top')
        finally:
            open_draft_btn.props(remove='disable')

    def _on_fetch_click():
        if _fetch_ctl['busy']:
            if _fetch_ctl['task'] is not None:
                _fetch_ctl['task'].cancel()
            return
        _spawn(fetch_emails())

    def _on_analyze_click():
        if _analyze_ctl['busy']:
            if _analyze_ctl['task'] is not None:
                _analyze_ctl['task'].cancel()
            return
        _spawn(run_analysis())

    # 조회는 사용자 PC 로컬 브릿지를 통하므로 서버 플랫폼과 무관하게 항상 활성화.
    # (분석/초안 생성은 서버측 LLM 이 조회된 메일 dict 로 수행)
    fetch_btn.on_click(_on_fetch_click)
    analyze_btn.on_click(_on_analyze_click)
    reply_btn.on_click(run_reply)
    open_draft_btn.on_click(open_draft_in_outlook)

    # 패널 로드 직후 브릿지 연결 상태 1회 확인 (클라이언트 연결 필요 → 타이머로 지연)
    ui.timer(0.6, lambda: _spawn(_check_bridge()), once=True)
