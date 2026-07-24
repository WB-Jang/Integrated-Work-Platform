"""
규제 동향 모니터링 패널 UI — 모노크롬 디자인 시스템 이식판

좌측 필터(모드 토글: 기관별 / 연합뉴스) · 우측 결과 리스트 + 메일 발송.
"""
import asyncio
import html as _html
import re
import time as _time

from nicegui import ui, run as nicegui_run, app as nicegui_app
from nicegui import context as _ng_context

from logger import get_logger, set_current_user
import activity_log
from outlook_panel import _is_outlook_available, _OUTLOOK_UNAVAILABLE_MSG
from ui_styles import progress_block_html, step_list_html, elapsed_ticker_script

log = get_logger("regulatory_panel")

_YNA_STEPS = ['키워드 추출', '기사 수집', '유사도 재정렬', '기사 요약', '클러스터링', '통합 답변']

# YYYYMMDD, YYYY.MM.DD, YYYY/MM/DD 등을 YYYY-MM-DD 로 정규화
_DATE_DIGITS_RE = re.compile(r'^\s*(\d{4})[.\-/]?(\d{2})[.\-/]?(\d{2})\s*$')


def _normalize_date(raw: str) -> tuple[str, bool]:
    """입력 문자열을 YYYY-MM-DD 로 정규화. (정규화된 문자열, 유효 여부) 반환.
    빈 문자열은 유효한 것으로 취급(선택 입력이므로)."""
    raw = (raw or '').strip()
    if not raw:
        return '', True
    m = _DATE_DIGITS_RE.match(raw)
    if not m:
        return raw, False
    y, mo, d = m.groups()
    try:
        import datetime as _dt
        _dt.date(int(y), int(mo), int(d))
    except ValueError:
        return raw, False
    return f'{y}-{mo}-{d}', True


def _apply_current_user() -> None:
    try:
        v = (nicegui_app.storage.user.get('initials') or '-').strip().upper()
    except Exception:
        v = '-'
    set_current_user(v or '-')

# 출처별 태그 라벨 (색상 대신 글자만으로 식별)
_SOURCE_TAG = {
    "금융감독원": "FSS",
    "한국은행":   "BOK",
    "금융위원회": "FSC",
    "연합뉴스":   "YNA",
}


def build_regulatory_panel(config: dict, create_llm_fn):
    """규제 동향 모니터링 패널.

    호출하는 쪽에서 ``.panel`` 컨테이너 안에 배치해 주세요 (page-head 포함).
    """
    state = {
        'results': [],
        'mode': 'agency',
    }

    # ── 헤더 ─────────────────────────────────────────────────────────────
    with ui.element('div').classes('page-head'):
        ui.html(
            '<div class="titles">'
            '<div class="page-title">규제 동향</div>'
            '<div class="page-subtitle">금융감독원·한국은행·금융위원회 보도자료 또는 '
            '네이버/BIGKinds/연합뉴스 뉴스 검색을 LLM으로 요약합니다.</div>'
            '</div>'
        )

    # ── 본문 — 좌측 필터 / 우측 결과 ─────────────────────────────────────
    with ui.element('div').classes('filter-result-row'):

        # ── 좌측: 검색 설정 ──────────────────────────────────────────────
        with ui.element('div').classes('filter-col'):
            ui.html(
                '<div class="section-card-title">'
                '<span class="material-symbols-outlined">tune</span>검색 설정'
                '</div>'
            )

            ui.html('<div class="muted-label">검색 방식</div>')
            with ui.row().classes('segmented mb-4 w-full no-wrap gap-0'):
                btn_agency = ui.button('기관별 모니터링').props('flat no-caps').classes('btn-mono flex-1 is-active')
                btn_yna    = ui.button('뉴스 검색').props('flat no-caps').classes('btn-mono flex-1')

            # ── 기관별 모드 UI ───────────────────────────────────────────
            agency_panel = ui.element('div')
            with agency_panel:
                count_input = ui.number(
                    label='기관별 조회 건수', value=3, min=1, max=10, step=1,
                ).props('outlined dense').classes('w-full mb-3')

                ui.html('<div class="muted-label">메일 발송 수신자</div>')
                email_input = ui.input(
                    placeholder='이메일 주소 (발송 시 사용)',
                ).props('outlined dense').classes('w-full mb-3')

                fetch_btn_agency = ui.button('조회 및 분석').classes('btn-primary-mono w-full')
                fetch_status_agency = ui.html(
                    '<div class="muted-text" style="margin-top:8px;"></div>'
                )

            # ── 뉴스 검색 UI ────────────────────────────────────────────
            yna_panel = ui.element('div')
            yna_panel.visible = False
            with yna_panel:
                keyword_input = ui.input(
                    label='질문 (LLM이 키워드 자동 추출)',
                    placeholder='예: 최근 한국은행 기준금리 인하 전망은 어떻습니까?',
                ).props('outlined dense').classes('w-full mb-2')
                date_from_input = ui.input(
                    label='시작일 (YYYY-MM-DD 또는 YYYYMMDD)', placeholder='예: 2025-01-01 또는 20250101',
                ).props('outlined dense').classes('w-full mb-2')
                date_from_err = ui.html('').style('margin:-4px 0 6px 2px;')
                date_to_input = ui.input(
                    label='종료일 (YYYY-MM-DD 또는 YYYYMMDD)', placeholder='예: 2025-12-31 또는 20251231',
                ).props('outlined dense').classes('w-full mb-2')
                date_to_err = ui.html('').style('margin:-4px 0 6px 2px;')

                def _make_date_blur_handler(inp, err_el):
                    def _on_blur():
                        normalized, ok = _normalize_date(inp.value)
                        if not ok:
                            err_el.content = (
                                '<div style="font-size:11px;color:var(--danger);">'
                                '인식할 수 없는 날짜 형식입니다 (예: 2025-01-01, 20250101)</div>'
                            )
                            return
                        inp.value = normalized
                        err_el.content = ''
                    return _on_blur

                date_from_input.on('blur', _make_date_blur_handler(date_from_input, date_from_err))
                date_to_input.on('blur', _make_date_blur_handler(date_to_input, date_to_err))

                yna_count_input = ui.number(
                    label='최대 조회 건수', value=10, min=1, max=30, step=1,
                ).props('outlined dense').classes('w-full mb-3')

                fetch_btn_yna = ui.button('검색 및 요약').classes('btn-primary-mono w-full')
                fetch_status_yna = ui.html(
                    '<div class="muted-text" style="margin-top:8px;"></div>'
                )

        # ── 우측: 결과 ───────────────────────────────────────────────────
        with ui.element('div').classes('result-col'):
            _empty_state_html = (
                '<div class="muted-text">조회 조건을 설정하고 검색을 클릭하세요.</div>'
                '<div style="margin-top:10px;display:flex;flex-wrap:wrap;gap:6px;">'
                '<span class="tag solid">최근 기준금리 변동 요약</span>'
                '<span class="tag solid">가계부채 관련 규제 동향</span>'
                '<span class="tag solid">최근 금융위 보도자료</span>'
                '</div>'
                '<div style="margin-top:8px;font-size:11.5px;color:var(--text-4);">'
                '기관별 모니터링: 금감원·한은·금융위 보도자료를 자동 수집·요약합니다.<br>'
                '뉴스 검색: 질문을 입력하면 관련 뉴스를 찾아 통합 답변을 생성합니다.</div>'
            )
            result_count_label = ui.html(_empty_state_html)

            progress_area = ui.html('')
            skeleton_area = ui.column().classes('w-full mt-2 gap-0')
            skeleton_area.visible = False

            result_container = ui.column().classes('w-full mt-2').style('flex:1; overflow:auto;')

            ui.html('<div class="divider"></div>')
            with ui.row().classes('w-full items-center gap-3'):
                send_btn = ui.button('Outlook 메일 발송').classes('btn-primary-mono')
                if not _is_outlook_available():
                    send_btn.props('disable')
                    send_btn.tooltip('로컬 Outlook(Windows) 환경 전용 — 현재 환경에서는 발송할 수 없습니다.')
                send_status = ui.html('<div class="muted-text"></div>')
                if not _is_outlook_available():
                    send_status.content = (
                        f'<div class="muted-text" style="font-size:11px;">{_html.escape(_OUTLOOK_UNAVAILABLE_MSG)}</div>'
                    )

    ui.add_body_html(elapsed_ticker_script())

    # ─── 모드 전환 ───────────────────────────────────────────────────────

    def _set_mode(mode: str):
        state['mode'] = mode
        if mode == 'agency':
            agency_panel.visible = True
            yna_panel.visible = False
            btn_agency.classes(add='is-active')
            btn_yna.classes(remove='is-active')
        else:
            agency_panel.visible = False
            yna_panel.visible = True
            btn_agency.classes(remove='is-active')
            btn_yna.classes(add='is-active')

    btn_agency.on_click(lambda: _set_mode('agency'))
    btn_yna.on_click(lambda: _set_mode('news'))

    # ─── 렌더링 ─────────────────────────────────────────────────────────

    def _render_one_card(item: dict):
        """단일 기사 카드를 현재 컨텍스트에 렌더링."""
        source = item.get('source', '')
        tag_label = _SOURCE_TAG.get(source, source[:3])
        title_safe = _html.escape(item.get('title') or '')
        url_safe = _html.escape(item.get('url') or '')
        summary_safe = _html.escape(item.get('summary', '')).replace('\n', '<br>')
        pub_date = item.get('published_date', '')
        date_html = (
            f'<span style="color:var(--text-4);font-size:11px;margin-left:auto;">'
            f'{_html.escape(str(pub_date))}</span>'
        ) if pub_date else ''

        with ui.element('div').classes('reg-card'):
            ui.html(
                '<div class="reg-title">'
                f'<span class="tag solid">{_html.escape(tag_label)}</span>'
                f'<span style="color:var(--text-3);font-size:11.5px;">'
                f'{_html.escape(source)}</span>'
                f'<span style="flex:1;color:var(--text);font-weight:600;">{title_safe}</span>'
                f'{date_html}'
                '</div>'
                f'<div class="reg-summary">{summary_safe}</div>'
            )
            # 외부 원문 링크 — 반드시 새 탭으로 열림
            link_url = item.get('url') or ''
            ui.link('원문 보기 →', target=link_url, new_tab=True).classes('reg-link')

    def _render_results(
        results: list[dict],
        clustered: bool = False,
        question: str = '',
        keywords: list[str] | None = None,
        answer_summary: str = '',
        approximate: bool = False,
    ):
        result_container.clear()
        with result_container:
            if not results:
                ui.html(
                    '<div style="text-align:center;color:var(--text-4);font-size:13px;'
                    'padding:24px;background:var(--bg-elev);border:1px solid var(--border);'
                    'border-radius:var(--radius);">검색 결과가 없습니다.</div>'
                )
                return

            # ── 관련성 미달 안내 (참고용 근접 기사) ───────────────────────
            if approximate:
                ui.html(
                    '<div style="font-size:12.5px;color:var(--text-2);'
                    'padding:10px 12px;margin-bottom:10px;background:var(--bg-elev);'
                    'border:1px solid var(--text-3);border-left:3px solid var(--text-2);'
                    'border-radius:var(--radius);">'
                    '⚠ 질문과 <b>명확히 관련된 기사를 찾지 못했습니다.</b> '
                    '아래는 의미상 가장 가까운 <b>참고용 근접 기사</b>이며, '
                    '질문에 대한 직접적인 답이 아닐 수 있습니다.</div>'
                )

            # ── 최상단: 질문 통합 답변 (있을 때) ───────────────────────────
            if answer_summary:
                kws_html = ''
                if keywords:
                    chips = ' '.join(
                        f'<span class="tag solid" style="margin-right:4px;">{_html.escape(k)}</span>'
                        for k in keywords
                    )
                    kws_html = (
                        f'<div style="margin:6px 0 10px;font-size:11.5px;color:var(--text-3);">'
                        f'추출 키워드: {chips}</div>'
                    )
                ans_html = _html.escape(answer_summary).replace('\n', '<br>')
                q_html = _html.escape(question)
                ui.html(
                    '<div class="reg-card" style="border:1px solid var(--text-3);'
                    'background:var(--bg-elev);">'
                    '<div class="reg-title">'
                    '<span class="tag solid">통합답변</span>'
                    f'<span style="flex:1;color:var(--text);font-weight:700;">{q_html}</span>'
                    '</div>'
                    f'{kws_html}'
                    f'<div class="reg-summary">{ans_html}</div>'
                    '</div>'
                )

            if not clustered:
                for item in results:
                    _render_one_card(item)
                return

            # 클러스터별 대표 기사만 표시 (cluster_rank 기준 정렬)
            clusters: dict[int, list[dict]] = {}
            for item in results:
                c = item.get('cluster', 0)
                clusters.setdefault(c, []).append(item)

            # cluster_rank 가져오기 (클러스터 내 첫 아이템 기준)
            def _cluster_rank(c_idx: int) -> int:
                its = clusters[c_idx]
                return its[0].get('cluster_rank', 999) if its else 999

            ordered = sorted(clusters.keys(), key=_cluster_rank)

            for display_idx, c_idx in enumerate(ordered, start=1):
                items_in_cluster = clusters[c_idx]
                reps = [it for it in items_in_cluster if it.get('is_representative')]
                if not reps:
                    reps = items_in_cluster[:2]

                total_in_cluster = len(items_in_cluster)
                sim = items_in_cluster[0].get('cluster_similarity', 0.0)
                ui.html(
                    f'<div style="font-size:12px;font-weight:700;color:var(--text-3);'
                    f'text-transform:uppercase;letter-spacing:.04em;'
                    f'margin:16px 0 8px;padding:0 2px;">'
                    f'클러스터 {display_idx} — 대표 기사 '
                    f'(전체 {total_in_cluster}건 중 2건, 질문 유사도 {sim:.3f})</div>'
                )
                for item in reps:
                    _render_one_card(item)

    # ─── 기관별 조회 ────────────────────────────────────────────────────

    # 실행 중 취소를 위한 컨트롤(작업 핸들 + 진행 상태)
    _agency_ctl = {'task': None, 'busy': False}
    _yna_ctl = {'task': None, 'busy': False}

    # create_task 로 띄우면 NiceGUI 슬롯/클라이언트 컨텍스트가 유실되어
    # ui.notify 등이 실패한다. 빌드 시점 client 를 캡처해 태스크 내부에서 복원.
    _client = _ng_context.client

    def _spawn(coro):
        async def _wrapped():
            with _client:
                await coro
        return asyncio.create_task(_wrapped())

    async def fetch_agency_updates():
        _apply_current_user()
        log.info('규제동향(기관별) 조회 시작')
        count = int(count_input.value or 3)
        fss_api_key       = config.get('fss_api_key', '').strip()
        naver_client_id   = config.get('naver_client_id', '').strip()
        naver_client_secret = config.get('naver_client_secret', '').strip()

        _start_ts = _time.time()
        _agency_ctl['busy'] = True
        _agency_ctl['task'] = asyncio.current_task()
        fetch_btn_agency.text = '중지'
        fetch_btn_agency.classes(add='is-stop')
        fetch_status_agency.content = ''
        progress_area.content = progress_block_html('수집 및 분석 중…', start_ts=_start_ts)
        result_container.clear()
        result_count_label.content = ''
        skeleton_area.visible = True
        skeleton_area.clear()
        with skeleton_area:
            for _ in range(3):
                ui.html('<div class="skeleton-card"></div>')

        try:
            llm = create_llm_fn()
            from regulatory_agent import fetch_and_summarize
            results = await nicegui_run.io_bound(
                fetch_and_summarize, fss_api_key, llm, count,
                naver_client_id, naver_client_secret,
            )
            state['results'] = results
            _render_results(results)
            result_count_label.content = (
                f'<div class="info-block"><b>조회 결과: {len(results)}건</b></div>'
            )
            progress_area.content = ''
            ui.notify(f'{len(results)}건 분석 완료', type='positive', position='top')
            activity_log.record('regulatory', '금감원 보도자료 조회', detail=f'{len(results)}건', status='done')
        except asyncio.CancelledError:
            log.info('기관별 조회 취소됨')
            progress_area.content = (
                '<div class="muted-text" style="color:var(--warning);">조회를 중지했습니다.</div>'
            )
            ui.notify('조회를 중지했습니다.', type='warning', position='top')
        except Exception as e:
            log.error('기관별 조회 오류: %s', e)
            ui.notify(f'조회 오류: {e}', type='negative', position='top')
            progress_area.content = (
                '<div class="muted-text" style="color:var(--danger);">조회 실패</div>'
            )
        finally:
            skeleton_area.visible = False
            _agency_ctl['busy'] = False
            _agency_ctl['task'] = None
            fetch_btn_agency.text = '조회 및 분석'
            fetch_btn_agency.classes(remove='is-stop')

    # ─── 뉴스 검색 ──────────────────────────────────────────────────────

    async def fetch_yonhap_search():
        _apply_current_user()
        question = (keyword_input.value or '').strip()
        if not question:
            ui.notify('질문을 입력하세요.', type='warning', position='top')
            return
        log.info('규제동향(뉴스검색) 질의: %s', question[:120])

        date_from_norm, from_ok = _normalize_date(date_from_input.value)
        date_to_norm, to_ok = _normalize_date(date_to_input.value)
        if not from_ok or not to_ok:
            ui.notify('날짜 형식을 확인하세요 (예: 2025-01-01, 20250101).', type='warning', position='top')
            return
        date_from_input.value = date_from_norm
        date_to_input.value = date_to_norm
        date_from = date_from_norm or None
        date_to   = date_to_norm or None
        count     = int(yna_count_input.value or 10)
        naver_client_id     = config.get('naver_client_id', '').strip()
        naver_client_secret = config.get('naver_client_secret', '').strip()

        _start_ts = _time.time()
        _yna_ctl['busy'] = True
        _yna_ctl['task'] = asyncio.current_task()
        fetch_btn_yna.text = '중지'
        fetch_btn_yna.classes(add='is-stop')
        fetch_status_yna.content = ''
        result_container.clear()
        result_count_label.content = ''
        skeleton_area.visible = True
        skeleton_area.clear()
        with skeleton_area:
            for _ in range(3):
                ui.html('<div class="skeleton-card"></div>')

        def _step(idx: int, extra: str = '') -> None:
            elapsed_span = (
                f'<span class="progress-block-elapsed" data-elapsed-since="{_start_ts}">'
                '0초 경과</span>'
            )
            progress_area.content = (
                step_list_html(_YNA_STEPS, idx)
                + f'<div class="muted-text" style="display:flex;align-items:center;gap:8px;">'
                f'{extra}{elapsed_span}</div>'
            )

        _step(0)

        try:
            llm = create_llm_fn()
            from regulatory_agent import (
                extract_search_queries,
                search_news_by_keywords,
                rerank_by_question,
                summarize_update,
                cluster_news_results,
                summarize_clusters_for_question,
            )

            embed_url     = config.get('legal_embedding', {}).get('url',     'http://127.0.0.1:8081')
            embed_model   = config.get('legal_embedding', {}).get('model',   'bge-m3')
            embed_timeout = config.get('legal_embedding', {}).get('timeout', 45)

            # 1) LLM으로 다양한 검색 표현 생성 (뉴스 헤드라인 기반 변형 포함)
            search_queries = await nicegui_run.io_bound(
                extract_search_queries, question, llm, 5,
            )
            _step(1, f'검색 표현: {_html.escape(", ".join(search_queries))} · ')

            # 2) 검색 표현으로 뉴스 후보 수집 (네이버→BIGKinds→연합뉴스 RSS 순)
            fetch_count = min(count * 3, 30)
            items = await nicegui_run.io_bound(
                search_news_by_keywords, search_queries, date_from, date_to, fetch_count,
                naver_client_id, naver_client_secret,
            )

            # 3) BGE-M3 질문-기사 유사도 재정렬(항상 수행 → 관련성 점수 확보) + 임계값 판정
            if items:
                _step(2, f'{len(items)}건 후보 · ')
                items = await nicegui_run.io_bound(
                    rerank_by_question,
                    question, items, embed_url, embed_model, embed_timeout, count,
                )

            # 관련성 임계값으로 정상/근접(참고용) 분기 (혼합 동작)
            sim_threshold = float(
                config.get('legal_embedding', {}).get('relevance_threshold', 0.45)
            )
            approximate = False
            scored = [it for it in items if 'rerank_score' in it]
            if scored:
                relevant = [it for it in scored if it['rerank_score'] >= sim_threshold]
                if relevant:
                    items = relevant
                else:
                    # 전부 임계값 미달 → 가장 가까운 상위 소수만 참고용으로
                    approximate = True
                    items = scored[:min(3, len(scored))]
            else:
                # 임베딩 불가(점수 없음) → 렉시컬 신호로 대체 판정
                lex_hit = [it for it in items if it.get('lexical_score', 0) > 0]
                if lex_hit:
                    items = lex_hit[:count]
                else:
                    approximate = True
                    items = items[:min(3, len(items))]
            if approximate:
                for it in items:
                    it['is_approximate'] = True
                log.info(
                    '연합뉴스 직접검색: 임계값(%.2f) 이상 기사 없음 → 참고용 근접 %d건',
                    sim_threshold, len(items),
                )

            # 4) 각 기사 LLM 요약
            _step(3, f'{len(items)}건 · ')

            def _summarize_all(items_, llm_):
                out = []
                for it in items_:
                    try:
                        s = summarize_update(it["source"], it["title"], it["url"], llm_)
                    except Exception as exc:
                        s = f"(요약 실패: {exc})\n출처: {it['url']}"
                    out.append({**it, "summary": s})
                return out

            results = await nicegui_run.io_bound(_summarize_all, items, llm)

            # 5) 클러스터링 + 질문 유사도 기반 정렬
            clustered = False
            if len(results) >= 3:
                _step(4)
                results = await nicegui_run.io_bound(
                    cluster_news_results,
                    results, question, embed_url, embed_model, embed_timeout,
                )
                clustered = True

            # 6) 클러스터별 대표 기사로 질문 통합 답변 생성
            answer_summary = ''
            if results:
                _step(5)
                answer_summary = await nicegui_run.io_bound(
                    summarize_clusters_for_question, question, results, llm, approximate,
                )

            state['results'] = results
            _render_results(
                results,
                clustered=clustered,
                question=question,
                keywords=search_queries,
                answer_summary=answer_summary,
                approximate=approximate,
            )
            n_clusters = len({it.get('cluster', 0) for it in results}) if clustered else 0
            cluster_info = f' / {n_clusters}개 클러스터' if clustered else ''
            kws_str = ', '.join(search_queries)
            approx_note = (
                ' — <b style="color:var(--text-2);">명확히 관련된 기사 없음(참고용 근접)</b>'
                if approximate else ''
            )
            result_count_label.content = (
                f'<div class="info-block"><b>뉴스 검색 결과: {len(results)}건{cluster_info}</b>'
                f'{approx_note} (검색 표현: {_html.escape(kws_str)})</div>'
            )
            progress_area.content = ''
            if results:
                ui.notify(f'{len(results)}건 검색·요약 완료', type='positive', position='top')
            else:
                ui.notify('검색 결과가 없습니다. 질문이나 날짜를 조정해 보세요.', type='warning', position='top')
        except asyncio.CancelledError:
            log.info('뉴스 검색 취소됨')
            progress_area.content = (
                '<div class="muted-text" style="color:var(--warning);">검색을 중지했습니다.</div>'
            )
            ui.notify('검색을 중지했습니다.', type='warning', position='top')
        except Exception as e:
            log.error('연합뉴스 검색 오류: %s', e)
            ui.notify(f'검색 오류: {e}', type='negative', position='top')
            progress_area.content = (
                '<div class="muted-text" style="color:var(--danger);">검색 실패</div>'
            )
        finally:
            skeleton_area.visible = False
            _yna_ctl['busy'] = False
            _yna_ctl['task'] = None
            fetch_btn_yna.text = '검색 및 요약'
            fetch_btn_yna.classes(remove='is-stop')

    # ─── 메일 발송 ──────────────────────────────────────────────────────

    async def send_email():
        _apply_current_user()
        if not state['results']:
            ui.notify('먼저 규제 동향을 조회하세요.', type='warning', position='top')
            return
        log.info('규제동향 메일 발송 시도')
        to = (email_input.value or '').strip()
        if not to:
            ui.notify('수신자 이메일 주소를 입력하세요. (기관별 모드)', type='warning', position='top')
            return

        send_btn.props(add='disable')
        send_status.content = '<div class="muted-text">발송 중…</div>'
        try:
            from regulatory_agent import send_regulatory_email
            await nicegui_run.io_bound(send_regulatory_email, to, state['results'])
            send_status.content = (
                f'<div class="muted-text">{_html.escape(to)} 발송 완료</div>'
            )
            ui.notify('메일 발송 완료', type='positive', position='top')
        except Exception as e:
            log.error('메일 발송 오류: %s', e)
            ui.notify(f'발송 오류: {e}', type='negative', position='top')
            send_status.content = (
                '<div class="muted-text" style="color:#b91c1c;">발송 실패</div>'
            )
        finally:
            send_btn.props(remove='disable')

    def _on_agency_click():
        # 실행 중이면 중지, 아니면 조회 시작 (버튼 하나로 토글)
        if _agency_ctl['busy']:
            if _agency_ctl['task'] is not None:
                _agency_ctl['task'].cancel()
            return
        _spawn(fetch_agency_updates())

    def _on_yna_click():
        if _yna_ctl['busy']:
            if _yna_ctl['task'] is not None:
                _yna_ctl['task'].cancel()
            return
        _spawn(fetch_yonhap_search())

    fetch_btn_agency.on_click(_on_agency_click)
    fetch_btn_yna.on_click(_on_yna_click)
    send_btn.on_click(send_email)
