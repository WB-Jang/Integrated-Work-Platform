"""
Integrated Work Platform — NiceGUI entry point (monochrome UX redesign)

기존 src/app.py 를 대체하는 드롭인 파일. 비즈니스 로직(LLM 호출·파일 처리·세션
상태)은 원본 그대로 유지하고, UI 레이아웃과 CSS만 새 모노크롬 디자인 시스템으로
이식했습니다.

설치:
    cp nicegui_port/ui_styles.py    src/ui_styles.py
    cp nicegui_port/app.py          src/app.py
    cp nicegui_port/legal_panel.py  src/legal_panel.py
"""

import os
import sys
import json
import uuid
import textwrap
import re
import shutil
import socket
import asyncio
import html as _html
from urllib.parse import urlparse

from starlette.requests import Request  # 접속 IP 식별용 (NiceGUI 페이지 request 주입)

# ── .env 자동 로딩 (개발용 폴더에서 secrets 관리) ─────────────────────────────
# HF Spaces 환경에서는 Space Secrets가 환경변수로 직접 주입되므로 .env가 없어도
# 정상 동작합니다. dotenv 패키지가 설치돼 있지 않거나 .env 파일이 없어도 무시.
try:
    from dotenv import load_dotenv  # type: ignore
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
    if os.path.exists(_env_path):
        load_dotenv(_env_path, override=False)
except Exception:
    pass

try:
    import pythoncom
    _HAS_PYTHONCOM = True
except ImportError:
    _HAS_PYTHONCOM = False


def _is_office_com_available() -> bool:
    """Word COM 클래스가 실제로 등록돼 있는지(= MS Office 설치 여부)를 확인합니다."""
    if sys.platform != 'win32' or not _HAS_PYTHONCOM:
        return False
    try:
        import winreg
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, 'Word.Application')
        return True
    except Exception:
        return False

import docx
from pypdf import PdfReader
from nicegui import ui, events, run as nicegui_run, app as nicegui_app

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

from read_docx_util import read_docx, read_file_with_llm_chunks
from highlighting import highlight_errors
from summarizer import hierarchical_summarize, compress_document, create_compressed_docx
from reporting_panel import build_reporting_panel
from legal_panel import build_legal_panel
from outlook_panel import build_outlook_panel
from regulatory_panel import build_regulatory_panel
from admin_panel import build_admin_panel
from fss_dashboard_panel import build_fss_dashboard_panel
from risk_indicator_panel import build_risk_indicator_panel
from agent_console import build_agent_panel
import menu_state as _msm
from logger import get_logger, set_current_user, register_client_user, unregister_client_user

from ui_styles import inject_global_css   # ← 신규: 모노크롬 디자인 시스템

log = get_logger("app")


# ──────────────────────────────────────────────────────────────────────────────
# 업로드 폴더 자동 정리 (서버 시작 시 1회)
# ──────────────────────────────────────────────────────────────────────────────
def _cleanup_old_uploads(max_age_hours: int = 24) -> None:
    """uploads/ 하위에서 max_age_hours 보다 오래된 파일·세션 폴더를 일괄 정리.

    멀티유저 환경에서 사용자가 X 버튼으로 명시 삭제하지 않은 채 떠난 파일들이
    무한히 쌓이는 것을 방지합니다.
    """
    import time
    root = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..', 'uploads',
    ))
    if not os.path.isdir(root):
        return
    cutoff = time.time() - max_age_hours * 3600
    removed_files = 0
    removed_dirs = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        rel = os.path.relpath(dirpath, root).replace('\\', '/')
        # PDF 변환 폴더는 세션별(uploads/pdf/<sess>/...)로 분리되므로 다른 업로드와
        # 동일하게 mtime 기준으로 오래된 파일/빈 폴더를 정리한다. 진행 중 변환 파일은
        # mtime 이 최신이라 cutoff 에 걸리지 않아 안전.
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            try:
                if os.path.getmtime(fp) < cutoff:
                    os.remove(fp)
                    removed_files += 1
            except Exception:
                pass
        # 빈 세션 디렉토리 제거 (uploads/analysis/<sess>, uploads/summary/<sess>)
        try:
            if (dirpath != root and rel not in ('analysis', 'summary')
                    and not os.listdir(dirpath)):
                os.rmdir(dirpath)
                removed_dirs += 1
        except Exception:
            pass
    if removed_files or removed_dirs:
        log.info("업로드 폴더 정리 완료 — 파일 %d개·디렉토리 %d개 제거 (%dh 이상)",
                 removed_files, removed_dirs, max_age_hours)


# 서버 import 시점에 1회 실행
try:
    _cleanup_old_uploads(max_age_hours=24)
except Exception as _e:
    log.warning("업로드 정리 중 오류 (계속 진행): %s", _e)

# ──────────────────────────────────────────────────────────────────────────────
# 설정 로드 (기존 로직 그대로)
# ──────────────────────────────────────────────────────────────────────────────
_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'config.json')
if os.path.exists(_config_path):
    with open(_config_path, encoding='utf-8') as f:
        _config = json.load(f)
else:
    _config = {}

# ── 환경변수 우선 주입 (HF Spaces Secrets / .env 호환) ───────────────────────
# 보안 원칙: API 키는 config.json 에 평문으로 저장하지 않습니다.
# HF Spaces 에서는 Space Settings → Repository secrets,
# 로컬 개발 환경에서는 프로젝트 루트의 .env (gitignore 됨) 를 사용하세요.
_env_openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
if _env_openai_key:
    _config.setdefault("openai", {})["api_key"] = _env_openai_key

_env_openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
if _env_openrouter_key:
    _config.setdefault("openrouter", {})["api_key"] = _env_openrouter_key

_env_fss_key = os.environ.get("FSS_API_KEY", "").strip()
if _env_fss_key:
    _config["fss_api_key"] = _env_fss_key

BASE_URL = _config.get("llm_base_url", "http://localhost:8080/v1")
MODEL_NAME = _config.get("model_name", "llama-3-Korean-Bllossom-8B-Q4_K_M")
# HOST/PORT 는 env 가 있으면 우선 (Docker/HF Spaces 호환)
HOST = os.environ.get("HOST", _config.get("host", '127.0.0.1'))
APP_PORT = int(os.environ.get("APP_PORT", _config.get("app_port", 8501)))
LLM_TIMEOUT = _config.get("llm_timeout", 1200)
LLM_MAX_TOKENS = _config.get("llm_max_tokens", 2048)
OPENROUTER_FALLBACK_MODEL = _config.get("openrouter_fallback_model", "openai/gpt-oss-20b")

# ── LLM 백엔드 가용성 점검 (폐쇄망 대응) ─────────────────────────────────────
# 로컬 llama-server / OpenAI / OpenRouter 중 하나라도 연결되면 가용.
# 어느 것도 연결되지 않으면 LLM 기능에 안내 팝업 + 버튼 비활성화가 적용된다.
import llm_status
llm_status.detect(_config)

# 모든 LLM 프롬프트에 '오늘 날짜' 시스템 문구 자동 주입 (날짜 오기 검증 등)
import prompt_date
prompt_date.install()

# ── 접속 IP → 사용자 이름 매핑 (이니셜 입력 대체, 로그 식별용) ──────────────────
# config.json 의 ip_user_map 에 {"10.20.30.40": "홍길동"} 형태로 등록하면 해당 IP
# 접속자는 이름으로 로그에 기록된다. 미등록 IP 는 IP 문자열 자체로 기록.
# 주의: 사내 프록시/NAT 환경에서는 여러 사용자가 동일 IP 로 보일 수 있다.
_IP_USER_MAP: dict = _config.get("ip_user_map", {}) or {}


def _client_ip(request) -> str:
    """프록시(X-Forwarded-For/X-Real-IP) 우선, 없으면 직접 연결 IP를 반환한다."""
    try:
        xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if xff:
            return xff
        real = (request.headers.get("x-real-ip") or "").strip()
        if real:
            return real
        if request.client and request.client.host:
            return request.client.host
    except Exception:
        pass
    return "unknown"


# ── 모델 옵션 ───────────────────────────────────────────────────────────────
# OpenAI 직통 모델 (api.openai.com). gpt-5-mini 가 신규 기본값.
MODEL_OPTIONS_OPENAI: dict[str, str] = {
    "gpt-5-mini": "gpt-5-mini",
}

# OpenRouter 경유 모델 (openrouter.ai). 통신 불안정 시 폴백용으로 유지.
MODEL_OPTIONS_OPENROUTER: dict[str, str] = {
    "gpt-oss-20b":           "openai/gpt-oss-20b",
    "gpt-oss-120b":          "openai/gpt-oss-120b",
    "llama-3.1-8b":          "meta-llama/llama-3.1-8b-instruct",
    "llama-3.3-70b":         "meta-llama/llama-3.3-70b-instruct",
    "gemini-3.1-flash-lite": "google/gemini-3.1-flash-lite",
    "claude-sonnet-latest":  "~anthropic/claude-sonnet-latest",
    "Gemma 4 26B A4B":       "google/gemma-4-26b-a4b-it",
    "DeepSeek V4 Flash":     "deepseek/deepseek-v4-flash",
}

# 메인 LLM = Gemma 4 26B A4B (OpenRouter 경유). 드롭다운 최상단·기본 선택값.
_DEFAULT_MODEL = "Gemma 4 26B A4B"
_MODEL_OPTIONS_ALL: dict[str, str] = {**MODEL_OPTIONS_OPENAI, **MODEL_OPTIONS_OPENROUTER}
# 기본 모델(_DEFAULT_MODEL)을 맨 앞에 배치한 통합 옵션 (드롭다운 노출 순서 = dict 순서)
MODEL_OPTIONS: dict[str, str] = {
    _DEFAULT_MODEL: _MODEL_OPTIONS_ALL[_DEFAULT_MODEL],
    **{k: v for k, v in _MODEL_OPTIONS_ALL.items() if k != _DEFAULT_MODEL},
}


def resolve_chunk_model(model_id: str) -> tuple[str, str]:
    """UI 모델 선택 창의 모델 id → (provider, 실제 모델 id).

    LLM 청킹이 채팅창에서 선택한 모델을 그대로 쓰도록 매핑한다.
    OpenAI 등록 모델이면 ("openai", 실제id), 그 외에는 OpenRouter 로 간주.
    """
    if model_id in MODEL_OPTIONS_OPENAI:
        return "openai", MODEL_OPTIONS_OPENAI[model_id]
    return "openrouter", MODEL_OPTIONS_OPENROUTER.get(model_id, model_id)


def _is_port_open(base_url: str, timeout: float = 1.5) -> bool:
    try:
        parsed = urlparse(base_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def _build_openai_llm(model_id="gpt-5-mini", temperature=0, max_tokens=None) -> ChatOpenAI:
    """OpenAI API 직통 LLM 빌더. api_key 는 환경변수(OPENAI_API_KEY) 기반."""
    openai_cfg = _config.get("openai", {})
    api_key = openai_cfg.get("api_key", "") or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        log.warning(
            "OPENAI_API_KEY 가 비어 있습니다. .env 또는 HF Spaces Secrets 에 설정하세요."
        )
    return ChatOpenAI(
        base_url=openai_cfg.get("base_url", "https://api.openai.com/v1"),
        api_key=api_key,
        model=model_id,
        temperature=temperature,
        max_tokens=max_tokens or LLM_MAX_TOKENS,
        max_retries=1,
        timeout=openai_cfg.get("timeout", 600),
    )


def _build_openrouter_llm(model_id=None, temperature=0, max_tokens=None) -> ChatOpenAI:
    openrouter_cfg = _config.get("openrouter", {})
    api_key = openrouter_cfg.get("api_key", "") or os.environ.get("OPENROUTER_API_KEY", "")
    return ChatOpenAI(
        base_url=openrouter_cfg.get("base_url", "https://openrouter.ai/api/v1"),
        api_key=api_key,
        model=model_id or OPENROUTER_FALLBACK_MODEL,
        temperature=temperature,
        max_tokens=max_tokens or LLM_MAX_TOKENS,
        max_retries=0,
    )


def create_llm(model_id=None) -> ChatOpenAI:
    # UI 드롭다운에서 모델이 선택된 경우: OpenAI 직통 또는 OpenRouter 분기
    if model_id:
        if model_id in MODEL_OPTIONS_OPENAI:
            openai_id = MODEL_OPTIONS_OPENAI[model_id]
            log.info("LLM 선택 (OpenAI): %s → %s", model_id, openai_id)
            return _build_openai_llm(model_id=openai_id)
        openrouter_id = MODEL_OPTIONS_OPENROUTER.get(model_id, model_id)
        log.info("LLM 선택 (OpenRouter): %s → %s", model_id, openrouter_id)
        return _build_openrouter_llm(model_id=openrouter_id)

    # 모델 미지정 시: committee_llm 설정 따름. provider=openai 이면 OpenAI 직통.
    committee_cfg = _config.get("committee_llm", {})
    provider = committee_cfg.get("provider", "local")

    if provider == "openai":
        return _build_openai_llm(
            model_id=committee_cfg.get("model", "gpt-5-mini"),
            temperature=committee_cfg.get("temperature", 0),
            max_tokens=committee_cfg.get("max_tokens", LLM_MAX_TOKENS),
        )

    if provider == "openrouter":
        return _build_openrouter_llm(
            temperature=committee_cfg.get("temperature", 0),
            max_tokens=committee_cfg.get("max_tokens", LLM_MAX_TOKENS),
        )

    local_base_url = committee_cfg.get("base_url", BASE_URL)
    if _is_port_open(local_base_url):
        return ChatOpenAI(
            base_url=local_base_url,
            api_key=committee_cfg.get("api_key", "not-needed"),
            model=committee_cfg.get("model", MODEL_NAME),
            temperature=committee_cfg.get("temperature", 0),
            timeout=committee_cfg.get("timeout", LLM_TIMEOUT),
            max_tokens=committee_cfg.get("max_tokens", LLM_MAX_TOKENS),
            max_retries=0,
        )

    log.warning("로컬 LLM(%s) 접속 불가 → 기본 LLM (gpt-5-mini) fallback", local_base_url)
    return _build_openai_llm(
        temperature=committee_cfg.get("temperature", 0),
        max_tokens=committee_cfg.get("max_tokens", LLM_MAX_TOKENS),
    )


def _gate_llm_button(btn, native: bool = False):
    """LLM 백엔드 미연결 시 LLM 실행 버튼을 비활성화한다.

    native=True 는 ui.element('button') 같은 네이티브 버튼(quasar q-btn 아님)용.
    가용한 경우 아무것도 하지 않는다.
    """
    if llm_status.is_available():
        return
    try:
        btn.props('disabled' if native else 'disable')
        btn.classes(add='is-disabled')
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# 유틸리티 (원본 그대로)
# ──────────────────────────────────────────────────────────────────────────────
def escape_markdown_special_chars(text):
    if not text:
        return text
    text = re.sub(r'#(?![0-9a-fA-F]{3,6})', '&#35;', text)
    text = text.replace('*', '&#42;').replace('_', '&#95;')
    return text


def read_raw_docx(file_path):
    try:
        doc = docx.Document(file_path)
        return '\n'.join(para.text for para in doc.paragraphs)
    except Exception as e:
        return f"파일을 읽는 중 오류가 발생했습니다: {e}"


def read_pdf(file_path):
    # pypdf → pypdfium2 폴백을 포함한 견고한 추출기 사용(이미지 PDF면 빈 문자열).
    from read_docx_util import read_pdf_as_text
    return read_pdf_as_text(file_path)


# ──────────────────────────────────────────────────────────────────────────────
# LLM 체인 함수 (원본 그대로)
# ──────────────────────────────────────────────────────────────────────────────
def get_proofreading_chain(llm):
    template = """
    당신은 한국어 교정 전문가입니다. 아래 텍스트에서 오타, 비문, 어색한 표현을 찾아주세요.

    [텍스트]:
    {text}

    [응답 형식]:
    반드시 아래와 같은 **JSON 포맷**으로만 응답하세요. 다른 말은 하지 마세요.
    오류가 없으면 빈 리스트 [] 를 반환하세요.

    [
      {{
        "error_sentence": "오류가 포함된 원본 문장 또는 단어 구절",
        "correction": "수정 제안 내용",
        "reason": "수정 이유"
      }}
    ]
    """
    prompt = PromptTemplate.from_template(template)
    return prompt | llm | StrOutputParser()


def get_logical_error_chain(llm):
    template = """
    [역할]: 전문 팩트체커
    [텍스트]: {text}
    [지시]: 시간·장소·인물·수치·인과관계·모순 검증.
    [응답 형식]: JSON 배열만. 마크다운 금지.
    [
      {{
        "error_sentence": "원문 문장",
        "correction": "수정 제안",
        "reason": "논리적 모순 설명"
      }}
    ]
    """
    prompt = PromptTemplate.from_template(template)
    return prompt | llm | StrOutputParser()


def get_english_chain(llm):
    """Business Tone & Manner — 영어 문서를 비즈니스 격식에 맞게 다듬는 분석."""
    template = """
    [Role]: You are a senior business English editor specializing in corporate reports and formal business communication.
    [Text to review]: {text}

    [Editing criteria]:
      - Formality: no contractions (don't → do not), no colloquialisms or slang.
      - Objectivity: avoid exaggerated adjectives, hedging, or emotional language.
      - Conciseness: remove wordiness, redundancy, and filler phrases.
      - Clarity: precise terminology, unambiguous references.
      - Active voice preferred over passive voice (unless passive is more natural).
      - Consistent business reporting tone throughout.

    [Instruction]:
      Identify every sentence or phrase that violates the criteria above and
      propose an improved version. Only flag sentences that genuinely need
      revision — do not produce false positives.

    [Response format]: JSON array only. No markdown, no commentary.
    [
      {{
        "error_sentence": "the original English sentence or phrase",
        "correction": "revised English version (business-formal)",
        "reason": "brief explanation in Korean (사유는 한국어로)"
      }}
    ]
    """
    prompt = PromptTemplate.from_template(template)
    return prompt | llm | StrOutputParser()


def analyze_one_section(chain, title, content):
    response_json = chain.invoke({"text": content})
    highlighted_text, errors = highlight_errors(content, response_json)
    safe_highlighted = escape_markdown_special_chars(highlighted_text)
    section_html = textwrap.dedent(f"""
        <div style="margin-bottom: 20px;">
            <div style="font-size: 13px; font-weight: 600; color: var(--text, #0a0a0a);
                        margin-bottom: 6px; border-bottom: 1px solid var(--border, #e7e5e4);
                        padding-bottom: 4px;">{title}</div>
            <div style="font-size: 13.5px; color: var(--text-2, #404040);
                        line-height: 1.75;">{safe_highlighted}</div>
        </div>
    """).strip()
    return section_html, errors


def render_results(container, results_data):
    """모노크롬 결과 카드 렌더링."""
    container.clear()
    with container:
        if not results_data:
            ui.html('<div style="color:var(--text-4);font-size:13px;text-align:center;'
                    'padding:20px;background:var(--bg-elev);border:1px solid var(--border);'
                    'border-radius:var(--radius);">검출된 수정 사항이 없습니다.</div>')
            return

        ui.html(
            f'<div style="font-size:12.5px;color:var(--text-3);margin:4px 0 12px;">'
            f'총 <b style="color:var(--text);">{len(results_data)}개 섹션</b>에서 '
            f'수정 사항이 발견되었습니다.</div>'
        )

        for res in results_data:
            errs = res.get('errors', [])
            html = (
                '<details class="section-result" open>'
                '<summary class="section-result-head">'
                '<span class="material-symbols-outlined" style="font-size:16px;color:var(--text-3);">article</span>'
                f'<span>{_html.escape(res["title"])}</span>'
                f'<span class="count">{len(errs)}건</span>'
                '</summary>'
            )
            for er in errs:
                original = _html.escape(er.get('error_sentence', ''))
                correction = _html.escape(er.get('correction', ''))
                reason = _html.escape(er.get('reason', ''))
                html += (
                    '<div class="err-card">'
                    '<div class="err-row">'
                    f'<span class="err-from">{original}</span>'
                    '<span class="err-arrow">→</span>'
                    f'<span class="err-to">{correction}</span>'
                    '</div>'
                    f'<div class="err-reason"><b>이유:</b> {reason}</div>'
                    '</div>'
                )
            html += '</details>'
            ui.html(html)


# ──────────────────────────────────────────────────────────────────────────────
# 홈 채팅 — 플랫폼 안내 어시스턴트
# ──────────────────────────────────────────────────────────────────────────────
_HOME_SYSTEM_PROMPT = """당신은 통합업무플랫폼(Integrated Work Platform)의 AI 안내 어시스턴트입니다.
사용자가 플랫폼 기능을 이해하고 활용할 수 있도록 안내합니다.

[주요 기능]
- 문서복합분석: DOCX/PDF/HWP 문서 오타 교정·논리 검증·Business Tone&Manner
- 문서요약: 계층적 Map-Reduce 요약 또는 분량 축약
- 문서질의응답: 업로드한 문서(들)를 RAG 로 LLM 과 자유 대화
- 법률검색: 법령 FAISS 벡터 DB 기반 RAG 질의응답
- PDF변환: Word/PPT 일괄 PDF 변환
- 보고서작성: AI 자동 보고서 작성
- 메일분석: Outlook 연동
- 규제동향: 금감원·한은·금융위 보도자료 LLM 요약
- DB관리: 법령별 FAISS 벡터 DB 구축 (관리자 전용)

한국어로 친절하게 답변하세요."""

_HOME_SUGGESTIONS = [
    ("문서 복합 분석은 어떻게 쓰나요?",
     "DOCX/PDF/HWP 업로드 → 오타·논리·스타일 검사",
     "문서 복합 분석 기능 사용법 알려줘"),
    ("법률 검색의 작동 원리",
     "RAG 파이프라인 + 벡터 검색",
     "법률 검색이 어떻게 동작하는지 설명해줘"),
    ("PDF 변환 한꺼번에 처리하려면?",
     "Word/PPT 일괄 변환",
     "PDF 일괄 변환 방법"),
    ("규제 동향은 어디서 가져오나요?",
     "금감원·한은·금융위 보도자료",
     "규제 동향 출처와 수집 주기 알려줘"),
]


# ──────────────────────────────────────────────────────────────────────────────
# Sidebar (모노크롬 라이트, 224px)
# ──────────────────────────────────────────────────────────────────────────────
def _nav_item_html(icon: str, label: str) -> str:
    return (
        f'<span class="material-symbols-outlined nav-icon">{icon}</span>'
        f'<span class="nav-label">{label}</span>'
    )


# ──────────────────────────────────────────────────────────────────────────────
# Sidebar — Vue 컴포넌트 nest 잔상 제거를 위해 정적 HTML 단일 블록 + JS 위임 방식
#
# 기존: 각 nav-item을 개별 ui.element('div')로 mount → 각각 Vue 컴포넌트 인스턴스
#       발생, 동적 inline style이 cascade에서 우리 CSS를 이기는 잔상 문제
# 신규: 사이드바 내부 HTML 전체를 단일 ui.html() 정적 블록으로 렌더 → DOM 구조가
#       정적이라 Vue/Quasar가 끼어들 여지 없음. 클릭은 JS event delegation 후
#       hidden NiceGUI 버튼을 클릭하여 Python 콜백 트리거.
# ──────────────────────────────────────────────────────────────────────────────

# 네비게이션 항목 메타데이터 (key, label, icon, group)
_NAV_HOME  = ('home',           '홈',            'home',          None)
_NAV_LLM   = [
    ('analysis', '문서분석', 'description'),
    ('summary',  '문서요약', 'summarize'),
    ('qa',       '문서질의응답', 'forum'),
    ('legal',    '법률검색', 'gavel'),
]
_NAV_BIZ   = [
    ('convert',    'PDF 변환', 'picture_as_pdf'),
    ('reporting',  '보고서',   'assignment'),
    ('outlook',    '메일분석', 'mail'),
    ('regulatory', '규제동향', 'monitoring'),
]
_NAV_DASH  = [
    ('risk_dashboard',   'Risk DashBoard',          'monitor_heart'),
    ('risk_indicator',   'Risk Indicator Dashboard','insights'),
]
_NAV_ADMIN = ('admin', 'DB 관리', 'settings')
_NAV_AGENT = ('agent', 'AI 에이전트', 'smart_toy')

# LLM 백엔드가 필요한 탭 — 미연결 시 진입하면 안내 팝업을 띄운다.
_LLM_TAB_KEYS = {'home', 'analysis', 'summary', 'qa', 'legal', 'outlook', 'regulatory', 'agent'}


def _build_sidebar_nav_html() -> str:
    """사이드바 내부 HTML 정적 블록 생성 (로고 + 모든 nav-item + 그룹 라벨/토글/sub)."""
    parts = [
        '<div class="sidebar-logo">'
        '<span class="logo-mark">IW</span>'
        '<span class="logo-text">Integrated Work Platform</span>'
        '<span class="beta-tag">BETA</span>'
        '</div>',

        # 홈
        f'<div class="nav-item active" data-nav-key="{_NAV_HOME[0]}">'
        f'{_nav_item_html(_NAV_HOME[2], _NAV_HOME[1])}'
        f'</div>',

        # AI 에이전트 (채팅 기반 앱 제어 — PoC)
        f'<div class="nav-item" data-nav-key="{_NAV_AGENT[0]}">'
        f'{_nav_item_html(_NAV_AGENT[2], _NAV_AGENT[1])}'
        f'</div>',

        # LLM 그룹
        '<div class="nav-group-label" data-group-label="llm">LLM 기능</div>',
        '<div class="nav-item expanded" data-group-toggle="llm" style="cursor:pointer;">'
        '<span class="material-symbols-outlined nav-icon">smart_toy</span>'
        '<span class="nav-label">LLM 도구</span>'
        '<span class="material-symbols-outlined nav-chev">chevron_right</span>'
        '</div>',
        '<div class="nav-sub open" data-group-sub="llm">',
    ]
    for key, label, icon in _NAV_LLM:
        parts.append(
            f'<div class="nav-item" data-nav-key="{key}">'
            f'{_nav_item_html(icon, label)}'
            f'</div>'
        )
    parts.append('</div>')

    # 업무 그룹
    parts.append('<div class="nav-group-label" data-group-label="business">업무</div>')
    for key, label, icon in _NAV_BIZ:
        parts.append(
            f'<div class="nav-item" data-nav-key="{key}">'
            f'{_nav_item_html(icon, label)}'
            f'</div>'
        )

    # DashBoard 그룹
    parts.append('<div class="nav-group-label" data-group-label="dashboard">DashBoard</div>')
    parts.append(
        '<div class="nav-item expanded" data-group-toggle="dashboard" style="cursor:pointer;">'
        '<span class="material-symbols-outlined nav-icon">dashboard</span>'
        '<span class="nav-label">DashBoard</span>'
        '<span class="material-symbols-outlined nav-chev">chevron_right</span>'
        '</div>'
    )
    parts.append('<div class="nav-sub open" data-group-sub="dashboard">')
    for key, label, icon in _NAV_DASH:
        parts.append(
            f'<div class="nav-item" data-nav-key="{key}">'
            f'{_nav_item_html(icon, label)}'
            f'</div>'
        )
    parts.append('</div>')

    # 관리자
    parts.append('<div class="nav-group-label" data-group-label="admin">관리자</div>')
    parts.append(
        f'<div class="nav-item" data-nav-key="{_NAV_ADMIN[0]}">'
        f'{_nav_item_html(_NAV_ADMIN[2], _NAV_ADMIN[1])}'
        f'</div>'
    )

    return '\n'.join(parts)


class _NavProxy:
    """nav_elements / nav_groups 호환용 가벼운 proxy.

    실제 DOM은 정적 HTML이므로 `.visible` setter가 JS를 통해 display 토글.
    construction 시점에 client를 캐싱하여 background task에서 호출돼도
    slot 컨텍스트 의존 없이 작동.
    """
    def __init__(self, selector: str):
        self._selector = selector
        self._visible = True
        # main_page() 호출 시점의 client를 캐싱 (slot 컨텍스트가 살아 있을 때)
        try:
            from nicegui import context as _ctx
            self._client = _ctx.context.client
        except Exception:
            self._client = None

    @property
    def visible(self) -> bool:
        return self._visible

    @visible.setter
    def visible(self, v: bool) -> None:
        self._visible = bool(v)
        disp = '' if v else 'none'
        sel = self._selector.replace("'", "\\'")
        code = (
            f"document.querySelectorAll('{sel}').forEach(el => "
            f"el.style.display = {repr(disp)});"
        )
        # 캐시된 client 직접 사용 (background task에서도 안전)
        if self._client is not None:
            try:
                self._client.run_javascript(code)
                return
            except Exception:
                pass
        # fallback — slot 컨텍스트가 있다면 ui.run_javascript 사용
        try:
            ui.run_javascript(code)
        except Exception:
            pass

    def classes(self, *args, **kwargs):
        """admin_panel 호환 stub. switch_tab의 classes(remove='active')/(add='active')는
        switch_tab 자체가 JS로 처리하므로 여기서는 무시."""
        return self


# ──────────────────────────────────────────────────────────────────────────────
# 메인 페이지
# ──────────────────────────────────────────────────────────────────────────────
@ui.page('/')
def main_page(request: Request):
    inject_global_css()
    # LLM 미연결 시 비활성 버튼 시각 처리
    ui.add_head_html(
        '<style>.is-disabled{opacity:.45;pointer-events:none;cursor:not-allowed;}</style>'
    )
    _msm.load()   # 세션마다 최신 메뉴 상태 로드

    # LLM 백엔드 가용 여부 (탭 진입 팝업·버튼 비활성화에 사용)
    _llm_ok = llm_status.is_available()
    _llm_notice_shown = {'v': False}   # 탭 진입 안내 팝업 1회 제어

    # ── 사용자 식별 (접속 IP 기반 — 이니셜 입력 절차 제거) ────────────────────
    # 접속 IP를 식별자로 사용한다. config.json 의 ip_user_map 에 IP→이름 매핑이
    # 있으면 이름으로, 없으면 IP 문자열 자체로 활동 로그를 태깅한다.
    client_ip = _client_ip(request)
    user_initials = _IP_USER_MAP.get(client_ip, client_ip) or client_ip
    set_current_user(user_initials)
    # 이 클라이언트 연결에 사용자 등록 → 이후 버튼/타이머 등 별도 컨텍스트에서
    # 발생하는 로그도 USER 가 "-"(null) 로 빠지지 않고 자동 태깅된다.
    try:
        from nicegui import context as _ctx
        _client_obj = _ctx.client
        register_client_user(_client_obj.id, user_initials)
        _client_obj.on_disconnect(
            lambda cid=_client_obj.id: unregister_client_user(cid)
        )
    except Exception as _e:
        log.debug("클라이언트 사용자 등록 실패: %s", _e)

    # 세션별 업로드 폴더 — 멀티유저 충돌 방지 + 일괄 정리 용이
    # IP/이름에 경로 비허용 문자가 있을 수 있어 안전한 라벨로 정규화
    _safe_label = re.sub(r'[^0-9A-Za-z가-힣_.-]', '_', str(user_initials)) or 'anon'
    session_dir = f"{_safe_label}_{uuid.uuid4().hex[:8]}"

    state = {
        'file_path': None,
        'file_name': None,
        'raw_text': '',
        'suffix': None,
        'summary_file_path': None,
        'summary_file_name': None,
        'current_tab': 'home',
        'selected_model_id': _DEFAULT_MODEL,
        'home_history': [],
        'llm_open': True,
        'user_initials': user_initials,
        'session_dir': session_dir,
    }

    log.info("페이지 진입 (user=%s, ip=%s, session_dir=%s)",
             user_initials, client_ip, session_dir)

    # ──────────────────────────────────────────────────────────────────────
    # SIDEBAR — 정적 HTML 블록 + 숨겨진 트리거 버튼 + JS event delegation
    # ──────────────────────────────────────────────────────────────────────
    # 모든 nav-key
    _ALL_NAV_KEYS = (
        ['home', 'agent']
        + [k for k, _, _ in _NAV_LLM]
        + [k for k, _, _ in _NAV_BIZ]
        + [k for k, _, _ in _NAV_DASH]
        + ['admin']
    )

    # nav_elements: admin_panel과의 API 호환을 위한 proxy (실제 DOM은 정적 HTML)
    nav_elements: dict = {
        k: _NavProxy(f'.sidebar [data-nav-key="{k}"]') for k in _ALL_NAV_KEYS
    }

    with ui.element('aside').classes('sidebar'):
        # ── 정적 HTML 블록: 로고 + 모든 nav-item + 그룹 라벨/토글/sub ────
        ui.html(_build_sidebar_nav_html(), sanitize=False)

        # ── Footer — 모델 선택 + 현재 사용자 표시 ──────────────────────────
        with ui.element('div').classes('sidebar-footer'):
            ui.html('<div class="footer-label">LLM 모델</div>')
            model_select = ui.select(
                options=list(MODEL_OPTIONS.keys()),
                value=_DEFAULT_MODEL,
            ).props(
                'dense outlined hide-bottom-space dark options-dense '
                'behavior="menu" popup-content-class="model-select-menu"'
            ).classes('model-select-q w-full')

            def _on_model_change(e):
                set_current_user(state.get('user_initials', '-'))
                state['selected_model_id'] = e.args if isinstance(e.args, str) else model_select.value
                log.info("모델 변경: %s", state['selected_model_id'])

            model_select.on('update:model-value', _on_model_change)

            # 사용자 칩 (접속 IP 기반 자동 식별 — 수동 로그인/로그아웃 없음)
            user_chip = ui.element('div').style(
                'display:flex;align-items:center;gap:8px;margin-top:10px;'
                'padding:6px 8px;background:rgba(255,255,255,0.05);border-radius:8px;'
                'font-size:11.5px;'
            )
            with user_chip:
                ui.html(
                    '<span class="material-symbols-outlined" '
                    'style="font-size:14px;color:var(--text-3, #9ca3af);">person</span>'
                    f'<span style="color:var(--text-2, #d4d4d4);flex:1;" '
                    f'title="접속 IP: {_html.escape(client_ip)}">'
                    f'{_html.escape(user_initials)}</span>'
                )

    # ── Hidden 트리거 버튼: 각 nav-key에 대해 Python 콜백 연결 ────────────
    # JS event delegation이 nav-item 클릭 → 해당 트리거 버튼 click() 호출 →
    # NiceGUI on('click') 핸들러 발화 → switch_tab(key) 실행.
    nav_triggers: dict = {}
    with ui.element('div').style('display:none;') as trigger_container:
        trigger_container.props('aria-hidden=true')
        for _k in _ALL_NAV_KEYS:
            _btn = ui.element('button').props(f'id=_nav_trigger_{_k} type=button')
            nav_triggers[_k] = _btn

    # nav_groups (admin_panel 호환 proxy)
    nav_group_proxies = {
        'llm': {
            'label':  _NavProxy('.sidebar [data-group-label="llm"]'),
            'toggle': _NavProxy('.sidebar [data-group-toggle="llm"]'),
            'sub':    _NavProxy('.sidebar [data-group-sub="llm"]'),
        },
        'business': {
            'label':  _NavProxy('.sidebar [data-group-label="business"]'),
        },
        'dashboard': {
            'label':  _NavProxy('.sidebar [data-group-label="dashboard"]'),
            'toggle': _NavProxy('.sidebar [data-group-toggle="dashboard"]'),
            'sub':    _NavProxy('.sidebar [data-group-sub="dashboard"]'),
        },
    }

    # ── JS event delegation: 사이드바 클릭 라우터 ────────────────────────
    # · [data-group-toggle] 클릭 → 해당 sub.open 토글 + 토글 자체 .expanded 토글
    # · [data-nav-key]      클릭 → hidden 트리거 #_nav_trigger_<key> .click()
    ui.add_body_html('''
<script>
(function(){
  function bindSidebar(){
    const sb = document.querySelector('aside.sidebar');
    if (!sb) { setTimeout(bindSidebar, 100); return; }
    if (sb.dataset.delegated === '1') return;
    sb.dataset.delegated = '1';
    sb.addEventListener('click', function(e){
      const toggle = e.target.closest('[data-group-toggle]');
      if (toggle && sb.contains(toggle)) {
        const g = toggle.getAttribute('data-group-toggle');
        const sub = sb.querySelector('[data-group-sub="' + g + '"]');
        if (sub) sub.classList.toggle('open');
        toggle.classList.toggle('expanded');
        e.stopPropagation();
        return;
      }
      const item = e.target.closest('[data-nav-key]');
      if (item && sb.contains(item)) {
        const k = item.getAttribute('data-nav-key');
        const trig = document.getElementById('_nav_trigger_' + k);
        if (trig) trig.click();
      }
    });
    console.info('[IPM] sidebar click delegation bound');
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindSidebar);
  } else {
    bindSidebar();
  }
})();
</script>
''')

    # ──────────────────────────────────────────────────────────────────────
    # MAIN AREA
    # ──────────────────────────────────────────────────────────────────────
    panels: dict = {}
    switch_tab_ref: list = [None]   # switch_tab 정의 후 채워짐

    with ui.element('main').classes('main-area'):

        # ── HOME ──────────────────────────────────────────────────────────
        panel_home = ui.element('div').classes('panel')
        panels['home'] = panel_home
        with panel_home:
            with ui.element('div').classes('page-head'):
                ui.html(
                    '<div class="titles">'
                    '<div class="page-title">홈</div>'
                    '<div class="page-subtitle">플랫폼 사용법과 기능을 안내해 드립니다.</div>'
                    '</div>'
                )

            chat_wrap = ui.element('div').classes('chat-wrap')
            with chat_wrap:
                empty_state = ui.element('div').classes('chat-empty')
                with empty_state:
                    ui.html(
                        '<div class="empty-mark">'
                        '<span class="material-symbols-outlined">auto_awesome</span>'
                        '</div>'
                        '<h2>무엇을 도와드릴까요?</h2>'
                        '<p>통합업무플랫폼은 문서 분석·요약, 법률 검색, 보고서 작성, '
                        '규제 동향 모니터링 등을 한 곳에서 제공합니다. 궁금한 기능을 '
                        '자연어로 질문해 보세요.</p>'
                    )
                    sugg_row = ui.element('div').classes('suggestion-grid')

                scroll_area = ui.element('div').classes('chat-scroll').style('display:none;')
                with scroll_area:
                    chat_inner = ui.element('div').classes('chat-inner')

                # ── Composer ───────────────────────────────────────────
                with ui.element('div').classes('composer-wrap'):
                    with ui.element('div').classes('composer'):
                        home_input = ui.textarea(
                            placeholder='플랫폼 기능에 대해 무엇이든 물어보세요…',
                        ).props('borderless autogrow rows=1 dense').classes('flex-1')

                        with ui.element('div').classes('composer-actions'):
                            attach_btn = ui.element('button').classes('icon-btn')
                            attach_btn.props('title="파일 첨부"')
                            with attach_btn:
                                ui.html('<span class="material-symbols-outlined">attach_file</span>')

                            send_btn = ui.element('button').classes('send-btn')
                            send_btn.props('title="전송 (Enter)"')
                            with send_btn:
                                ui.html('<span class="material-symbols-outlined">arrow_upward</span>')
                            _gate_llm_button(send_btn, native=True)

                    ui.html(
                        '<div class="composer-hint">'
                        '<span>Shift + Enter 줄바꿈</span>'
                        '<span><span class="kbd">Enter</span> 전송</span>'
                        '</div>'
                    )

                async def _home_send(msg_text: str = None):
                    if not llm_status.guard():
                        return
                    msg = (msg_text if msg_text is not None else home_input.value or '').strip()
                    if not msg:
                        return
                    home_input.value = ''
                    state['home_history'].append({'role': 'user', 'content': msg})

                    # 첫 메시지면 empty state 숨기고 채팅 영역 표시
                    empty_state.style('display:none;')
                    scroll_area.style('display:block;')

                    safe_msg = _html.escape(msg).replace('\n', '<br>')
                    with chat_inner:
                        ui.html(
                            '<div class="msg user">'
                            '<div class="msg-role">'
                            '<span class="avatar">나</span><span>사용자</span>'
                            '</div>'
                            f'<div class="msg-body">{safe_msg}</div>'
                            '</div>'
                        )
                        stream_bubble = ui.html(
                            '<div class="msg ai">'
                            '<div class="msg-role">'
                            '<span class="avatar">AI</span><span>어시스턴트</span>'
                            '</div>'
                            '<div class="msg-body"><span class="chat-cursor"></span></div>'
                            '</div>'
                        )

                    reply_parts: list[str] = []
                    reply = ''
                    try:
                        from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
                        home_llm = create_llm(model_id=state.get('selected_model_id'))
                        msgs = [SystemMessage(content=_HOME_SYSTEM_PROMPT)]
                        for h in state['home_history'][-20:]:
                            msgs.append(
                                HumanMessage(content=h['content']) if h['role'] == 'user'
                                else AIMessage(content=h['content'])
                            )

                        async for chunk in home_llm.astream(msgs):
                            token = chunk.content
                            if token:
                                reply_parts.append(token)
                                current = _html.escape(''.join(reply_parts)).replace('\n', '<br>')
                                stream_bubble.content = (
                                    '<div class="msg ai">'
                                    '<div class="msg-role">'
                                    '<span class="avatar">AI</span><span>어시스턴트</span>'
                                    '</div>'
                                    f'<div class="msg-body">{current}<span class="chat-cursor"></span></div>'
                                    '</div>'
                                )
                                await asyncio.sleep(0)

                        reply = ''.join(reply_parts)
                        safe_reply = _html.escape(reply).replace('\n', '<br>')
                        stream_bubble.content = (
                            '<div class="msg ai">'
                            '<div class="msg-role">'
                            '<span class="avatar">AI</span><span>어시스턴트</span>'
                            '</div>'
                            f'<div class="msg-body">{safe_reply}</div>'
                            '</div>'
                        )
                    except Exception as exc:
                        stream_bubble.content = (
                            '<div class="msg ai">'
                            '<div class="msg-role">'
                            '<span class="avatar">AI</span><span>어시스턴트</span>'
                            '</div>'
                            f'<div class="msg-body" style="color:#b91c1c;">[오류] {_html.escape(str(exc))}</div>'
                            '</div>'
                        )
                        reply = f'[오류] {exc}'

                    state['home_history'].append({'role': 'assistant', 'content': reply})
                    if len(state['home_history']) > 50:
                        state['home_history'] = state['home_history'][-30:]

                    # ui.run_javascript는 slot 컨텍스트 필요 — 명시적으로 진입
                    with chat_inner:
                        ui.run_javascript(
                            'document.querySelectorAll(".chat-scroll").forEach(s => '
                            '{ s.scrollTop = s.scrollHeight; });'
                        )

                # 추천 카드 클릭 → 즉시 전송
                with sugg_row:
                    for title, sub, prompt in _HOME_SUGGESTIONS:
                        b = ui.element('button').classes('suggestion')
                        with b:
                            ui.html(
                                f'<span class="s-title">{_html.escape(title)}</span>'
                                f'<span class="s-sub">{_html.escape(sub)}</span>'
                            )
                        b.on('click', lambda _e, p=prompt: asyncio.create_task(_home_send(p)))
                        _gate_llm_button(b, native=True)

                # Enter 키 전송
                async def _home_enter_key(e):
                    if not (isinstance(e.args, dict) and e.args.get('shiftKey')):
                        await _home_send()

                home_input.on('keydown.enter', _home_enter_key)
                send_btn.on('click', lambda _e: asyncio.create_task(_home_send()))

        # ── AI 에이전트 콘솔 (PoC) ────────────────────────────────────────
        panel_agent = ui.element('div').classes('panel')
        panels['agent'] = panel_agent
        panel_agent.style('display:none;')
        build_agent_panel(panel_agent, state, create_llm, _config)


        # ── 문서 복합 분석 ────────────────────────────────────────────────
        panel_analysis = ui.element('div').classes('panel')
        panels['analysis'] = panel_analysis
        panel_analysis.style('display:none;')
        with panel_analysis:
            with ui.element('div').classes('page-head'):
                ui.html(
                    '<div class="titles">'
                    '<div class="page-title">문서 복합 분석</div>'
                    '<div class="page-subtitle">DOCX·PDF·HWP를 업로드하고 오타·논리·스타일을 검사합니다.</div>'
                    '</div>'
                )

            # 파일 목록: [{path, name, suffix, size_kb, raw_text, analyses}]
            # 각 file_info['analyses'] = {
            #     'proofreading': {'annotated_html': str, 'errors': list},
            #     'logic':        {'annotated_html': str, 'errors': list},
            #     'style':        {'annotated_html': str, 'errors': list},
            # }
            analysis_files: list[dict] = []
            analysis_sel: list[int] = [-1]    # 선택된 파일 인덱스 (mutable)
            analysis_active_tab: list[str] = ['proofreading']  # 현재 우측 탭 (mutable)
            arefs: dict = {}

            # 분석 유형 메타 (key, label, badge fg/bg color)
            ANALYSIS_META = [
                ('proofreading', '오타 검수',             '#16a34a', '#dcfce7'),
                ('logic',        '논리 검증',             '#7c3aed', '#ede9fe'),
                ('style',        'Business Tone&Manner',  '#0284c7', '#e0f2fe'),
            ]
            ANALYSIS_LABEL = {k: lbl for k, lbl, _fg, _bg in ANALYSIS_META}

            def _file_badges_html(fi: dict) -> str:
                """파일 카드 우측에 표시할 '분석됨' 뱃지들 (유형별)."""
                an = fi.get('analyses') or {}
                parts = []
                for key, label, fg, bg in ANALYSIS_META:
                    if an.get(key):
                        parts.append(
                            f'<span title="{label} 완료" style="font-size:10px;font-weight:600;'
                            f'color:{fg};background:{bg};padding:2px 6px;border-radius:10px;'
                            f'flex-shrink:0;">{label}</span>'
                        )
                return ''.join(parts)

            with ui.element('div').classes('split'):

                # ── LEFT pane — 업로드 + 파일 목록 + 미리보기 ─────────────
                with ui.element('div').classes('pane'):
                    with ui.element('div').classes('pane-head'):
                        ui.html(
                            '<span class="material-symbols-outlined" '
                            'style="font-size:18px;color:var(--text-2);">upload_file</span>'
                            '<div style="flex:1;">'
                            '<h3>파일 업로드 및 목록</h3>'
                            '<div class="pane-sub">.docx · .pdf · .hwp · .hwpx (다중 업로드 가능)</div>'
                            '</div>'
                        )
                    with ui.element('div').classes('pane-body').style('display:flex; flex-direction:column;'):
                        # 업로드 영역은 sticky로 고정 — 분석 후에도 항상 화면에 보임
                        with ui.element('div').classes('upload-sticky w-full'):
                            arefs['upload'] = ui.upload(
                                auto_upload=True,
                                multiple=True,
                            ).props('accept=.docx,.pdf,.hwp,.hwpx flat bordered').classes('w-full')

                        arefs['file_list'] = ui.column().classes('w-full').style(
                            'gap:4px; margin-top:10px; margin-bottom:2px;'
                        )
                        arefs['preview'] = ui.html(
                            '<div class="preview-text">'
                            '<span style="color:var(--text-4);">파일을 업로드하면 본문 미리보기가 표시됩니다.</span>'
                            '</div>'
                        )

                # ── RIGHT pane — AI 분석 ───────────────────────────────
                with ui.element('div').classes('pane'):
                    with ui.element('div').classes('pane-head'):
                        ui.html(
                            '<span class="material-symbols-outlined" '
                            'style="font-size:18px;color:var(--text-2);">psychology</span>'
                            '<div style="flex:1;">'
                            '<h3>AI 분석 실행</h3>'
                            '<div class="pane-sub">섹션 단위로 LLM 검사가 진행됩니다</div>'
                            '</div>'
                        )
                    with ui.element('div').classes('pane-body'):
                        analysis_llm_chunk = ui.checkbox(
                            'LLM 의미 단위 청킹 사용 (OFF: 볼드체 기반)',
                            value=True,
                        ).classes('check-row')

                        ui.html(
                            '<div style="font-size:11px;font-weight:600;color:var(--text-3);'
                            'letter-spacing:.03em;text-transform:uppercase;margin-bottom:8px;">'
                            '선택 파일 분석</div>'
                        )
                        with ui.element('div').classes('action-row'):
                            btn_proof = ui.button('오타 검수').classes('btn-primary-mono')
                            btn_style = ui.button('Business Tone&Manner').classes('btn-primary-mono')

                        ui.html('<div class="divider" style="margin:12px 0;"></div>')

                        ui.html(
                            '<div style="font-size:11px;font-weight:600;color:var(--text-3);'
                            'letter-spacing:.03em;text-transform:uppercase;margin-bottom:8px;">'
                            '논리 검증</div>'
                        )
                        with ui.element('div').classes('action-row'):
                            btn_logic_single = ui.button('파일별 논리검증').classes('btn-primary-mono')
                            btn_logic_all    = ui.button('전체 논리검증').classes('btn-primary-mono')

                        status_label = ui.html('')

                        # ── 결과 탭 (오타 검수 / 논리 검증 / Business Tone&Manner) ──
                        ui.html('<div class="divider" style="margin:12px 0 8px;"></div>')
                        ui.html(
                            '<div style="font-size:11px;font-weight:600;color:var(--text-3);'
                            'letter-spacing:.03em;text-transform:uppercase;margin-bottom:8px;">'
                            '분석 결과</div>'
                        )
                        with ui.element('div').style(
                            'display:flex;gap:4px;border-bottom:1px solid var(--border);'
                            'margin-bottom:10px;'
                        ) as _tabs_row:
                            arefs['tab_row'] = _tabs_row
                            arefs['tab_btns'] = {}
                            for _k, _label, _fg, _bg in ANALYSIS_META:
                                _tb = ui.element('button').style(
                                    'background:transparent;border:none;border-bottom:2px solid transparent;'
                                    'padding:8px 12px;cursor:pointer;font-size:13px;font-weight:500;'
                                    'color:var(--text-3);transition:all .15s;'
                                )
                                with _tb:
                                    ui.html(f'<span>{_label}</span>')
                                arefs['tab_btns'][_k] = _tb
                                _tb.on('click', lambda _e, kk=_k: _switch_analysis_tab(kk))

                        # 미리보기 5000자 제한 안내
                        ui.html(
                            '<div style="font-size:11px;color:var(--text-4);'
                            'margin-bottom:8px;line-height:1.5;">'
                            '※ 좌측 미리보기는 앞 5,000자만 표시되지만, 분석은 문서 전체에 대해 수행됩니다. '
                            '5,000자를 넘는 위치의 수정 사항은 아래 결과 카드의 원문/수정 텍스트로 확인하세요.'
                            '</div>'
                        )
                        results_container = ui.column().classes('w-full')

            def _switch_analysis_tab(tab_key: str):
                """우측 탭 전환: active tab 변경 후 좌측 미리보기와 우측 결과 갱신."""
                if tab_key not in ANALYSIS_LABEL:
                    return
                analysis_active_tab[0] = tab_key
                # 탭 버튼 시각 상태 갱신
                for _k, _btn in arefs['tab_btns'].items():
                    if _k == tab_key:
                        _btn.style(
                            'background:transparent;border:none;'
                            'border-bottom:2px solid var(--text);'
                            'padding:8px 12px;cursor:pointer;font-size:13px;font-weight:600;'
                            'color:var(--text);transition:all .15s;'
                        )
                    else:
                        _btn.style(
                            'background:transparent;border:none;'
                            'border-bottom:2px solid transparent;'
                            'padding:8px 12px;cursor:pointer;font-size:13px;font-weight:500;'
                            'color:var(--text-3);transition:all .15s;'
                        )
                # 현재 선택된 파일 기준으로 좌·우 갱신
                if 0 <= analysis_sel[0] < len(analysis_files):
                    _render_for_tab(analysis_files[analysis_sel[0]])

            def _render_for_tab(fi: dict):
                """선택된 파일의 현재 active 탭 결과를 좌(미리보기)·우(결과)에 그림."""
                tab_key = analysis_active_tab[0]
                an = (fi.get('analyses') or {}).get(tab_key)
                # 좌측 미리보기: 해당 탭의 annotated HTML 우선, 없으면 원문
                if an and an.get('annotated_html'):
                    arefs['preview'].content = (
                        '<div class="preview-text">'
                        + an['annotated_html'] + '</div>'
                    )
                else:
                    arefs['preview'].content = (
                        '<div class="preview-text">'
                        + _html.escape(fi.get('raw_text') or '') + '</div>'
                    )
                # 우측 결과
                if an and an.get('errors') is not None:
                    render_results(results_container, an['errors'])
                else:
                    results_container.clear()
                    with results_container:
                        ui.html(
                            '<div style="color:var(--text-4);font-size:13px;'
                            'text-align:center;padding:20px;background:var(--bg-elev);'
                            'border:1px solid var(--border);border-radius:var(--radius);">'
                            f'[{_html.escape(fi["name"])}] '
                            f'{ANALYSIS_LABEL[tab_key]} 결과가 아직 없습니다. '
                            '우측 상단 분석 버튼으로 실행하세요.'
                            '</div>'
                        )

            # ── 파일 목록 렌더링 ──────────────────────────────────────────
            def _refresh_file_list():
                arefs['file_list'].clear()
                with arefs['file_list']:
                    for i, fi in enumerate(analysis_files):
                        is_sel = (i == analysis_sel[0])
                        border_extra = (
                            'border-color:var(--accent);background:var(--bg-elev);'
                            if is_sel else ''
                        )
                        row = ui.element('div').style(
                            f'display:flex;align-items:center;gap:8px;padding:8px 10px;'
                            f'border:1px solid var(--border);border-radius:var(--radius);'
                            f'cursor:pointer;font-size:13px;{border_extra}'
                        )
                        with row:
                            badge_html = _file_badges_html(fi)
                            ui.html(
                                '<span class="material-symbols-outlined" '
                                'style="font-size:16px;color:var(--text-3);flex-shrink:0;">'
                                'description</span>'
                                + f'<span style="flex:1;overflow:hidden;text-overflow:ellipsis;'
                                f'white-space:nowrap;font-weight:500;color:var(--text);">'
                                f'{_html.escape(fi["name"])}</span>'
                                + badge_html
                                + f'<span style="font-size:11px;color:var(--text-4);flex-shrink:0;'
                                f'margin-left:4px;">{fi["size_kb"]:.1f} KB</span>'
                            )
                            # 삭제 버튼 (.stop 모디파이어로 부모 row 클릭 차단)
                            del_btn = ui.element('button').style(
                                'background:transparent;border:none;cursor:pointer;'
                                'color:var(--text-4);padding:2px 4px;flex-shrink:0;'
                                'display:flex;align-items:center;'
                            ).props('title="목록에서 제거"')
                            with del_btn:
                                ui.html('<span class="material-symbols-outlined" '
                                        'style="font-size:16px;">close</span>')
                            idx_capture_del = i
                            del_btn.on(
                                'click.stop',
                                lambda _e, idx=idx_capture_del: _remove_file(idx),
                            )
                        idx_capture = i
                        row.on('click', lambda _e, idx=idx_capture: _select_file(idx))

            def _select_file(idx: int):
                if idx < 0 or idx >= len(analysis_files):
                    return
                analysis_sel[0] = idx
                fi = analysis_files[idx]
                state['file_path'] = fi['path']
                state['file_name'] = fi['name']
                state['suffix']    = fi['suffix']
                state['raw_text']  = fi['raw_text']
                # 좌·우 영역은 현재 active 탭 기준으로 렌더
                _render_for_tab(fi)
                _refresh_file_list()

            def _remove_file(idx: int):
                if idx < 0 or idx >= len(analysis_files):
                    return
                fi = analysis_files.pop(idx)
                try:
                    if fi.get('path') and os.path.exists(fi['path']):
                        os.remove(fi['path'])
                except Exception:
                    pass
                if analysis_sel[0] == idx:
                    analysis_sel[0] = min(idx, len(analysis_files) - 1)
                    if analysis_sel[0] >= 0:
                        _select_file(analysis_sel[0])
                    else:
                        arefs['preview'].content = (
                            '<div class="preview-text">'
                            '<span style="color:var(--text-4);">파일을 업로드하면 본문 미리보기가 표시됩니다.</span>'
                            '</div>'
                        )
                elif analysis_sel[0] > idx:
                    analysis_sel[0] -= 1
                _refresh_file_list()

            # ── 업로드 핸들러 ─────────────────────────────────────────────
            async def handle_upload_analysis(e: events.UploadEventArguments):
                set_current_user(state.get('user_initials', '-'))
                try:
                    f = e.file
                    name = f.name
                    suffix = os.path.splitext(name.lower())[1] or '.docx'
                    data = await f.read()
                    upload_abs = os.path.normpath(os.path.join(
                        os.path.dirname(os.path.abspath(__file__)), '..',
                        _config.get('upload_dir', './uploads'), 'analysis',
                        state.get('session_dir', 'anon'),
                    ))
                    os.makedirs(upload_abs, exist_ok=True)
                    save_path = os.path.join(upload_abs, f'{uuid.uuid4().hex}_{name}')
                    with open(save_path, 'wb') as fp:
                        fp.write(data)
                    log.info('문서분석 업로드: %s (%.1f KB)', name, len(data) / 1024)

                    if suffix == '.pdf':
                        raw = await nicegui_run.io_bound(read_pdf, save_path)
                        if not (raw or '').strip():
                            # 텍스트 레이어가 없는 이미지/스캔 PDF → 분석 불가 안내
                            raw = (
                                '⚠ 이 PDF에는 추출 가능한 텍스트가 없습니다(이미지·스캔 문서로 보입니다).\n\n'
                                '텍스트 기반 PDF 또는 DOCX 파일을 올리거나, OCR로 텍스트를 인식시킨 뒤 '
                                '다시 업로드하면 분석할 수 있습니다.'
                            )
                            ui.notify(
                                f'[{name}] 텍스트가 없는 이미지/스캔 PDF로 보입니다. 분석이 제한됩니다.',
                                type='warning', position='top',
                            )
                            log.warning('문서분석: 텍스트 없는 이미지 PDF 업로드 — %s', name)
                    elif suffix == '.docx':
                        raw = await nicegui_run.io_bound(read_raw_docx, save_path)
                    else:
                        raw = f'[{name}] 미리보기 미지원 형식 — 분석 시 자동 추출됩니다.'

                    size_kb = len(data) / 1024
                    analysis_files.append({
                        'path': save_path, 'name': name,
                        'suffix': suffix, 'size_kb': size_kb, 'raw_text': raw,
                        'analyses': {},  # {type: {annotated_html, errors}}
                    })
                    _select_file(len(analysis_files) - 1)
                    arefs['upload'].reset()
                    ui.notify(f'{name} 업로드 완료', type='positive', position='top')
                except Exception as exc:
                    ui.notify(f'업로드 오류: {exc}', type='negative', position='top')

            arefs['upload'].on_upload(handle_upload_analysis)

            # ── 단일 파일 분석 헬퍼 ──────────────────────────────────────
            def _spinner_html(text: str) -> str:
                return (
                    '<div style="display:flex;align-items:center;gap:8px;'
                    'color:var(--text-3);font-size:13px;padding:8px 0;">'
                    '<span class="material-symbols-outlined" '
                    'style="font-size:16px;animation:spin 1.2s linear infinite;">'
                    f'progress_activity</span>{text}</div>'
                )

            async def _run_on_file(analysis_type: str, file_info: dict):
                """단일 파일 분석.

                짧은 문서(섹션 ≤5 또는 총 3,000자 이하):
                  → 전체를 하나의 API 호출로 처리 (방안 2) + astream 스트리밍 (방안 4)

                긴 문서:
                  → 모든 섹션을 asyncio.gather 로 동시에 처리 (방안 1)
                """
                chain_map = {
                    'proofreading': (get_proofreading_chain, '오타 검수'),
                    'logic':        (get_logical_error_chain, '논리 검증'),
                    'style':        (get_english_chain, 'Business Tone&Manner 분석'),
                }
                chain_func, msg = chain_map[analysis_type]
                file_label = _html.escape(file_info['name'])

                def _is_active() -> bool:
                    return (
                        0 <= analysis_sel[0] < len(analysis_files)
                        and analysis_files[analysis_sel[0]] is file_info
                    )

                def _commit(annotated_html: str, file_errors: list):
                    """결과를 파일 dict에 저장하고, 현재 active 뷰이면 UI도 갱신."""
                    file_info.setdefault('analyses', {})[analysis_type] = {
                        'annotated_html': annotated_html,
                        'errors': list(file_errors),
                    }
                    if _is_active() and analysis_active_tab[0] == analysis_type:
                        arefs['preview'].content = (
                            '<div class="preview-text">'
                            + annotated_html + '</div>'
                        )
                        render_results(results_container, file_errors)

                try:
                    if analysis_llm_chunk.value:
                        status_label.content = _spinner_html(
                            f'{msg} [{file_label}] — LLM 의미 단위 청킹 중… '
                            '(첫 단계: 문서 구조 분석)'
                        )
                        sections = await nicegui_run.io_bound(
                            read_file_with_llm_chunks, file_info['path'], _config
                        )
                    else:
                        status_label.content = _spinner_html(
                            f'{msg} [{file_label}] — 문서 파싱 중…'
                        )
                        from read_docx_util import read_file_sections
                        sections = await nicegui_run.io_bound(
                            read_file_sections, file_info['path']
                        )

                    if not sections:
                        _is_pdf = file_info.get('suffix') == '.pdf'
                        _detail = (
                            '이미지·스캔 PDF로 보입니다. 텍스트 레이어가 없어 분석할 수 없습니다 '
                            '(OCR로 변환 후 다시 시도하세요).'
                            if _is_pdf else '파일 형식·인코딩을 확인하세요.'
                        )
                        ui.notify(
                            f'[{file_info["name"]}] 텍스트를 추출할 수 없습니다. {_detail}',
                            type='warning', position='top',
                        )
                        status_label.content = (
                            f'<div style="color:#b45309;font-size:13px;padding:6px 0;">'
                            f'⚠ 텍스트를 추출할 수 없습니다. {_html.escape(_detail)}</div>'
                        )
                        return []

                    llm = create_llm(model_id=state.get('selected_model_id'))
                    chain = chain_func(llm)

                    total_chars = sum(len(s.get('content', '')) for s in sections)
                    use_single = (len(sections) <= 5 or total_chars <= 3000)
                    status_label.content = _spinner_html(
                        f'{msg} [{file_label}] — 청킹 완료 ({len(sections)}개 섹션) · LLM 분석 시작…'
                    )

                    # ── 방안 2 + 4: 단일 호출 + astream 스트리밍 ─────────
                    if use_single:
                        full_text = "\n\n".join(
                            f"[섹션: {s.get('title','제목 없음')}]\n{s.get('content','')}"
                            for s in sections
                        )
                        status_label.content = _spinner_html(
                            f'{msg} [{file_label}] — 스트리밍 수신 중…'
                        )

                        full_response = ""
                        recv_chars = 0
                        try:
                            async for chunk in chain.astream({"text": full_text}):
                                full_response += chunk
                                recv_chars += len(chunk)
                                # 80자마다 또는 초반부에 상태 갱신
                                if recv_chars < 40 or recv_chars % 80 < len(chunk):
                                    status_label.content = _spinner_html(
                                        f'{msg} [{file_label}] — {recv_chars}자 수신 중…'
                                    )
                        except Exception:
                            # astream 미지원 환경 → invoke 폴백
                            full_response = await nicegui_run.io_bound(
                                chain.invoke, {"text": full_text}
                            )

                        highlighted_text, errors = await nicegui_run.io_bound(
                            highlight_errors, full_text, full_response
                        )
                        safe_hl = escape_markdown_special_chars(highlighted_text)
                        annotated_html = textwrap.dedent(f"""
                            <div style="margin-bottom:20px;">
                                <div style="font-size:13px;font-weight:600;
                                            color:var(--text,#0a0a0a);margin-bottom:6px;
                                            border-bottom:1px solid var(--border,#e7e5e4);
                                            padding-bottom:4px;">전체 문서</div>
                                <div style="font-size:13.5px;color:var(--text-2,#404040);
                                            line-height:1.75;">{safe_hl}</div>
                            </div>
                        """).strip()
                        file_errors = [{'title': '전체 문서', 'errors': errors}] if errors else []
                        _commit(annotated_html, file_errors)
                        return file_errors

                    # ── 방안 1: 병렬 처리 (완료 순으로 부분 갱신) ────────
                    else:
                        total = len(sections)
                        status_label.content = _spinner_html(
                            f'{msg} [{file_label}] — {total}개 섹션 병렬 분석 중… (0/{total})'
                        )

                        async def _process_one(idx, section):
                            try:
                                result = await nicegui_run.io_bound(
                                    analyze_one_section, chain,
                                    section.get('title', '제목 없음'),
                                    section.get('content', ''),
                                )
                                return (idx, section, result, None)
                            except Exception as exc:
                                return (idx, section, None, exc)

                        # 원래 섹션 순서를 유지하기 위해 인덱스 배열에 결과 슬롯 보관
                        all_html_slots: list[str] = [''] * total
                        file_errors: list[dict] = []
                        done_count = 0

                        tasks = [
                            asyncio.create_task(_process_one(i, s))
                            for i, s in enumerate(sections)
                        ]

                        for fut in asyncio.as_completed(tasks):
                            idx, section, result, exc = await fut
                            done_count += 1
                            title = section.get('title', '제목 없음')
                            if exc is not None:
                                all_html_slots[idx] = (
                                    f'<p style="color:#b91c1c;">[{_html.escape(title)}] '
                                    f'Error: {type(exc).__name__}: {exc}</p>'
                                )
                            else:
                                section_html, errors = result
                                all_html_slots[idx] = section_html
                                if errors:
                                    file_errors.append({'title': title, 'errors': errors})

                            # 상태 + 부분 결과 실시간 표시
                            status_label.content = _spinner_html(
                                f'{msg} [{file_label}] — 진행 중 ({done_count}/{total}) · 최근 완료: {_html.escape(title)}'
                            )
                            _commit(''.join(all_html_slots), file_errors)

                        return file_errors

                except Exception as e:
                    ui.notify(f'분석 오류: {e}', type='negative', position='top')
                    return []

            async def run_analysis(analysis_type: str):
                if not llm_status.guard():
                    return
                set_current_user(state.get('user_initials', '-'))
                if not analysis_files:
                    ui.notify('파일을 먼저 업로드하세요.', type='warning', position='top')
                    return
                log.info('문서분석 시작 (type=%s)', analysis_type)

                # 오타 검수·스타일 교정은 단일 파일만 가능 — 다중 업로드 시 선택 팝업
                if analysis_type in ('proofreading', 'style') and len(analysis_files) > 1:
                    with ui.dialog() as file_dlg, ui.card().style(
                        'min-width:360px;max-width:480px;padding:20px;'
                        'background:var(--bg);border:1px solid var(--border);border-radius:12px;'
                    ):
                        ui.html(
                            '<div style="font-size:14px;font-weight:600;color:var(--text);'
                            'margin-bottom:12px;">분석할 파일을 선택하세요</div>'
                        )
                        for i, fi in enumerate(analysis_files):
                            def _pick(idx=i):
                                file_dlg.submit(idx)
                            with ui.element('div').style(
                                'display:flex;align-items:center;gap:8px;padding:8px 10px;'
                                'border:1px solid var(--border);border-radius:var(--radius);'
                                'cursor:pointer;margin-bottom:4px;transition:background .15s;'
                            ).on('click', _pick):
                                ui.html(
                                    '<span class="material-symbols-outlined" '
                                    'style="font-size:16px;color:var(--text-3);flex-shrink:0;">'
                                    'description</span>'
                                    f'<span style="font-size:13px;font-weight:500;color:var(--text);'
                                    f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
                                    f'{_html.escape(fi["name"])}</span>'
                                    f'<span style="font-size:11px;color:var(--text-4);'
                                    f'flex-shrink:0;margin-left:auto;">'
                                    f'{fi["size_kb"]:.1f} KB</span>'
                                )
                        ui.button('취소', on_click=lambda: file_dlg.submit(None)).classes('btn-primary-mono').style(
                            'margin-top:8px;width:100%;'
                        )

                    chosen_idx = await file_dlg
                    if chosen_idx is None:
                        return
                    target_fi = analysis_files[chosen_idx]
                else:
                    if analysis_sel[0] < 0:
                        ui.notify('목록에서 파일을 선택하세요.', type='warning', position='top')
                        return
                    target_fi = analysis_files[analysis_sel[0]]

                # 분석 직전: 해당 파일의 해당 유형 결과만 초기화 (다른 분석 결과는 보존)
                target_fi.setdefault('analyses', {}).pop(analysis_type, None)
                # 선택된 파일을 명시적으로 미리보기 대상으로 전환 + 해당 분석 탭으로 전환
                target_idx = analysis_files.index(target_fi) if target_fi in analysis_files else -1
                if target_idx >= 0:
                    analysis_sel[0] = target_idx
                _switch_analysis_tab(analysis_type)
                results_container.clear()
                status_label.content = (
                    '<div style="display:flex;align-items:center;gap:8px;'
                    'color:var(--text-3);font-size:13px;padding:8px 0;">'
                    '<span class="material-symbols-outlined" '
                    'style="font-size:16px;animation:spin 1.2s linear infinite;">'
                    f'progress_activity</span>{ANALYSIS_LABEL[analysis_type]} 중…</div>'
                )
                await _run_on_file(analysis_type, target_fi)
                # 분석 후 파일·미리보기 유지 (사용자가 X 버튼으로만 제거)
                _refresh_file_list()
                status_label.content = ''
                ui.notify(
                    f'{ANALYSIS_LABEL[analysis_type]} 완료 — 우측 탭에서 결과를 확인하세요.',
                    type='positive', position='top',
                )

            async def run_logic_all():
                if not llm_status.guard():
                    return
                set_current_user(state.get('user_initials', '-'))
                if not analysis_files:
                    ui.notify('파일을 먼저 업로드하세요.', type='warning', position='top')
                    return
                log.info('전체 논리검증 시작 (%d개 파일)', len(analysis_files))

                # 이미 논리 분석된 파일은 스킵 (analyses['logic'] 존재 여부)
                pending = [
                    fi for fi in analysis_files
                    if not (fi.get('analyses') or {}).get('logic')
                ]
                skipped = len(analysis_files) - len(pending)
                if not pending:
                    ui.notify(
                        '모든 파일에 논리 검증이 이미 완료되었습니다. '
                        '좌측 파일을 클릭하면 해당 결과로 전환됩니다.',
                        type='info', position='top',
                    )
                    return

                # 진행 시작 시점에 논리 탭으로 전환
                _switch_analysis_tab('logic')

                total_files = len(pending)
                for f_idx, fi in enumerate(pending):
                    status_label.content = (
                        '<div style="display:flex;align-items:center;gap:8px;'
                        'color:var(--text-3);font-size:13px;padding:8px 0;">'
                        '<span class="material-symbols-outlined" '
                        'style="font-size:16px;animation:spin 1.2s linear infinite;">'
                        f'progress_activity</span>'
                        f'전체 논리검증 ({f_idx + 1}/{total_files}) — '
                        f'{_html.escape(fi["name"])}'
                        + (f' (이미 분석된 {skipped}개 스킵)' if skipped else '')
                        + '</div>'
                    )
                    # 현재 분석 중인 파일을 좌측에서 강조 + 우측도 그 파일 결과로 전환
                    if fi in analysis_files:
                        _select_file(analysis_files.index(fi))
                    await _run_on_file('logic', fi)

                _refresh_file_list()
                status_label.content = ''
                msg = (f'전체 논리검증 완료 ({total_files}개 파일 분석'
                       + (f', {skipped}개 스킵' if skipped else '')
                       + ') — 좌측 파일을 클릭하면 결과로 전환됩니다.')
                ui.notify(msg, type='positive', position='top')

            btn_proof.on_click(lambda: run_analysis('proofreading'))
            btn_style.on_click(lambda: run_analysis('style'))
            btn_logic_single.on_click(lambda: run_analysis('logic'))
            btn_logic_all.on_click(run_logic_all)
            for _b in (btn_proof, btn_style, btn_logic_single, btn_logic_all):
                _gate_llm_button(_b)

            # 초기 탭(오타 검수) 활성화 시각 상태 설정
            _switch_analysis_tab('proofreading')

            # spinner keyframes
            ui.add_head_html('<style>@keyframes spin { to { transform: rotate(360deg); } }</style>')

        # ── 문서 요약 ─────────────────────────────────────────────────────
        panel_summary = ui.element('div').classes('panel')
        panels['summary'] = panel_summary
        panel_summary.style('display:none;')
        _build_summary_panel(panel_summary, state)

        # ── 문서 질의응답 ─────────────────────────────────────────────────
        panel_qa = ui.element('div').classes('panel')
        panels['qa'] = panel_qa
        panel_qa.style('display:none;')
        _build_qa_panel(panel_qa, state, create_llm)

        # ── PDF 변환 ──────────────────────────────────────────────────────
        panel_convert = ui.element('div').classes('panel')
        panels['convert'] = panel_convert
        panel_convert.style('display:none;')
        _build_convert_panel(panel_convert, state)

        # ── 보고서 ────────────────────────────────────────────────────────
        panel_reporting = ui.element('div').classes('panel')
        panels['reporting'] = panel_reporting
        panel_reporting.style('display:none;')
        with panel_reporting:
            build_reporting_panel(_config)

        # ── 법률 검색 ─────────────────────────────────────────────────────
        panel_legal = ui.element('div').classes('panel')
        panels['legal'] = panel_legal
        panel_legal.style('display:none;')
        with panel_legal:
            build_legal_panel(_config)

        # ── 메일 분석 ─────────────────────────────────────────────────────
        panel_outlook = ui.element('div').classes('panel')
        panels['outlook'] = panel_outlook
        panel_outlook.style('display:none;')
        with panel_outlook:
            def _llm_outlook(model_id=None):
                return create_llm(model_id=state.get('selected_model_id'))
            build_outlook_panel(_config, _llm_outlook)

        # ── 규제 동향 ─────────────────────────────────────────────────────
        panel_regulatory = ui.element('div').classes('panel')
        panels['regulatory'] = panel_regulatory
        panel_regulatory.style('display:none;')
        with panel_regulatory:
            def _llm_reg(model_id=None):
                return create_llm(model_id=state.get('selected_model_id'))
            build_regulatory_panel(_config, _llm_reg)

        # ── 관리자 ────────────────────────────────────────────────────────
        panel_admin = ui.element('div').classes('panel')
        panels['admin'] = panel_admin
        panel_admin.style('display:none;')
        nav_ctx = {
            'nav_elements': nav_elements,
            'nav_groups': nav_group_proxies,
            'app_state': state,
            'switch_tab_ref': switch_tab_ref,
            'resolve_chunk_model': resolve_chunk_model,
        }
        with panel_admin:
            build_admin_panel(_config, nav_ctx=nav_ctx)

        # ── Risk DashBoard ────────────────────────────────────────────
        panel_risk_dashboard = ui.element('div').classes('panel')
        panels['risk_dashboard'] = panel_risk_dashboard
        panel_risk_dashboard.style('display:none;')
        with panel_risk_dashboard:
            build_fss_dashboard_panel(_config)

        # ── Risk Indicator Dashboard ──────────────────────────────────
        panel_risk_indicator = ui.element('div').classes('panel')
        panels['risk_indicator'] = panel_risk_indicator
        panel_risk_indicator.style('display:none;')
        with panel_risk_indicator:
            build_risk_indicator_panel(_config)

    # ── 저장된 메뉴 상태 초기 적용 ──────────────────────────────────────────
    _saved_menu = _msm.get()
    for _mk, _enabled in _saved_menu.items():
        if not _enabled and _mk in nav_elements:
            nav_elements[_mk].visible = False
    for _gk, _gitems in _msm.MENU_GROUPS.items():
        if not any(_saved_menu.get(ki, True) for ki in _gitems):
            for _ge in nav_ctx['nav_groups'].get(_gk, {}).values():
                _ge.visible = False

    # ──────────────────────────────────────────────────────────────────────
    # 탭 전환 — nav-item .active 클래스는 정적 HTML이므로 JS로 토글
    # ──────────────────────────────────────────────────────────────────────
    def switch_tab(key):
        state['current_tab'] = key
        # JS로 .active 클래스 토글 (사이드바 정적 HTML이라 Python에서 직접 조작 불가)
        ui.run_javascript(
            "document.querySelectorAll('.sidebar [data-nav-key]').forEach("
            "el => el.classList.remove('active'));"
            f"const t = document.querySelector('.sidebar [data-nav-key=\"{key}\"]');"
            "if (t) t.classList.add('active');"
        )
        for k, p in panels.items():
            p.style(f'display: {"flex" if k == key else "none"};')

        # LLM 미연결 상태에서 LLM 의존 탭 최초 진입 시 안내 팝업 (세션당 1회)
        if (not _llm_ok and key in _LLM_TAB_KEYS
                and not _llm_notice_shown['v']):
            _llm_notice_shown['v'] = True
            llm_status.show_unavailable_dialog()

    switch_tab_ref[0] = switch_tab   # 메뉴 관리 토글 핸들러에서 사용

    # Hidden 트리거 버튼에 click 핸들러 바인딩 — JS delegation이 이걸 click()으로 발화시킴
    for key in _ALL_NAV_KEYS:
        nav_triggers[key].on('click', lambda _e, k=key: switch_tab(k))


# ──────────────────────────────────────────────────────────────────────────────
# 패널 빌더 함수 (가독성을 위해 분리)
# ──────────────────────────────────────────────────────────────────────────────
def _build_summary_panel(parent, state):
    """문서 요약 — 분할 레이아웃."""
    with parent:
        with ui.element('div').classes('page-head'):
            ui.html(
                '<div class="titles">'
                '<div class="page-title">문서 요약</div>'
                '<div class="page-subtitle">계층적 Map-Reduce 방식으로 요약하거나 분량을 축약합니다.</div>'
                '</div>'
            )
        with ui.element('div').classes('split'):
            # LEFT
            with ui.element('div').classes('pane'):
                with ui.element('div').classes('pane-head'):
                    ui.html(
                        '<span class="material-symbols-outlined" '
                        'style="font-size:18px;color:var(--text-2);">upload_file</span>'
                        '<div style="flex:1;">'
                        '<h3>파일 업로드 및 미리보기</h3>'
                        '<div class="pane-sub">.docx · .pdf · .hwp · .hwpx</div>'
                        '</div>'
                    )
                with ui.element('div').classes('pane-body').style('display:flex; flex-direction:column;'):
                    srefs = {}

                    async def handle_upload_summary(e: events.UploadEventArguments):
                        set_current_user(state.get('user_initials', '-'))
                        try:
                            f = e.file
                            name = f.name
                            ext = os.path.splitext(name.lower())[1]
                            if ext not in ('.docx', '.pdf', '.hwp', '.hwpx'):
                                ui.notify('지원하지 않는 확장자입니다.', type='warning', position='top')
                                srefs['upload'].reset()
                                return
                            data = await f.read()
                            upload_abs = os.path.normpath(os.path.join(
                                os.path.dirname(os.path.abspath(__file__)), '..',
                                _config.get("upload_dir", "./uploads"), 'summary',
                                state.get('session_dir', 'anon'),
                            ))
                            os.makedirs(upload_abs, exist_ok=True)
                            save_path = os.path.join(upload_abs, f"{uuid.uuid4().hex}_{name}")
                            with open(save_path, 'wb') as fp:
                                fp.write(data)
                            log.info('문서요약 업로드: %s (%.1f KB)', name, len(data) / 1024)

                            state['summary_file_path'] = save_path
                            state['summary_file_name'] = name

                            if ext == '.pdf':
                                raw = await nicegui_run.io_bound(read_pdf, save_path)
                            elif ext == '.docx':
                                raw = await nicegui_run.io_bound(read_raw_docx, save_path)
                            else:
                                raw = f"[{name}] 미리보기 미지원 형식 — 요약 시 자동 추출됩니다."

                            size_kb = len(data) / 1024
                            srefs['file_card'].content = (
                                '<div class="file-card">'
                                '<span class="material-symbols-outlined">description</span>'
                                f'<span class="fc-name">{_html.escape(name)}</span>'
                                f'<span class="fc-size">{size_kb:.1f} KB</span>'
                                '</div>'
                            )
                            srefs['preview'].content = (
                                f'<div class="preview-text">'
                                f'{_html.escape(raw)}</div>'
                            )
                            ui.notify(f'{name} 업로드 완료', type='positive', position='top')
                            srefs['upload'].reset()
                        except Exception as exc:
                            ui.notify(f'업로드 오류: {exc}', type='negative', position='top')

                    # 업로드 영역은 sticky로 고정 — 요약 후에도 항상 화면에 보임
                    with ui.element('div').classes('upload-sticky w-full'):
                        srefs['upload'] = ui.upload(
                            on_upload=handle_upload_summary,
                            auto_upload=True, max_files=1,
                        ).props('accept=.docx,.pdf,.hwp,.hwpx flat bordered').classes('w-full')
                    srefs['file_card'] = ui.html('')
                    srefs['preview'] = ui.html(
                        '<div class="preview-text">'
                        '<span style="color:var(--text-4);">파일을 업로드하면 미리보기가 표시됩니다.</span>'
                        '</div>'
                    )

                    def _reset_summary_upload_only():
                        """요약/축약 완료 후 업로드 위젯만 초기화하여 새 파일을 받을 수 있게 함.
                        좌측의 파일 카드와 원문 미리보기는 유지하여 사용자가 원문을 계속 확인할 수 있도록 함."""
                        try:
                            srefs['upload'].reset()
                        except Exception:
                            pass

            # RIGHT
            with ui.element('div').classes('pane'):
                with ui.element('div').classes('pane-head'):
                    ui.html(
                        '<span class="material-symbols-outlined" '
                        'style="font-size:18px;color:var(--text-2);">summarize</span>'
                        '<div style="flex:1;">'
                        '<h3>분석 실행</h3>'
                        '<div class="pane-sub">전체 요약 또는 분량 축약 (분량 축약 기능은 DOCX 다운로드 가능)</div>'
                        '</div>'
                    )
                with ui.element('div').classes('pane-body'):
                    summary_llm_chunk = ui.checkbox(
                        'LLM 의미 단위 청킹 사용 (문서 요약 전용)', value=True,
                    ).classes('check-row')
                    ui.html(
                        '<div style="font-size:11px;color:var(--text-4);margin:-4px 0 8px 24px;">'
                        '※ 분량 축약은 원본 단락 구조를 보존하기 위해 항상 섹션 기반으로 처리됩니다.'
                        '</div>'
                    )
                    with ui.element('div').classes('action-row'):
                        btn_summary = ui.button('문서 요약').classes('btn-primary-mono')
                        btn_compress = ui.button('분량 축약').classes('btn-primary-mono')
                    summary_status = ui.html('')
                    summary_result = ui.column().classes('w-full')

                    async def run_summary():
                        if not llm_status.guard():
                            return
                        set_current_user(state.get('user_initials', '-'))
                        if not state.get('summary_file_path'):
                            ui.notify('파일을 먼저 업로드하세요.', type='warning', position='top')
                            return
                        log.info('문서 요약 시작: %s', state.get('summary_file_name'))
                        import time as _t
                        _start_t = _t.monotonic()

                        def _spin(msg: str) -> str:
                            return (
                                '<div style="display:flex;align-items:center;gap:8px;'
                                'color:var(--text-3);font-size:13px;padding:8px 0;">'
                                '<span class="material-symbols-outlined" '
                                'style="font-size:16px;animation:spin 1.2s linear infinite;">'
                                f'progress_activity</span>{msg}</div>'
                            )

                        summary_status.content = _spin(
                            'LLM 의미 단위 청킹 중… (1단계)'
                            if summary_llm_chunk.value else '문서 파싱 중…'
                        )

                        # 스트리밍 토큰을 실시간 표시할 영역 (요약 단일호출 fast-path 용)
                        summary_result.clear()
                        with summary_result:
                            ui.html(
                                '<div style="font-size:13px;font-weight:600;color:var(--text);'
                                'margin:0 0 8px;">요약 (생성 중…)</div>'
                            )
                            streaming_preview = ui.html(
                                '<div class="preview-text" style="min-height:120px;'
                                'background:var(--bg-elev);">'
                                '<span class="chat-cursor"></span></div>'
                            )

                        try:
                            llm = create_llm(model_id=state.get('selected_model_id'))
                            cfg = _config if summary_llm_chunk.value else None

                            def _on_progress(cur, tot, msg):
                                try:
                                    # 단일호출 스트리밍 토큰이면 미리보기 박스에 표시
                                    if isinstance(msg, str) and msg.startswith('__STREAM__'):
                                        partial = msg[len('__STREAM__'):]
                                        safe = _html.escape(partial).replace('\n', '<br>')
                                        streaming_preview.content = (
                                            '<div class="preview-text" style="min-height:120px;'
                                            'background:var(--bg-elev);">'
                                            f'{safe}<span class="chat-cursor"></span></div>'
                                        )
                                        summary_status.content = _spin(
                                            f'요약 스트리밍 중… ({len(partial)}자 수신)'
                                        )
                                    else:
                                        summary_status.content = _spin(
                                            f'{msg} ({cur}/{tot})'
                                        )
                                except Exception:
                                    pass

                            result = await nicegui_run.io_bound(
                                hierarchical_summarize,
                                state['summary_file_path'], llm, _on_progress, cfg,
                            )
                            # 텍스트 추출 실패(.hwp 등) → 빈 결과면 명확히 안내하고 중단
                            if not result.get('section_summaries'):
                                summary_status.content = ''
                                ui.notify(
                                    '문서에서 텍스트를 추출하지 못했습니다. '
                                    '(.hwp는 일부 버전이 지원되지 않을 수 있습니다)',
                                    type='negative', position='top',
                                )
                                return
                            _elapsed = _t.monotonic() - _start_t
                            log.info('문서 요약 완료: %.1fs', _elapsed)
                            summary_result.clear()
                            with summary_result:
                                ui.html(
                                    '<div style="font-size:13px;font-weight:600;color:var(--text);'
                                    'margin:0 0 8px;">최종 요약</div>'
                                    '<div style="padding:14px 16px;background:var(--bg-elev);'
                                    'border:1px solid var(--border);border-radius:var(--radius);'
                                    f'font-size:13.5px;line-height:1.75;color:var(--text);">'
                                    f'{result["final_summary"]}</div>'
                                )
                                ui.html(
                                    '<div style="font-size:13px;font-weight:600;color:var(--text);'
                                    'margin:16px 0 8px;">섹션별 요약</div>'
                                )
                                for s in result['section_summaries']:
                                    with ui.expansion(s['title']).classes(
                                        'w-full mb-2'
                                    ).style(
                                        'border:1px solid var(--border);border-radius:var(--radius);'
                                        'background:var(--bg);'
                                    ):
                                        ui.label(s['summary']).classes('text-sm').style(
                                            'color:var(--text-2);line-height:1.7;'
                                        )
                            summary_status.content = ''
                            ui.notify(
                                f'요약 완료 ({_elapsed:.1f}s) — '
                                '좌측에서 원문을 계속 확인할 수 있으며, 새 파일도 업로드 가능합니다.',
                                type='positive', position='top',
                            )
                            # 원본 파일·미리보기·파일 카드는 유지하여 사용자가 원문을 계속 확인할 수 있도록 함.
                            # 업로드 위젯만 reset 하여 같은 세션에서 새 파일 업로드 가능.
                            _reset_summary_upload_only()
                        except Exception as e:
                            summary_status.content = ''
                            ui.notify(f'요약 오류: {e}', type='negative', position='top')

                    async def run_compress():
                        if not llm_status.guard():
                            return
                        set_current_user(state.get('user_initials', '-'))
                        if not state.get('summary_file_path'):
                            ui.notify('파일을 먼저 업로드하세요.', type='warning', position='top')
                            return
                        log.info('분량 축약 시작: %s', state.get('summary_file_name'))
                        summary_status.content = (
                            '<div style="color:var(--text-3);font-size:13px;padding:8px 0;">분량 축약 중…</div>'
                        )
                        try:
                            llm = create_llm(model_id=state.get('selected_model_id'))
                            # 분량 축약은 원본 DOCX의 Heading 구조와 1:1 대응되어야
                            # create_compressed_docx 가 단락을 정확히 치환할 수 있음.
                            # LLM 청킹은 임의의 청크 제목을 만들어 매칭 실패 → 원본이
                            # 그대로 다운로드되는 버그를 일으키므로 항상 None 으로 호출.
                            result = await nicegui_run.io_bound(
                                compress_document,
                                state['summary_file_path'], llm, None, None,
                            )
                            # 텍스트 추출 실패(.hwp 등) → 빈 섹션이면 빈 문서 생성 대신 안내하고 중단
                            if not result.get('sections'):
                                summary_status.content = ''
                                ui.notify(
                                    '문서에서 텍스트를 추출하지 못했습니다. '
                                    '(.hwp는 일부 버전이 지원되지 않을 수 있습니다)',
                                    type='negative', position='top',
                                )
                                return
                            orig_name = state.get('summary_file_name', 'document.docx')
                            base_name = os.path.splitext(orig_name)[0]
                            out_name = f"{base_name}_compressed.docx"
                            upload_abs = os.path.normpath(os.path.join(
                                os.path.dirname(os.path.abspath(__file__)), '..',
                                _config.get("upload_dir", "./uploads"), 'summary',
                            ))
                            out_path = os.path.join(upload_abs, f"{uuid.uuid4().hex}_{out_name}")
                            await nicegui_run.io_bound(
                                create_compressed_docx,
                                state['summary_file_path'], result['sections'], out_path,
                            )
                            summary_result.clear()
                            with summary_result:
                                ui.html(
                                    '<div style="padding:10px 14px;background:var(--bg-elev);'
                                    'border:1px solid var(--border);border-radius:var(--radius);'
                                    'color:var(--text);font-size:13px;margin-bottom:12px;">'
                                    f'분량 축약 완료 · 원문 <b>{result["total_original_chars"]:,}자</b> → '
                                    f'<b>{result["total_compressed_chars"]:,}자</b> '
                                    f'({result["reduction_rate"]}% 감소)</div>'
                                )
                                ui.button(
                                    f'{out_name} 다운로드',
                                    on_click=lambda p=out_path, n=out_name: ui.download(p, filename=n),
                                ).classes('btn-primary-mono mb-3')
                                from summarizer import _TABLE_RE as _TREX
                                for s in result['sections']:
                                    note = ' (표 포함)' if s.get('has_tables') else ''
                                    with ui.expansion(s['title'] + note).classes(
                                        'w-full mb-2'
                                    ).style(
                                        'border:1px solid var(--border);border-radius:var(--radius);'
                                        'background:var(--bg);'
                                    ):
                                        ui.html(
                                            f'<div style="font-size:11px;color:var(--text-4);'
                                            f'margin-bottom:6px;">{s["original_chars"]:,}자 → '
                                            f'{s["compressed_chars"]:,}자</div>'
                                        )
                                        display_text = _TREX.sub('', s['compressed']).strip()
                                        ui.label(display_text).classes('text-sm').style(
                                            'color:var(--text-2);line-height:1.7;'
                                        )
                            summary_status.content = ''
                            ui.notify(
                                '분량 축약 완료 — 좌측에서 원문을 계속 확인할 수 있으며, 새 파일도 업로드 가능합니다.',
                                type='positive', position='top',
                            )
                            # 원본 파일·미리보기·파일 카드는 유지. 출력 DOCX는 다운로드용으로 보관.
                            _reset_summary_upload_only()
                        except Exception as e:
                            summary_status.content = ''
                            ui.notify(f'축약 오류: {e}', type='negative', position='top')

                    btn_summary.on_click(run_summary)
                    btn_compress.on_click(run_compress)
                    _gate_llm_button(btn_summary)
                    _gate_llm_button(btn_compress)


# ──────────────────────────────────────────────────────────────────────────────
# 문서 질의응답 (Document Q&A) — RAG + 멀티턴 채팅
# ──────────────────────────────────────────────────────────────────────────────
def _qa_simple_chunk(text: str, chunk_size: int = 1200, overlap: int = 200) -> list[str]:
    """간단한 슬라이딩 청킹 (의존성 최소화). 빈 텍스트는 빈 리스트."""
    text = (text or '').strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    out = []
    i = 0
    step = max(1, chunk_size - overlap)
    while i < len(text):
        out.append(text[i:i + chunk_size])
        i += step
    return out


def _qa_embed_text(emb_cfg: dict, text: str):
    """legal_embedding 서버를 재사용해 단일 텍스트 임베딩을 얻음. 실패 시 None."""
    try:
        import requests
        import numpy as np
    except Exception:
        return None
    url = emb_cfg.get('url', 'http://127.0.0.1:8081')
    model = emb_cfg.get('model', 'bge-m3')
    timeout = emb_cfg.get('timeout', 30)
    try:
        r = requests.post(
            f"{url}/v1/embeddings",
            json={"model": model, "input": text},
            timeout=timeout,
        )
        if r.ok and "data" in r.json():
            v = np.array(r.json()["data"][0]["embedding"], dtype=np.float32)
            v /= (np.linalg.norm(v) + 1e-12)
            return v
    except Exception:
        pass
    return None


def _qa_score_tfidf(query: str, chunks: list[str]) -> list[float]:
    """sklearn TfidfVectorizer 기반 유사도. 실패 시 키워드 빈도 fallback."""
    if not chunks:
        return []
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        vec = TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 4))
        mat = vec.fit_transform(chunks + [query])
        sims = cosine_similarity(mat[-1], mat[:-1]).ravel()
        return sims.tolist()
    except Exception:
        q_tokens = set(re.findall(r'\w+', (query or '').lower()))
        scores = []
        for c in chunks:
            c_tokens = re.findall(r'\w+', (c or '').lower())
            if not c_tokens or not q_tokens:
                scores.append(0.0)
                continue
            hits = sum(1 for t in c_tokens if t in q_tokens)
            scores.append(hits / (len(c_tokens) ** 0.5))
        return scores


def _build_qa_panel(parent, state, create_llm_fn):
    """문서 질의응답 패널 — 멀티턴 채팅 + RAG.

    좌측: 다중 파일 업로드 + 업로드 파일 목록
    우측: 채팅 히스토리 + 입력 (대화 히스토리 유지)
    """
    with parent:
        with ui.element('div').classes('page-head'):
            ui.html(
                '<div class="titles">'
                '<div class="page-title">문서 질의응답</div>'
                '<div class="page-subtitle">업로드한 문서를 기반으로 LLM 과 자유롭게 질의응답합니다 (RAG · 대화 히스토리 유지).</div>'
                '</div>'
            )

        qa_files: list[dict] = []
        qa_chat:  list[dict] = []
        qrefs: dict = {}

        emb_cfg = _config.get('legal_embedding', {})

        with ui.element('div').classes('split'):
            with ui.element('div').classes('pane'):
                with ui.element('div').classes('pane-head'):
                    ui.html(
                        '<span class="material-symbols-outlined" '
                        'style="font-size:18px;color:var(--text-2);">upload_file</span>'
                        '<div style="flex:1;">'
                        '<h3>참고 문서</h3>'
                        '<div class="pane-sub">.docx · .pdf · .hwp · .hwpx (다중 업로드 가능)</div>'
                        '</div>'
                    )
                with ui.element('div').classes('pane-body').style('display:flex;flex-direction:column;'):
                    qrefs['upload'] = ui.upload(
                        auto_upload=True, multiple=True,
                    ).props('accept=.docx,.pdf,.hwp,.hwpx,.txt flat bordered').classes('w-full')

                    qrefs['file_list'] = ui.column().classes('w-full').style(
                        'gap:4px;margin-top:10px;'
                    )

                    ui.html('<div class="divider" style="margin:12px 0;"></div>')
                    qrefs['status'] = ui.html(
                        '<div style="font-size:12px;color:var(--text-4);">'
                        '파일을 업로드하면 자동으로 청킹·인덱싱됩니다.</div>'
                    )

            with ui.element('div').classes('pane'):
                with ui.element('div').classes('pane-head'):
                    ui.html(
                        '<span class="material-symbols-outlined" '
                        'style="font-size:18px;color:var(--text-2);">forum</span>'
                        '<div style="flex:1;">'
                        '<h3>대화</h3>'
                        '<div class="pane-sub">질문하면 관련 청크가 자동 검색되어 답변에 활용됩니다</div>'
                        '</div>'
                    )
                # 홈 화면과 동일한 chat-wrap / chat-scroll / chat-inner / composer 구조
                with ui.element('div').classes('chat-wrap'):
                    qrefs['empty'] = ui.element('div').classes('chat-empty')
                    with qrefs['empty']:
                        ui.html(
                            '<div class="empty-mark">'
                            '<span class="material-symbols-outlined">forum</span>'
                            '</div>'
                            '<h2>문서에 대해 무엇이든 물어보세요</h2>'
                            '<p>좌측에서 참고 문서를 업로드한 뒤 질문을 입력하면, '
                            '관련 청크가 자동 검색되어 답변에 활용됩니다.</p>'
                        )

                    qrefs['scroll'] = ui.element('div').classes('chat-scroll').style('display:none;')
                    with qrefs['scroll']:
                        qrefs['chat_inner'] = ui.element('div').classes('chat-inner')

                    with ui.element('div').classes('composer-wrap'):
                        with ui.element('div').classes('composer'):
                            qrefs['input'] = ui.textarea(
                                placeholder='문서 내용에 대해 질문하세요…',
                            ).props('borderless autogrow rows=1 dense').classes('flex-1')

                            with ui.element('div').classes('composer-actions'):
                                qrefs['clear'] = ui.element('button').classes('icon-btn')
                                qrefs['clear'].props('title="대화 초기화"')
                                with qrefs['clear']:
                                    ui.html('<span class="material-symbols-outlined">restart_alt</span>')

                                qrefs['send'] = ui.element('button').classes('send-btn')
                                qrefs['send'].props('title="전송 (Enter)"')
                                with qrefs['send']:
                                    ui.html('<span class="material-symbols-outlined">arrow_upward</span>')

                        ui.html(
                            '<div class="composer-hint">'
                            '<span>Shift + Enter 줄바꿈</span>'
                            '<span><span class="kbd">Enter</span> 전송</span>'
                            '</div>'
                        )

        def _msg_html(role: str, content: str, with_cursor: bool = False) -> str:
            """홈/Q&A 공용 메시지 카드 HTML."""
            is_user = (role == 'user')
            cls = 'msg user' if is_user else 'msg ai'
            avatar = '나' if is_user else 'AI'
            label  = '사용자' if is_user else '어시스턴트'
            body = _html.escape(content).replace('\n', '<br>') if content else ''
            cursor = '<span class="chat-cursor"></span>' if with_cursor else ''
            return (
                f'<div class="{cls}">'
                f'<div class="msg-role">'
                f'<span class="avatar">{avatar}</span><span>{label}</span>'
                f'</div>'
                f'<div class="msg-body">{body}{cursor}</div>'
                f'</div>'
            )

        def _show_empty_state(visible: bool):
            try:
                qrefs['empty'].style(f'display:{"flex" if visible else "none"};')
                qrefs['scroll'].style(f'display:{"none" if visible else "block"};')
            except Exception:
                pass

        def _render_chat():
            qrefs['chat_inner'].clear()
            if not qa_chat:
                _show_empty_state(True)
                return
            _show_empty_state(False)
            with qrefs['chat_inner']:
                for msg in qa_chat:
                    ui.html(_msg_html(msg['role'], msg.get('content', '')))
            try:
                with qrefs['chat_inner']:
                    ui.run_javascript(
                        'document.querySelectorAll(".chat-scroll").forEach('
                        's => { s.scrollTop = s.scrollHeight; });'
                    )
            except Exception:
                pass

        def _render_file_list():
            qrefs['file_list'].clear()
            with qrefs['file_list']:
                if not qa_files:
                    ui.html(
                        '<div style="color:var(--text-4);font-size:12px;'
                        'padding:6px 2px;">업로드된 파일이 없습니다.</div>'
                    )
                    return
                for i, fi in enumerate(qa_files):
                    n_chunks = len(fi.get('chunks') or [])
                    n_vec = sum(1 for v in (fi.get('vectors') or []) if v is not None)
                    badge = (
                        f'<span style="font-size:10px;font-weight:600;color:#16a34a;'
                        f'background:#dcfce7;padding:2px 6px;border-radius:10px;'
                        f'flex-shrink:0;">청크 {n_chunks}</span>'
                    )
                    if n_vec:
                        badge += (
                            f'<span style="font-size:10px;font-weight:600;color:#0284c7;'
                            f'background:#e0f2fe;padding:2px 6px;border-radius:10px;'
                            f'flex-shrink:0;margin-left:4px;">벡터 {n_vec}</span>'
                        )
                    row = ui.element('div').style(
                        'display:flex;align-items:center;gap:8px;padding:8px 10px;'
                        'border:1px solid var(--border);border-radius:var(--radius);'
                        'font-size:13px;'
                    )
                    with row:
                        ui.html(
                            '<span class="material-symbols-outlined" '
                            'style="font-size:16px;color:var(--text-3);flex-shrink:0;">'
                            'description</span>'
                            + f'<span style="flex:1;overflow:hidden;text-overflow:ellipsis;'
                            f'white-space:nowrap;font-weight:500;color:var(--text);">'
                            f'{_html.escape(fi["name"])}</span>'
                            + badge
                            + f'<span style="font-size:11px;color:var(--text-4);flex-shrink:0;'
                            f'margin-left:4px;">{fi["size_kb"]:.1f} KB</span>'
                        )
                        del_btn = ui.element('button').style(
                            'background:transparent;border:none;cursor:pointer;'
                            'color:var(--text-4);padding:2px 4px;flex-shrink:0;'
                            'display:flex;align-items:center;'
                        ).props('title="목록에서 제거"')
                        with del_btn:
                            ui.html('<span class="material-symbols-outlined" '
                                    'style="font-size:16px;">close</span>')
                        idx_cap = i
                        del_btn.on(
                            'click.stop',
                            lambda _e, idx=idx_cap: _remove_qa_file(idx),
                        )

        def _remove_qa_file(idx: int):
            if idx < 0 or idx >= len(qa_files):
                return
            fi = qa_files.pop(idx)
            try:
                if fi.get('path') and os.path.exists(fi['path']):
                    os.remove(fi['path'])
            except Exception:
                pass
            _render_file_list()

        async def handle_qa_upload(e: events.UploadEventArguments):
            set_current_user(state.get('user_initials', '-'))
            try:
                f = e.file
                name = f.name
                ext = os.path.splitext(name.lower())[1]
                if ext not in ('.docx', '.pdf', '.hwp', '.hwpx', '.txt'):
                    ui.notify('지원하지 않는 확장자입니다.', type='warning', position='top')
                    return
                data = await f.read()
                upload_abs = os.path.normpath(os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), '..',
                    _config.get('upload_dir', './uploads'), 'qa',
                    state.get('session_dir', 'anon'),
                ))
                os.makedirs(upload_abs, exist_ok=True)
                save_path = os.path.join(upload_abs, f'{uuid.uuid4().hex}_{name}')
                with open(save_path, 'wb') as fp:
                    fp.write(data)
                log.info('문서Q&A 업로드: %s (%.1f KB)', name, len(data) / 1024)

                if ext == '.pdf':
                    raw = await nicegui_run.io_bound(read_pdf, save_path)
                elif ext == '.docx':
                    raw = await nicegui_run.io_bound(read_raw_docx, save_path)
                elif ext == '.txt':
                    try:
                        with open(save_path, 'r', encoding='utf-8', errors='ignore') as fp:
                            raw = fp.read()
                    except Exception:
                        raw = ''
                else:
                    try:
                        from read_docx_util import read_docx as _rdocx
                        raw = await nicegui_run.io_bound(_rdocx, save_path)
                    except Exception:
                        raw = ''

                chunks = _qa_simple_chunk(raw or '', chunk_size=1200, overlap=200)

                qrefs['status'].content = (
                    f'<div style="font-size:12px;color:var(--text-3);">'
                    f'[{_html.escape(name)}] 인덱싱 중… '
                    f'(청크 {len(chunks)}개)</div>'
                )
                vectors = []
                use_embed = True
                for ci, ch in enumerate(chunks):
                    if not use_embed:
                        vectors.append(None)
                        continue
                    v = await nicegui_run.io_bound(_qa_embed_text, emb_cfg, ch)
                    if v is None and ci == 0:
                        use_embed = False
                    vectors.append(v)

                size_kb = len(data) / 1024
                qa_files.append({
                    'path': save_path, 'name': name, 'size_kb': size_kb,
                    'chunks': chunks, 'vectors': vectors,
                })
                _render_file_list()
                qrefs['status'].content = (
                    f'<div style="font-size:12px;color:var(--text-3);">'
                    f'{len(qa_files)}개 문서 · 총 청크 '
                    f'{sum(len(x["chunks"]) for x in qa_files)}개 '
                    + ('· 임베딩 사용' if use_embed else '· 키워드(TF-IDF) 검색 사용')
                    + '</div>'
                )
                qrefs['upload'].reset()
                ui.notify(f'{name} 인덱싱 완료', type='positive', position='top')
            except Exception as exc:
                log.exception('Q&A 업로드 오류')
                qrefs['status'].content = ''
                ui.notify(f'업로드 오류: {exc}', type='negative', position='top')

        qrefs['upload'].on_upload(handle_qa_upload)

        def _retrieve(query: str, top_k: int = 6) -> list[tuple[str, str, float]]:
            all_items: list[tuple[str, str, object]] = []
            for fi in qa_files:
                vecs = fi.get('vectors') or []
                for ci, ch in enumerate(fi.get('chunks') or []):
                    v = vecs[ci] if ci < len(vecs) else None
                    all_items.append((fi['name'], ch, v))
            if not all_items:
                return []

            if all(v is not None for _, _, v in all_items):
                try:
                    import numpy as np
                    qv = _qa_embed_text(emb_cfg, query)
                    if qv is not None:
                        scored = []
                        for name, ch, v in all_items:
                            s = float(np.dot(qv, v))
                            scored.append((name, ch, s))
                        scored.sort(key=lambda x: x[2], reverse=True)
                        return scored[:top_k]
                except Exception:
                    pass

            texts = [ch for _, ch, _ in all_items]
            scores = _qa_score_tfidf(query, texts)
            scored = [
                (all_items[i][0], all_items[i][1], float(scores[i]))
                for i in range(len(all_items))
            ]
            scored.sort(key=lambda x: x[2], reverse=True)
            return scored[:top_k]

        def _format_context(docs: list[tuple[str, str, float]]) -> str:
            blocks = []
            for i, (name, ch, score) in enumerate(docs, 1):
                blocks.append(f'[문서 {i} — {name} (score={score:.3f})]\n{ch}')
            return '\n\n'.join(blocks)

        async def send_qa_message():
            if not llm_status.guard():
                return
            set_current_user(state.get('user_initials', '-'))
            q = (qrefs['input'].value or '').strip()
            if not q:
                return
            if not qa_files:
                ui.notify(
                    '먼저 좌측에서 참고 문서를 업로드하세요.',
                    type='warning', position='top',
                )
                return

            qrefs['input'].value = ''
            qa_chat.append({'role': 'user', 'content': q})
            _show_empty_state(False)

            # 사용자 메시지 + 빈 AI 버블 즉시 추가 (스트리밍 토큰을 그 안에 누적)
            with qrefs['chat_inner']:
                ui.html(_msg_html('user', q))
                stream_bubble = ui.html(_msg_html('assistant', '', with_cursor=True))

            try:
                docs = await nicegui_run.io_bound(_retrieve, q, 6)
                context_text = _format_context(docs) if docs else '(관련 문서를 찾지 못했습니다)'

                history_lines = []
                for m in qa_chat[:-1]:  # 마지막은 방금 추가한 user q
                    role = '사용자' if m['role'] == 'user' else 'AI'
                    history_lines.append(f'{role}: {m["content"]}')
                history_block = '\n'.join(history_lines) if history_lines else '(없음)'

                system_prompt = (
                    '당신은 사용자가 업로드한 문서들의 내용을 깊이 이해하고 '
                    '근거에 기반하여 답변하는 한국어 문서 질의응답 전문가입니다. '
                    '아래 [참고 문서]에 명시된 사실만 사용해 답변하세요. '
                    '문서에 없는 내용은 "주어진 문서로는 확인되지 않습니다"라고 명시하세요. '
                    '답변에는 어느 문서를 근거로 했는지 [문서 N] 형식으로 표기하세요.'
                )
                user_prompt = (
                    f'[참고 문서]\n{context_text}\n\n'
                    f'[이전 대화]\n{history_block}\n\n'
                    f'[사용자 질문]\n{q}'
                )

                from langchain_core.messages import SystemMessage, HumanMessage
                llm = create_llm_fn(model_id=state.get('selected_model_id'))
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
                    # astream 미지원/오류 → invoke 폴백
                    def _sync_invoke():
                        resp = llm.invoke([
                            SystemMessage(content=system_prompt),
                            HumanMessage(content=user_prompt),
                        ])
                        return getattr(resp, 'content', None) or str(resp)
                    answer = await nicegui_run.io_bound(_sync_invoke)

                final = answer or '(빈 응답)'
                stream_bubble.content = _msg_html('assistant', final)
                qa_chat.append({'role': 'assistant', 'content': final})

                with qrefs['chat_inner']:
                    ui.run_javascript(
                        'document.querySelectorAll(".chat-scroll").forEach('
                        's => { s.scrollTop = s.scrollHeight; });'
                    )
            except Exception as e:
                log.exception('Q&A 답변 오류')
                err = f'답변 생성 중 오류가 발생했습니다: {e}'
                stream_bubble.content = _msg_html('assistant', err)
                qa_chat.append({'role': 'assistant', 'content': err})

        async def clear_qa_chat():
            qa_chat.clear()
            _render_chat()

        qrefs['send'].on('click', lambda _e: asyncio.create_task(send_qa_message()))
        qrefs['clear'].on('click', lambda _e: asyncio.create_task(clear_qa_chat()))
        _gate_llm_button(qrefs['send'], native=True)

        def _on_enter(_e):
            try:
                shift = bool(_e.args.get('shiftKey')) if isinstance(_e.args, dict) else False
            except Exception:
                shift = False
            if not shift:
                asyncio.create_task(send_qa_message())
        qrefs['input'].on('keydown.enter', _on_enter)

        _render_file_list()


def _build_convert_panel(parent, state):
    """PDF 변환 패널 — 모노크롬 카드 1개.

    업로드·변환 폴더는 세션(IP)별로 분리하여 여러 사용자의 파일이 한 폴더에
    섞이지 않도록 한다: uploads/pdf/<session_dir>/{input,output}.
    """
    _sess = (state or {}).get('session_dir', 'anon')
    _uploads_root = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..', 'uploads', 'pdf', _sess,
    ))
    target_dir    = os.path.join(_uploads_root, "input")
    output_dir    = os.path.join(_uploads_root, "output")
    zip_file_path = os.path.join(_uploads_root, "converted_results.zip")
    os.makedirs(target_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    with parent:
        with ui.element('div').classes('page-head'):
            ui.html(
                '<div class="titles">'
                '<div class="page-title">PDF 변환</div>'
                '<div class="page-subtitle">Word·PowerPoint 파일을 일괄 PDF로 변환합니다.</div>'
                '</div>'
            )
        with ui.element('div').style(
            'flex:1; overflow:auto; padding:24px 32px; max-width:880px; margin:0 auto; width:100%;'
        ):
            async def handle_upload(e: events.UploadEventArguments):
                file_name = e.file.name
                try:
                    target_path = os.path.join(target_dir, file_name)
                    await e.file.save(target_path)
                    ui.notify(f'업로드: {file_name}', type='positive')
                except Exception as ex:
                    ui.notify(f'저장 실패: {ex}', type='negative')

            def _create_zip_only(dst, zip_path):
                shutil.make_archive(zip_path.replace('.zip', ''), 'zip', dst)

            def _log_line(col, msg: str, color: str = 'var(--text-3)'):
                with col:
                    ui.html(
                        f'<div style="padding:6px 12px;border-radius:var(--radius);'
                        f'color:{color};font-size:13px;margin-bottom:2px;'
                        f'background:var(--bg-elev);border:1px solid var(--border);">'
                        f'{msg}</div>'
                    )

            async def run_conversion():
                import queue as _queue

                uploaded = [
                    f for f in os.listdir(target_dir)
                    if not f.startswith('~$')
                ] if os.path.isdir(target_dir) else []
                if not uploaded:
                    ui.notify('업로드된 파일이 없습니다.', type='warning')
                    return

                # ── 로그 다이얼로그 생성 ────────────────────────────────
                log_q: _queue.Queue = _queue.Queue()
                success_count = 0
                failed_files: list = []

                dlg = ui.dialog().props('persistent max-width=680px')
                with dlg:
                    with ui.card().style(
                        'width:640px;max-height:80vh;display:flex;flex-direction:column;gap:0;'
                        'background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-lg);'
                    ):
                        ui.html(
                            '<div style="padding:18px 20px 12px;font-size:15px;font-weight:600;'
                            'color:var(--text);border-bottom:1px solid var(--border);">'
                            'PDF 변환 진행 로그</div>'
                        )
                        log_col = ui.column().style(
                            'flex:1;overflow-y:auto;padding:12px 16px;gap:0;min-height:120px;max-height:480px;'
                        )
                        summary_col = ui.column().style('padding:0 16px 4px;gap:0;display:none;')
                        with ui.row().style(
                            'padding:12px 16px;border-top:1px solid var(--border);justify-content:flex-end;'
                        ):
                            close_btn = ui.button('닫기', on_click=dlg.close).classes('btn')
                            close_btn.props('disabled')

                dlg.open()

                def _finish(s_count, f_files, output_folder_path, zip_src):
                    nonlocal success_count, failed_files
                    # 최종 요약 표시
                    total = s_count + len(f_files)
                    with log_col:
                        ui.html(
                            f'<div style="margin-top:8px;padding:8px 12px;border-radius:var(--radius);'
                            f'background:var(--bg-sunken);border:1px solid var(--border);'
                            f'font-size:13px;font-weight:600;color:var(--text);">'
                            f'완료: {s_count}/{total}개 성공</div>'
                        )
                    if f_files:
                        with log_col:
                            ui.html(
                                '<div style="margin-top:6px;padding:8px 12px;border-radius:var(--radius);'
                                'background:#fef3c7;border:1px solid #d97706;'
                                'font-size:13px;font-weight:600;color:#92400e;">'
                                f'실패한 파일 ({len(f_files)}개) — 아래 목록을 확인하고 재시도하세요.</div>'
                            )
                            for fname in f_files:
                                ui.html(
                                    f'<div style="padding:4px 12px;font-size:12px;color:#b45309;">'
                                    f'• {fname}</div>'
                                )
                    close_btn.props(remove='disabled')

                is_windows = _is_office_com_available()

                # ── 변환 스레드 함수 ────────────────────────────────────
                if is_windows:
                    def _run_thread():
                        import pythoncom as _pc
                        _pc.CoInitialize()
                        try:
                            from ppt_word2pdf import convert_each_to_pdf, cleanup_gen_py
                            convert_each_to_pdf(target_dir, output_dir, log_queue=log_q)
                            cleanup_gen_py()
                        except Exception as e:
                            log_q.put(('error', '', f'변환 오류: {e}'))
                            log_q.put(('done', '', ''))
                        finally:
                            try:
                                _pc.CoUninitialize()
                            except Exception:
                                pass
                else:
                    def _run_thread():
                        try:
                            from pdf_converter_Libre import batch_convert_to_pdf as _libre_batch
                            _libre_batch(target_dir, log_queue=log_q)
                        except Exception as e:
                            log_q.put(('error', '', f'변환 오류: {e}'))
                            log_q.put(('done', '', ''))

                engine = 'Microsoft Office' if is_windows else 'LibreOffice'
                _log_line(log_col, f'변환 엔진: {engine}  |  총 {len(uploaded)}개 파일', 'var(--text-3)')
                asyncio.create_task(nicegui_run.io_bound(_run_thread))

                # ── 큐 폴링 타이머 ─────────────────────────────────────
                _done = False

                async def _poll():
                    nonlocal _done, success_count, failed_files
                    if _done:
                        return
                    try:
                        while True:
                            status, fname, msg = log_q.get_nowait()
                            if status == 'success':
                                success_count += 1
                                _log_line(log_col, f'✓ {fname}', '#15803d')
                            elif status == 'error':
                                if fname:
                                    failed_files.append(fname)
                                    _log_line(log_col, f'✗ {fname}  —  {msg}', '#b91c1c')
                                else:
                                    _log_line(log_col, msg, '#b91c1c')
                            elif status == 'done':
                                _done = True
                                _timer.cancel()
                                # ZIP 생성 및 다운로드
                                try:
                                    out_path = output_dir if is_windows else os.path.join(target_dir, 'pdf_output')
                                    pdfs = [f for f in os.listdir(out_path) if f.lower().endswith('.pdf')] \
                                        if os.path.isdir(out_path) else []
                                    if pdfs:
                                        await nicegui_run.io_bound(_create_zip_only, out_path, zip_file_path)
                                        ui.download(zip_file_path, filename='converted_pdf_files.zip')
                                except Exception as e:
                                    _log_line(log_col, f'ZIP 생성 오류: {e}', '#b91c1c')
                                _finish(success_count, failed_files, output_dir, zip_file_path)
                                # input 폴더 정리
                                for f in list(os.listdir(target_dir)):
                                    try:
                                        os.remove(os.path.join(target_dir, f))
                                    except Exception:
                                        pass
                                # output 폴더 PDF 정리 (다음 변환 시 섞이지 않도록)
                                _out = output_dir if is_windows else os.path.join(target_dir, 'pdf_output')
                                if os.path.isdir(_out):
                                    for f in list(os.listdir(_out)):
                                        if f.lower().endswith('.pdf'):
                                            try:
                                                os.remove(os.path.join(_out, f))
                                            except Exception:
                                                pass
                                # 업로드 위젯 초기화
                                upload_widget.run_method('reset')
                                break
                    except Exception:
                        pass

                _timer = ui.timer(0.4, _poll)

            upload_widget = ui.upload(
                on_upload=handle_upload, multiple=True, auto_upload=True,
                label='파일을 드래그·앤·드롭하거나 클릭하여 업로드',
            ).classes('w-full mb-4').props('max-file-size=52428800 flat bordered')
            ui.button('업로드한 파일 변환 시작', on_click=run_conversion).classes(
                'btn-primary-mono w-full mb-4'
            )


# ──────────────────────────────────────────────────────────────────────────────
if __name__ in {"__main__", "__mp_main__"}:
    # 폰트 파일을 로컬 static으로 서빙 (static/fonts/ 폴더가 있는 경우)
    _static_fonts = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "fonts")
    if os.path.isdir(_static_fonts):
        nicegui_app.add_static_files('/static/fonts', _static_fonts)

    # storage_secret 은 app.storage.user (브라우저 영구 세션 저장소) 활성화에 필요.
    # 우선순위: NICEGUI_STORAGE_SECRET (env, HF Secrets) → config.json → 임시 키.
    _storage_secret = (
        os.environ.get("NICEGUI_STORAGE_SECRET", "").strip()
        or _config.get('storage_secret')
    )
    if not _storage_secret:
        import secrets as _secrets
        _storage_secret = _secrets.token_hex(32)
        log.warning(
            "NICEGUI_STORAGE_SECRET / config.storage_secret 미설정 — 임시 키를 생성합니다. "
            "재시작 시 사용자 이니셜 세션이 모두 초기화됩니다. "
            "HF Spaces Secrets 에 NICEGUI_STORAGE_SECRET 을 추가하세요."
        )

    ui.run(
        host=HOST, port=APP_PORT,
        title='Integrated Work Platform', reload=False, dark=False, show=False,
        reconnect_timeout=86400,
        storage_secret=_storage_secret,
    )
