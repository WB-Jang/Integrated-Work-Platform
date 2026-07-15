"""
관리자 전용 패널 — DB / 서버 관리 (모노크롬 디자인 시스템 이식판)

비밀번호 인증 후 임베딩·리랭크 서버를 제어하고, 법령 FAISS 벡터 DB를 구축합니다.
"""
import asyncio
import os
import sys
import subprocess
import threading
import uuid
import time
import html as _html

import requests as _requests
from nicegui import ui, run as nicegui_run, events

from logger import get_logger, set_current_user
from timer_utils import ClientBoundTimer

log = get_logger("admin")

ADMIN_PASSWORD = "911115"

# ── 서버 프로세스 상태 (모듈 수준 공유) ───────────────────────────────────
_server_procs: dict = {
    "embedding": None,
    "rerank": None,
}

_SERVER_META = {
    "embedding": {
        "script": "embedding_server.py",
        "port": 8081,
        "health_url": "http://127.0.0.1:8081/health",
        "label": "임베딩 서버",
    },
    "rerank": {
        "script": "rerank_server.py",
        "port": 8082,
        "health_url": "http://127.0.0.1:8082/health",
        "label": "리랭크 서버",
    },
}


# ── DB 구축 작업 상태 (모듈 전역) ─────────────────────────────────────────
# DB 구축은 수십 분~수 시간이 걸릴 수 있어, 클라이언트(브라우저) 작업으로 await 하면
# 그 사이 웹소켓이 끊겨 완료 알림/화면 갱신이 유실된다. 따라서 빌드는 백그라운드
# 스레드에서 돌리고 진행 상태를 이 전역 dict 에 기록한 뒤, 각 화면의 ui.timer 가
# 폴링하여 표시한다. 이렇게 하면 새로고침/재접속 후에도 진행·완료 상태가 보인다.
_BUILD: dict = {
    'active': False,       # 빌드 진행 중 여부
    'phase': 'idle',       # 'idle' | 'building' | 'done' | 'error'
    'law_name': '',
    'current': 0,
    'total': 1,
    'msg': '',
    'result': None,        # 성공 시 build_index 반환 dict
    'error': None,         # 실패 시 메시지
    'ui_handled': True,    # 완료/오류 후 1회성 후처리(알림·reload·정리) 완료 여부
}


def _build_progress_cb(current, total, msg):
    _BUILD['current'] = int(current)
    _BUILD['total'] = max(int(total), 1)
    _BUILD['msg'] = msg or ''


def _build_worker(paths, db_dir, law_name, chunk_size, overlap, append, use_llm, llm_config, user_initials="-"):
    """백그라운드 스레드에서 실제 DB 구축을 수행하고 _BUILD 에 결과를 기록한다."""
    set_current_user(user_initials)   # 스레드 컨텍스트에 사용자 설정
    from legal_db_builder import build_index
    try:
        _BUILD['phase'] = 'building'
        result = build_index(
            paths, db_dir, law_name, None, None,
            int(chunk_size), int(overlap), bool(append),
            bool(use_llm), llm_config, _build_progress_cb,
        )
        _BUILD['result'] = result
        _BUILD['phase'] = 'done'
        log.info("DB 구축 작업 완료(worker): %s — %s청크",
                 law_name, (result or {}).get('total_chunks'))
    except Exception as e:
        _BUILD['error'] = str(e)
        _BUILD['phase'] = 'error'
        log.error('DB 구축 오류(worker): %s', e)
    finally:
        # 스냅샷 임시 업로드 파일 정리 (UI 상태와 무관하게 항상 수행)
        for _p in paths:
            try:
                if os.path.exists(_p):
                    os.remove(_p)
            except Exception:
                pass
        _BUILD['active'] = False
        _BUILD['ui_handled'] = False   # 폴링 측에서 완료 후처리하도록 신호


def _is_server_up(health_url: str, timeout: float = 1.5) -> bool:
    try:
        r = _requests.get(health_url, timeout=timeout)
        return r.ok
    except Exception:
        return False


def _start_server(key: str) -> str:
    meta = _SERVER_META[key]
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), meta["script"])

    if _is_server_up(meta["health_url"]):
        return f"{meta['label']} 이미 실행 중"

    old_proc = _server_procs.get(key)
    if old_proc and old_proc.poll() is not None:
        _server_procs[key] = None

    if _server_procs[key] and _server_procs[key].poll() is None:
        return f"{meta['label']} 프로세스 실행 중 (모델 로딩 대기 중…)"

    try:
        proc = subprocess.Popen(
            [sys.executable, script_path, str(meta["port"])],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
        _server_procs[key] = proc
        for _ in range(5):
            time.sleep(1)
            if _is_server_up(meta["health_url"]):
                log.info("%s 즉시 시작 완료 (port=%d)", meta["label"], meta["port"])
                return f"{meta['label']} 시작 완료"
            if proc.poll() is not None:
                return f"{meta['label']} 프로세스가 즉시 종료됨 (로그 확인 필요)"
        return (
            f"{meta['label']} 프로세스 시작됨 — 모델 로딩 중 "
            f"(BGE-M3 최대 2분 소요). '상태 새로고침'으로 확인하세요."
        )
    except Exception as e:
        log.error("%s 시작 실패: %s", meta["label"], e)
        return f"{meta['label']} 시작 실패: {e}"


def _stop_server(key: str) -> str:
    meta = _SERVER_META[key]
    proc = _server_procs.get(key)
    if proc and proc.poll() is None:
        proc.terminate()
        _server_procs[key] = None
        log.info("%s 중지", meta["label"])
        return f"{meta['label']} 중지됨"
    return f"{meta['label']} 실행 중이 아님"


# ── 패널 빌더 ────────────────────────────────────────────────────────────

def build_admin_panel(config: dict, nav_ctx: dict = None):
    """관리자 패널 (비밀번호 인증 → DB / 서버 관리 + 메뉴 관리).

    호출하는 쪽에서 ``.panel`` 컨테이너 안에 배치해 주세요 (page-head 포함).
    nav_ctx: app.py 에서 전달하는 nav 요소 참조 dict (메뉴 관리에 사용).
    """
    db_cfg = config.get("legal_db", {})
    db_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        db_cfg.get("faiss_dir", "./legal_db").lstrip("./"),
    )

    session_state = {"authenticated": False}

    # ── 헤더 ─────────────────────────────────────────────────────────────
    with ui.element('div').classes('page-head'):
        ui.html(
            '<div class="titles">'
            '<div class="page-title">DB / 서버 관리</div>'
            '<div class="page-subtitle">법령 벡터 DB 구축, 임베딩·리랭크 서버, 메뉴 활성화를 관리합니다. '
            '(관리자 전용)</div>'
            '</div>'
        )

    # ── 비밀번호 게이트 ──────────────────────────────────────────────────
    gate = ui.element('div').style(
        'max-width:360px; margin:48px auto; padding:24px;'
        'background:var(--bg); border:1px solid var(--border);'
        'border-radius:var(--radius-lg);'
    )
    auth_area = ui.element('div').style(
        'flex:1;overflow-y:auto;min-height:0;'
    )
    auth_area.visible = False

    with auth_area:
        content = ui.element('div').style(
            'display:flex;flex-direction:row;gap:16px;align-items:stretch;padding:20px 24px;'
        )
        menu_section = ui.element('div').style('padding:0 32px 40px;')

    with gate:
        ui.html(
            '<div class="section-card-title">'
            '<span class="material-symbols-outlined">lock</span>관리자 인증'
            '</div>'
        )
        pw_input = ui.input(
            label='비밀번호', password=True, password_toggle_button=True,
        ).props('outlined dense').classes('w-full mb-2')
        pw_status = ui.html('<div class="muted-text" style="color:#b91c1c;"></div>')

        def _check_password():
            if pw_input.value == ADMIN_PASSWORD:
                session_state['authenticated'] = True
                gate.visible = False
                auth_area.visible = True
                _refresh_db_list()
                # _refresh_server_status는 async — sync 콜백에서는 task로 스케줄
                asyncio.create_task(_refresh_server_status())
            else:
                pw_status.content = (
                    '<div class="muted-text" style="color:#b91c1c;">'
                    '비밀번호가 올바르지 않습니다.</div>'
                )
                pw_input.value = ''

        pw_input.on('keydown.enter', lambda _: _check_password())
        ui.button('확인', on_click=_check_password).classes('btn-primary-mono w-full mt-3')

    # ── 관리자 콘텐츠 ───────────────────────────────────────────────────
    with content:
        # ── 좌측: 서버 + 법령 DB 목록 ───────────────────────────────────
        with ui.element('div').classes('filter-col'):

            # 서버 상태 카드
            with ui.element('div').classes('section-card'):
                ui.html(
                    '<div class="section-card-title">'
                    '<span class="material-symbols-outlined">dns</span>서버 상태'
                    '</div>'
                )
                server_status_html = ui.html('')

                def _check_statuses():
                    return [(meta['label'], _is_server_up(meta['health_url']))
                            for meta in _SERVER_META.values()]

                def _render_status(results):
                    rows = []
                    for label, up in results:
                        dot_cls = 'up' if up else 'down'
                        status_text = '실행 중' if up else '중지됨'
                        rows.append(
                            f'<div class="server-row">'
                            f'<span class="dot {dot_cls}"></span>'
                            f'<span>{_html.escape(label)}</span>'
                            f'<span style="margin-left:auto;color:var(--text-3);'
                            f'font-size:11.5px;">{status_text}</span>'
                            f'</div>'
                        )
                    server_status_html.content = ''.join(rows)

                async def _refresh_server_status():
                    results = await nicegui_run.io_bound(_check_statuses)
                    _render_status(results)

                _render_status([(m['label'], False) for m in _SERVER_META.values()])

                ui.html('<div class="divider"></div>')

                with ui.row().classes('gap-2 flex-wrap w-full'):
                    emb_btn   = ui.button('임베딩 시작').classes('btn-primary-mono btn-sm')
                    emb_stop  = ui.button('중지').classes('btn-primary-mono btn-sm')
                    rank_btn  = ui.button('리랭크 시작').classes('btn-primary-mono btn-sm')
                    rank_stop = ui.button('중지').classes('btn-primary-mono btn-sm')

                srv_status_label = ui.html(
                    '<div class="muted-text" style="margin-top:8px;"></div>'
                )

                async def _do_start(key: str):
                    srv_status_label.content = (
                        f'<div class="muted-text" style="margin-top:8px;">'
                        f'{_SERVER_META[key]["label"]} 프로세스 시작 중…</div>'
                    )
                    emb_btn.props(add='disable')
                    rank_btn.props(add='disable')
                    try:
                        msg = await nicegui_run.io_bound(_start_server, key)
                        srv_status_label.content = (
                            f'<div class="muted-text" style="margin-top:8px;">'
                            f'{_html.escape(msg)}</div>'
                        )
                    finally:
                        await _refresh_server_status()
                        emb_btn.props(remove='disable')
                        rank_btn.props(remove='disable')

                async def _do_stop(key: str):
                    msg = await nicegui_run.io_bound(_stop_server, key)
                    srv_status_label.content = (
                        f'<div class="muted-text" style="margin-top:8px;">'
                        f'{_html.escape(msg)}</div>'
                    )
                    await _refresh_server_status()

                emb_btn.on_click(lambda: _do_start('embedding'))
                emb_stop.on_click(lambda: _do_stop('embedding'))
                rank_btn.on_click(lambda: _do_start('rerank'))
                rank_stop.on_click(lambda: _do_stop('rerank'))

                # 클라이언트 연결 중에만 폴링 (disconnect 시 자동 취소·재연결 시 재개)
                ClientBoundTimer(10.0, _refresh_server_status)

                ui.button(
                    '상태 새로고침', on_click=_refresh_server_status,
                ).classes('btn-primary-mono btn-sm mt-2')

            # 법령 DB 목록
            with ui.element('div').classes('section-card'):
                ui.html(
                    '<div class="section-card-title">'
                    '<span class="material-symbols-outlined">database</span>'
                    '구축된 법령 DB'
                    '</div>'
                )
                law_list_html = ui.html('')

                def _refresh_db_list():
                    from legal_db_builder import list_law_indexes
                    laws = list_law_indexes(db_dir)
                    if not laws:
                        law_list_html.content = (
                            '<div class="muted-text">법령 DB 없음</div>'
                        )
                        return
                    rows = []
                    for law in laws:
                        rows.append(
                            f'<div style="display:flex;justify-content:space-between;'
                            f'align-items:center;padding:6px 0;border-bottom:1px solid '
                            f'var(--border);font-size:12.5px;">'
                            f'<b style="color:var(--text);">{_html.escape(law["law_name"])}</b>'
                            f'<span style="color:var(--text-3);">{law["doc_count"]}청크</span>'
                            f'</div>'
                        )
                    law_list_html.content = ''.join(rows)

                ui.button(
                    '목록 새로고침', on_click=_refresh_db_list,
                ).classes('btn-primary-mono btn-sm mt-2')

        # ── 우측: DB 구축 ───────────────────────────────────────────────
        with ui.element('div').classes('result-col'):
            with ui.element('div').classes('section-card'):
                ui.html(
                    '<div class="section-card-title">'
                    '<span class="material-symbols-outlined">database_upload</span>'
                    '법령 DB 구축'
                    '</div>'
                    '<div class="muted-text" style="margin-bottom:14px;">'
                    'DOCX · PDF · TXT · HWP 지원</div>'
                )

                with ui.row().classes('gap-3 mb-3 items-end w-full no-wrap'):
                    law_name_input = ui.input(
                        label='법령명 (필수)',
                        placeholder='예: privacy_law, labor_standard',
                    ).props('outlined dense').classes('flex-1')
                    ui.html(
                        '<div class="muted-text" style="padding-bottom:8px;flex:1;">'
                        '영문/숫자/언더바 권장<br>'
                        '{법령명}_idx.index 로 저장됩니다</div>'
                    )

                use_llm_chunk_check = ui.checkbox(
                    'LLM 의미 단위 청킹 사용 (상단 탭바에서 선택한 모델)', value=False,
                )
                ui.html(
                    '<div class="muted-text" style="margin-bottom:12px;">'
                    '체크 해제 시 문자 기반 단순 청킹</div>'
                )

                upload = ui.upload(
                    multiple=True, label='파일 선택', auto_upload=True,
                ).props('accept=.docx,.pdf,.txt,.hwp,.hwpx flat bordered').classes('w-full mb-3 upload-compact')

                uploaded_paths: list = []
                uploaded_label = ui.html(
                    '<div class="muted-text">업로드된 파일 없음</div>'
                )

                async def _on_upload(e: events.UploadEventArguments):
                    suffix = os.path.splitext(e.file.name)[1] or '.bin'
                    _db_build_dir = os.path.normpath(os.path.join(
                        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'uploads', 'db_build',
                    ))
                    os.makedirs(_db_build_dir, exist_ok=True)
                    tmp = os.path.join(_db_build_dir, f'{uuid.uuid4().hex}{suffix}')
                    await e.file.save(tmp)
                    uploaded_paths.append(tmp)
                    names = [os.path.basename(p) for p in uploaded_paths]
                    items = ''.join(
                        f'<div style="display:flex;align-items:center;gap:6px;'
                        f'font-size:12.5px;color:var(--text);">'
                        f'<span class="material-symbols-outlined" '
                        f'style="font-size:14px;color:var(--text-3);">description</span>'
                        f'{_html.escape(n)}</div>'
                        for n in names
                    )
                    uploaded_label.content = f'<div style="display:flex;flex-direction:column;gap:4px;">{items}</div>'

                upload.on_upload(_on_upload)

                with ui.row().classes('gap-3 mt-3 mb-3 items-end w-full no-wrap'):
                    chunk_size_input = ui.number(
                        '청크 크기(자)', value=800, min=200, max=3000, step=100,
                    ).props('outlined dense').style('width:160px;')
                    overlap_input = ui.number(
                        '중복(자)', value=100, min=0, max=500, step=50,
                    ).props('outlined dense').style('width:120px;')
                    append_check = ui.checkbox('기존 DB에 추가', value=False)

                with ui.row().classes('gap-2 mt-2'):
                    build_btn = ui.button('DB 구축').classes('btn-primary-mono')
                    clear_btn = ui.button('이 법령 DB 초기화').classes('btn-primary-mono')

                build_progress = ui.linear_progress(value=0).classes('w-full mt-2')
                build_progress.visible = False
                build_status = ui.html(
                    '<div class="muted-text" style="margin-top:6px;"></div>'
                )

                def _run_build():
                    if _BUILD['active']:
                        ui.notify('이미 DB 구축이 진행 중입니다. 완료 후 다시 시도하세요.',
                                  type='warning', position='top')
                        return
                    if not uploaded_paths:
                        ui.notify('업로드된 파일이 없습니다.', type='warning', position='top')
                        return
                    law_name = (law_name_input.value or '').strip().replace(' ', '_')
                    if not law_name:
                        ui.notify('법령명을 입력하세요.', type='warning', position='top')
                        return

                    use_llm = bool(use_llm_chunk_check.value)
                    # LLM 청킹 모델을 하드코딩하지 않고, 상단 탭바 모델 선택창에서
                    # 고른 모델·provider 로 수행하도록 config 에 주입한다.
                    llm_config = None
                    if use_llm:
                        llm_config = dict(config)
                        resolver = (nav_ctx or {}).get('resolve_chunk_model')
                        sel = ((nav_ctx or {}).get('app_state') or {}).get('selected_model_id')
                        if resolver and sel:
                            provider, real_model = resolver(sel)
                            llm_config['llm_chunk_model'] = real_model
                            llm_config['llm_chunk_provider'] = provider
                            log.info(
                                "LLM 청킹 모델=%s provider=%s (UI 선택: %s)",
                                real_model, provider, sel,
                            )

                    # 전역 상태 초기화 후 백그라운드 스레드로 빌드 시작
                    _BUILD.update({
                        'active': True, 'phase': 'building', 'law_name': law_name,
                        'current': 0, 'total': 1, 'msg': '준비 중…',
                        'result': None, 'error': None, 'ui_handled': True,
                    })
                    paths_snapshot = list(uploaded_paths)
                    _user = ((nav_ctx or {}).get('app_state') or {}).get('user_initials', '-')
                    threading.Thread(
                        target=_build_worker,
                        args=(paths_snapshot, db_dir, law_name,
                              int(chunk_size_input.value), int(overlap_input.value),
                              bool(append_check.value), use_llm, llm_config, _user),
                        daemon=True,
                    ).start()

                    # 업로드 목록은 스냅샷으로 넘겼으므로 UI 에서 즉시 비운다.
                    uploaded_paths.clear()
                    uploaded_label.content = '<div class="muted-text">업로드된 파일 없음</div>'
                    build_btn.props(add='disable')
                    build_progress.visible = True
                    build_progress.value = 0.02
                    build_status.content = (
                        f'<div class="muted-text" style="margin-top:6px;">'
                        f"'{_html.escape(law_name)}' DB 구축 시작… (창을 닫아도 계속 진행됩니다)</div>"
                    )

                # ── 진행 상태 폴링 타이머 ───────────────────────────────────
                # 빌드는 전역 _BUILD 에 기록되므로, 새로고침/재접속 후에도 이 타이머가
                # 현재 진행·완료 상태를 화면에 반영한다.
                # 패널이 소멸(다른 메뉴로 이동)되면 parent slot RuntimeError 가 발생하므로
                # 해당 시점에 타이머를 자동 취소한다.
                _poll_timer_ref: list = [None]

                def _poll_build():
                    try:
                        st = _BUILD
                        phase = st['phase']

                        if phase == 'building' or st['active']:
                            build_btn.props(add='disable')
                            build_progress.visible = True
                            frac = (st['current'] / st['total']) if st['total'] else 0
                            build_progress.value = max(0.02, min(frac, 0.99))
                            build_status.content = (
                                f'<div class="muted-text" style="margin-top:6px;">'
                                f"'{_html.escape(st['law_name'])}' 구축 중… "
                                f"{_html.escape(str(st['msg']))} "
                                f"({st['current']}/{st['total']})</div>"
                            )
                        elif phase == 'done':
                            r = st['result'] or {}
                            build_progress.value = 1.0
                            build_progress.visible = False
                            build_btn.props(remove='disable')
                            build_status.content = (
                                f'<div class="muted-text" style="margin-top:6px;color:var(--text);">'
                                f"완료: '{_html.escape(st['law_name'])}' — "
                                f'{r.get("total_chunks", 0)}청크 / dim={r.get("dim", 0)} / '
                                f'{r.get("total_files", 0)}파일</div>'
                            )
                        elif phase == 'error':
                            build_progress.visible = False
                            build_btn.props(remove='disable')
                            build_status.content = (
                                f'<div class="muted-text" style="margin-top:6px;color:#b91c1c;">'
                                f'오류: {_html.escape(str(st["error"]))}</div>'
                            )

                        # 완료/오류 직후 1회성 후처리 (알림·DB reload·목록 갱신)
                        if phase in ('done', 'error') and not st['ui_handled']:
                            st['ui_handled'] = True
                            if phase == 'done':
                                try:
                                    from legal_panel import reload_agent_db
                                    reload_agent_db(config)
                                except Exception as _re:
                                    log.warning('reload_agent_db 실패: %s', _re)
                                _refresh_db_list()
                                ui.notify(f"'{st['law_name']}' DB 구축 완료", type='positive', position='top')
                            else:
                                ui.notify(f"DB 구축 오류: {st['error']}", type='negative', position='top')

                    except RuntimeError:
                        # 패널 소멸 후 타이머가 발화한 경우 — 자동 취소
                        if _poll_timer_ref[0] is not None:
                            try:
                                _poll_timer_ref[0].cancel()
                            except Exception:
                                pass

                # 클라이언트 연결 중에만 폴링 (disconnect 시 자동 취소·재연결 시 재개)
                _poll_timer_ref[0] = ClientBoundTimer(0.8, _poll_build)

                def _confirm_clear():
                    law_name = (law_name_input.value or '').strip().replace(' ', '_')
                    if not law_name:
                        ui.notify('초기화할 법령명을 입력하세요.', type='warning', position='top')
                        return
                    with ui.dialog() as dlg, ui.card():
                        ui.html(
                            f'<div style="font-size:14px;font-weight:600;margin-bottom:8px;">'
                            f'"{_html.escape(law_name)}" DB를 초기화하시겠습니까?</div>'
                            f'<div class="muted-text" style="margin-bottom:12px;">'
                            f'해당 법령의 청크와 인덱스가 삭제됩니다.</div>'
                        )
                        with ui.row().classes('gap-2 justify-end w-full'):
                            ui.button('취소', on_click=dlg.close).classes('btn-primary-mono')

                            def _do_clear(ln=law_name):
                                from legal_db_builder import clear_index
                                from legal_panel import reload_agent_db
                                clear_index(db_dir, law_name=ln)
                                reload_agent_db(config)
                                _refresh_db_list()
                                dlg.close()
                                ui.notify(f"'{ln}' DB 초기화 완료", type='warning', position='top')

                            ui.button('초기화', on_click=_do_clear).classes('btn-primary-mono')
                    dlg.open()

                build_btn.on_click(_run_build)
                clear_btn.on_click(_confirm_clear)

    # ── 메뉴 관리 섹션 ────────────────────────────────────────────────────
    import menu_state as _ms

    _ITEM_META: dict[str, tuple[str, str]] = {
        'analysis':       ('description',    '문서 오타·논리·Business Tone&Manner'),
        'summary':        ('summarize',      '계층적 Map-Reduce 요약'),
        'qa':             ('forum',          '업로드 문서 기반 RAG 질의응답'),
        'legal':          ('gavel',          '법령 FAISS 벡터 DB 검색'),
        'convert':        ('picture_as_pdf', 'Word/PPT → PDF 일괄 변환'),
        'reporting':      ('assignment',     'AI 자동 보고서 작성'),
        'outlook':        ('mail',           'Outlook 연동 메일 분석'),
        'regulatory':     ('monitoring',     '금감원·한은·금융위 동향'),
        'rates':          ('trending_up',    'kofiabond 금리(CD91·채권시가평가) 조회'),
        'risk_dashboard': ('monitor_heart',  'FSS Open API 리스크 현황'),
        'risk_indicator': ('insights',       '은행 재무 건전성 지표 모니터링'),
    }
    _GROUP_LABELS: dict[str, str] = {
        'llm':       'LLM 기능',
        'business':  '업무',
        'dashboard': 'DashBoard',
    }
    _BASE_CARD = (
        'display:flex;align-items:center;gap:10px;'
        'padding:12px 14px;border:1px solid var(--border);'
        'border-radius:var(--radius);background:var(--bg-elev);'
        'transition:opacity .2s;'
    )
    # 카드·스위치 위젯 참조 (전체 일괄 업데이트에 사용)
    _menu_cards: dict = {}
    _menu_switches: dict = {}

    def _update_group_visibility(changed_key: str):
        """변경된 키가 속한 그룹의 헤더/토글/서브 가시성을 갱신합니다."""
        if not nav_ctx:
            return
        ng = nav_ctx.get('nav_groups', {})
        for gk, gi in _ms.MENU_GROUPS.items():
            if changed_key in gi:
                any_on = any(_ms.is_enabled(ki) for ki in gi)
                for ge in ng.get(gk, {}).values():
                    ge.visible = any_on
                break

    def _apply_bulk(enabled: bool):
        """모든 메뉴를 일괄 활성화/비활성화합니다."""
        for k in _ms.MENU_ITEMS:
            _ms.set_enabled(k, enabled)
            if k in _menu_cards:
                _menu_cards[k].style(_BASE_CARD + ('' if enabled else 'opacity:0.45;'))
            if k in _menu_switches:
                _menu_switches[k].value = enabled
            if nav_ctx and k in nav_ctx.get('nav_elements', {}):
                nav_ctx['nav_elements'][k].visible = enabled
        for gk in _ms.MENU_GROUPS:
            for ge in (nav_ctx.get('nav_groups', {}).get(gk, {}).values() if nav_ctx else []):
                ge.visible = enabled
        if not enabled and nav_ctx:
            st_ref = nav_ctx.get('switch_tab_ref')
            app_st = nav_ctx.get('app_state', {})
            if app_st.get('current_tab') not in ('home', 'admin') and st_ref and st_ref[0]:
                st_ref[0]('home')
        label = '활성화' if enabled else '비활성화'
        ui.notify(f'모든 메뉴 {label}됨', type='positive' if enabled else 'warning', position='top')

    with menu_section:
        ui.html('<div class="divider" style="margin:0 0 28px;"></div>')

        # 섹션 헤더
        ui.html(
            '<div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">'
            '<span class="material-symbols-outlined" '
            'style="font-size:20px;color:var(--text-2);">settings_applications</span>'
            '<div>'
            '<div style="font-size:15px;font-weight:700;color:var(--text);">메뉴 관리</div>'
            '<div style="font-size:12px;color:var(--text-3);margin-top:2px;">'
            '기능을 비활성화하면 상단 탭바에서 즉시 숨겨집니다. 변경 사항은 서버 재시작 후에도 유지됩니다.'
            '</div>'
            '</div>'
            '</div>'
        )
        ui.html('<div class="divider" style="margin:16px 0 20px;"></div>')

        # 전체 ON/OFF 버튼
        with ui.row().classes('gap-2 mb-4'):
            ui.button('전체 활성화', on_click=lambda: _apply_bulk(True)).classes('btn-primary-mono btn-sm')
            ui.button('전체 비활성화', on_click=lambda: _apply_bulk(False)).classes('btn-primary-mono btn-sm')

        # 그룹별 토글 카드
        for g_key, g_label in _GROUP_LABELS.items():
            g_items = _ms.MENU_GROUPS[g_key]

            ui.html(
                f'<div class="muted-label" style="margin-bottom:10px;">'
                f'{_html.escape(g_label)}</div>'
            )

            with ui.element('div').style(
                'display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));'
                'gap:8px;margin-bottom:24px;'
            ):
                for item_key in g_items:
                    item_label = _ms.MENU_ITEMS[item_key]
                    item_icon, item_desc = _ITEM_META[item_key]
                    item_on = _ms.is_enabled(item_key)

                    card = ui.element('div').style(
                        _BASE_CARD + ('' if item_on else 'opacity:0.45;')
                    )
                    _menu_cards[item_key] = card

                    def _make_toggle(k, c):
                        _lbl = _ms.MENU_ITEMS[k]

                        def _on_change(e):
                            enabled = bool(e.value)
                            _ms.set_enabled(k, enabled)
                            c.style(_BASE_CARD + ('' if enabled else 'opacity:0.45;'))

                            if nav_ctx:
                                ne = nav_ctx.get('nav_elements', {})
                                if k in ne:
                                    ne[k].visible = enabled
                                _update_group_visibility(k)

                                if not enabled:
                                    app_st = nav_ctx.get('app_state', {})
                                    if app_st.get('current_tab') == k:
                                        st_ref = nav_ctx.get('switch_tab_ref')
                                        if st_ref and st_ref[0]:
                                            st_ref[0]('home')

                            ui.notify(
                                f'{_lbl} {"활성화" if enabled else "비활성화"}됨',
                                type='positive' if enabled else 'warning',
                                position='top',
                            )

                        return _on_change

                    with card:
                        ui.html(
                            f'<span class="material-symbols-outlined" '
                            f'style="font-size:18px;color:var(--text-3);flex-shrink:0;">'
                            f'{item_icon}</span>'
                            f'<div style="flex:1;min-width:0;">'
                            f'<div style="font-size:13px;font-weight:600;color:var(--text);">'
                            f'{_html.escape(item_label)}</div>'
                            f'<div style="font-size:11px;color:var(--text-4);margin-top:2px;">'
                            f'{_html.escape(item_desc)}</div>'
                            f'</div>'
                        )
                        sw = ui.switch(value=item_on).props('dense')
                        sw.on_value_change(_make_toggle(item_key, card))
                        _menu_switches[item_key] = sw
