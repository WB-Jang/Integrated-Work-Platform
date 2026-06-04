"""
Outlook 메일 분석 패널 UI — 모노크롬 디자인 시스템 이식판

좌측 필터 컬럼 + 우측 탭 (메일 목록 / LLM 분석 / 답장 초안).
"""
import datetime
import html as _html
import sys

from nicegui import ui, run as nicegui_run

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


def build_outlook_panel(config: dict, create_llm_fn):
    """Outlook 메일 분석 패널.

    호출하는 쪽에서 ``.panel`` 컨테이너 안에 배치해 주세요 (page-head 포함).

    Args:
        config: 앱 설정 dict
        create_llm_fn: create_llm(model_id=...) 함수 참조
    """
    state = {
        'emails': [],
        'selected_idx': None,
        'model_id': None,
    }

    outlook_ok = _is_outlook_available()

    # ── 헤더 ─────────────────────────────────────────────────────────────
    with ui.element('div').classes('page-head'):
        ui.html(
            '<div class="titles">'
            '<div class="page-title">메일 분석</div>'
            '<div class="page-subtitle">Outlook 수발신 내역을 조회하고 LLM으로 분석합니다.</div>'
            '</div>'
        )

    if not outlook_ok:
        ui.html(
            '<div style="margin:0 0 16px;padding:12px 14px;'
            'background:#fef3c7;border:1px solid #fde68a;border-radius:8px;'
            'color:#92400e;font-size:13px;line-height:1.55;">'
            '<b>⚠ 베타 환경 안내</b><br>'
            + _html.escape(_OUTLOOK_UNAVAILABLE_MSG) +
            '</div>'
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
                    reply_btn = ui.button('초안 생성').classes('btn-primary-mono mb-2')
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

    async def fetch_emails():
        try:
            start_date = datetime.date.fromisoformat((start_input.value or '').strip())
            end_date   = datetime.date.fromisoformat((end_input.value or '').strip())
        except ValueError:
            ui.notify('날짜 형식을 YYYY-MM-DD로 입력하세요.', type='warning', position='top')
            return

        _set_fetch_status('조회 중…')
        fetch_btn.props(add='disable')
        mail_list_container.clear()

        try:
            from outlook_agent import get_emails
            emails = await nicegui_run.io_bound(
                get_emails,
                start_date, end_date,
                (sender_input.value or '').strip(),
                (recip_input.value or '').strip(),
                att_check.value,
            )
            state['emails'] = emails
            _render_mail_list(emails)
            mail_count_label.content = (
                f'<div class="info-block">'
                f'<b>조회 결과: {len(emails)}건</b>'
                f'</div>'
            )
            _set_fetch_status(f'{len(emails)}건 조회 완료')
            log.info('메일 조회 완료: %d건', len(emails))
            ui.notify(f'{len(emails)}건 조회 완료', type='positive', position='top')
        except Exception as e:
            log.error('메일 조회 오류: %s', e)
            ui.notify(f'조회 오류: {e}', type='negative', position='top')
            _set_fetch_status('조회 실패')
        finally:
            fetch_btn.props(remove='disable')

    def _render_mail_list(emails: list[dict]):
        mail_list_container.clear()
        with mail_list_container:
            for i, e in enumerate(emails):
                direction = e.get('direction', '')
                tag_cls = 'tag solid' if direction == '발신' else 'tag'
                subj = _html.escape(e.get('subject') or '(제목 없음)')
                sender = _html.escape(e.get('sender') or '')
                recipients = _html.escape(', '.join(e.get('recipients', [])[:3]))
                date_str = e.get('date', '')

                card = ui.element('div').classes('mail-item')
                with card:
                    ui.html(
                        f'<div class="mail-subject">{subj}</div>'
                        f'<div class="mail-meta">'
                        f'<span class="{tag_cls}">{_html.escape(direction)}</span>'
                        f'<span>{sender} → {recipients}</span>'
                        f'<span style="margin-left:auto;color:var(--text-4);">'
                        f'{_html.escape(date_str)}</span>'
                        f'</div>'
                    )
                card.on('click', lambda _ev, idx=i: _select_mail(idx))

    def _select_mail(idx: int):
        state['selected_idx'] = idx
        e = state['emails'][idx]
        subj = _html.escape(e.get('subject') or '')
        sender = _html.escape(e.get('sender') or '')
        reply_mail_label.content = (
            '<div class="info-block">'
            f'<b>선택된 메일:</b> {subj}<br>'
            f'<span style="color:var(--text-3);font-size:11.5px;">'
            f'발신자: {sender} · {_html.escape(e.get("date",""))}</span>'
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
        analyze_btn.props(add='disable')
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
        except Exception as e:
            log.error('메일 분석 오류: %s', e)
            ui.notify(f'분석 오류: {e}', type='negative', position='top')
        finally:
            analysis_progress.visible = False
            analyze_btn.props(remove='disable')

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
            draft = await nicegui_run.io_bound(
                create_reply_draft, state['emails'][idx], inst, llm,
            )
            safe = _html.escape(draft).replace('\n', '<br>')
            reply_result.content = (
                '<div style="background:var(--bg);border:1px solid var(--border);'
                'border-radius:var(--radius-lg);padding:16px;font-size:13.5px;'
                'line-height:1.75;color:var(--text);">'
                f'{safe}</div>'
            )
            log.info('답장 초안 생성 완료')
            ui.notify('초안 생성 완료', type='positive', position='top')
        except Exception as e:
            log.error('답장 초안 오류: %s', e)
            ui.notify(f'초안 오류: {e}', type='negative', position='top')
        finally:
            reply_progress.visible = False
            reply_btn.props(remove='disable')

    if outlook_ok:
        fetch_btn.on_click(fetch_emails)
        analyze_btn.on_click(run_analysis)
        reply_btn.on_click(run_reply)
    else:
        # HF/Linux: 모든 액션을 안내 메시지로 대체
        fetch_btn.props(add='disable')
        analyze_btn.props(add='disable')
        reply_btn.props(add='disable')

        def _notify_unavailable(_e=None):
            ui.notify(_OUTLOOK_UNAVAILABLE_MSG, type='warning', position='top',
                      multi_line=True, timeout=6000)

        fetch_btn.on_click(_notify_unavailable)
        analyze_btn.on_click(_notify_unavailable)
        reply_btn.on_click(_notify_unavailable)
