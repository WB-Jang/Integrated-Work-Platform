"""
LLM-based semantic chunker using OpenRouter (llama-70b).
HYU-Persona-AI 02-rag/2_chunk.py 방식을 포팅.
표(Table)는 마크다운 형식으로 변환하여 LLM이 의미 단위를 이해하기 쉽게 처리.
"""
import json
import re
import threading
import time
from typing import Optional

from logger import get_logger

log = get_logger("llm_chunker")

_CHUNK_SYSTEM_PROMPT = """[Context]
당신은 금융기관의 내부 규정, 법령, 감독규정, 업무 매뉴얼 등 한국어 공식 문서를 처리하는 RAG(검색 증강 생성) 청킹 전문가입니다.
청킹된 결과는 벡터 DB에 저장되어 사용자 질의 시 관련 조항을 검색하는 데 사용됩니다.

[Objective]
입력된 텍스트를 의미 단위로 분할하여 검색 정확도가 높은 청크 목록을 생성하세요.

[Rules]
- 각 청크는 약 200~600 토큰 (한국어 글자 기준 약 130~400자).
- 원문을 절대 요약·번역·재표현하지 마세요. 원문 그대로 보존하세요.
- 조항 번호(제X조, 제X항, 제X호), 항목 제목, 단락 경계에서 분할하세요.
- 문장 중간, 조항 번호와 조항 내용 사이에서 절대 분할하지 마세요.
- 표([TABLE START]...[TABLE END])는 반드시 하나의 청크 안에 완전히 포함하세요. 표를 절대 분할하지 마세요.
- 표가 매우 큰 경우(600 토큰 초과)는 표 단독으로 하나의 청크를 구성하세요.
- 하나의 조항이 짧으면 인접한 관련 조항과 묶어 청크 크기를 유지하세요.

[Tone]
정확성 최우선. 임의 판단이나 내용 변형 없이 기계적으로 경계를 식별하세요.

[Response]
반드시 아래 JSON 형식만 출력하세요. 다른 설명, 마크다운, 주석 일절 금지.
{"chunks": [{"text": "원문 텍스트"}, ...]}"""

WINDOW_TOKENS = 15_000
HOP_TOKENS = 1_000


def _get_encoding():
    try:
        import tiktoken
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def _slice_windows(tokens: list, encoder, size: int, hop: int):
    n = len(tokens)
    start = 0
    while start < n:
        end = min(start + size, n)
        yield encoder.decode(tokens[start:end])
        if end == n:
            return
        start = max(end - hop, start + 1)


def _normalize_key(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())[:200]


def table_to_markdown(table) -> str:
    """
    python-docx Table 객체를 마크다운 표 형식으로 변환.
    LLM이 표 구조를 이해하기 쉽도록 마크다운 형식 사용.
    """
    if not table.rows:
        return ""
    rows = []
    for i, row in enumerate(table.rows):
        cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
        rows.append("| " + " | ".join(cells) + " |")
        if i == 0:
            rows.append("| " + " | ".join(["---"] * len(cells)) + " |")
    return "\n[TABLE START]\n" + "\n".join(rows) + "\n[TABLE END]\n"


def _call_llm_chunk(text: str, config: dict) -> list[str]:
    """LLM 으로 텍스트 청킹. 청크 목록 반환.

    Provider 결정:
      - config.llm_chunk_provider ("openai"/"openrouter") 가 지정되고 해당 키가
        있으면 그 provider 사용. (UI 모델 선택 창에서 고른 모델 기준으로 주입됨)
      - 미지정 시 자동 감지: OpenAI 키 → OpenAI, 없으면 OpenRouter 키 → OpenRouter.
      - 둘 다 없으면 빈 목록 반환(상위에서 단순 청킹으로 fallback).

    모델: config.llm_chunk_model (UI 선택 모델로 주입; 기본 gpt-5-mini).
    타임아웃: config.llm_chunk_timeout (기본 600초).
    OpenRouter 사용 시 모델명에 "/"가 없으면 OpenRouter 형식("openai/...")으로 자동 매핑.
    """
    import os
    try:
        from openai import OpenAI
    except ImportError:
        log.warning("openai 패키지 없음. 단순 청킹 사용.")
        return []

    # ── Provider 결정 ──────────────────────────────────────────────
    openai_cfg = config.get("openai", {})
    openai_key = (
        os.environ.get("OPENAI_API_KEY", "").strip()
        or openai_cfg.get("api_key", "").strip()
    )
    openrouter_cfg = config.get("openrouter", {})
    openrouter_key = (
        os.environ.get("OPENROUTER_API_KEY", "").strip()
        or openrouter_cfg.get("api_key", "").strip()
    )

    chunk_model = config.get("llm_chunk_model", "gpt-5-mini")
    # UI 모델 선택 창에서 결정된 provider 를 우선 적용한다(하드코딩 금지).
    # llm_chunk_provider 가 비어 있으면 키 존재 여부로 자동 감지(기존 동작).
    forced = (config.get("llm_chunk_provider") or "").strip().lower()

    # 우선순위: 명시적 provider(해당 키 있으면) → OpenAI(키 있으면) → OpenRouter(키 있으면)
    if forced == "openai" and openai_key:
        provider = "openai"
    elif forced == "openrouter" and openrouter_key:
        provider = "openrouter"
    elif openai_key:
        provider = "openai"
    elif openrouter_key:
        provider = "openrouter"
    else:
        log.warning("OPENAI_API_KEY / OPENROUTER_API_KEY 모두 없음. 단순 청킹 사용.")
        return []

    if provider == "openai":
        api_key = openai_key
        base_url = openai_cfg.get("base_url", "https://api.openai.com/v1")
        default_headers = None
        # OpenAI 는 "openai/" 등 provider 접두사를 받지 않음 — 떼어냄
        if "/" in chunk_model:
            chunk_model = chunk_model.split("/", 1)[1]
    else:  # openrouter
        api_key = openrouter_key
        base_url = openrouter_cfg.get("base_url", "https://openrouter.ai/api/v1")
        default_headers = {
            "HTTP-Referer": "https://integrated-work-platform",
            "X-Title": "IntegratedPlatform",
        }
        # OpenRouter 는 "provider/model" 형식 — 접두사 자동 보강
        if "/" not in chunk_model:
            chunk_model = "openai/" + chunk_model

    # 타임아웃은 넉넉하게(기본 600초). 대용량 윈도우(최대 30k토큰) 추론 모델 대응.
    chunk_timeout = config.get("llm_chunk_timeout", 600)
    log.info("LLM 청킹 provider=%s, model=%s, timeout=%ss", provider, chunk_model, chunk_timeout)

    # max_retries=1: 타임아웃 시 동일 대기를 반복하지 않도록 재시도를 제한(총 대기 한계).
    client_kwargs = {"api_key": api_key, "base_url": base_url, "max_retries": 1}
    if default_headers:
        client_kwargs["default_headers"] = default_headers
    client = OpenAI(**client_kwargs)

    # ── Heartbeat: API 응답 대기 중 30초마다 경과 시간 로그 출력 ──────────
    # LLM 호출은 수 분이 걸릴 수 있어 터미널이 멈춘 것처럼 보일 수 있다.
    # 별도 스레드에서 주기적으로 로그를 찍어 진행 중임을 알린다.
    _hb_stop = threading.Event()

    def _heartbeat():
        start = time.monotonic()
        interval = 30  # 초
        while not _hb_stop.wait(timeout=interval):
            elapsed = int(time.monotonic() - start)
            log.info(
                "LLM 청킹 API 응답 대기 중… (%ds 경과, 모델=%s)",
                elapsed, chunk_model,
            )

    _hb_thread = threading.Thread(target=_heartbeat, daemon=True)
    _hb_thread.start()

    try:
        resp = client.chat.completions.create(
            model=chunk_model,
            messages=[
                {"role": "system", "content": _CHUNK_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            response_format={"type": "json_object"},
            timeout=chunk_timeout,
        )
        raw = resp.choices[0].message.content or "{}"
    except Exception as e:
        log.warning("LLM 청킹 API 호출 실패 (%s): %s", provider, e)
        return []
    finally:
        _hb_stop.set()   # heartbeat 스레드 종료

    # JSON 파싱 (fallback 포함)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
            except Exception:
                data = {}
        else:
            # Try to find JSON object anywhere in response
            m2 = re.search(r'\{[^{}]*"chunks"[^{}]*\[.*?\]\s*\}', raw, re.DOTALL)
            data = json.loads(m2.group(0)) if m2 else {}

    return [
        c.get("text", "").strip()
        for c in data.get("chunks", [])
        if c.get("text", "").strip()
    ]


def chunk_text(text: str, config: dict) -> list[str]:
    """
    LLM 기반 의미 단위 청킹.

    Args:
        text: 입력 텍스트 (표는 [TABLE START]...[TABLE END] 마커 포함 가능)
        config: 앱 설정 dict (openrouter 키 + llm_chunk_model 필요)

    Returns:
        청크 문자열 목록
    """
    encoder = _get_encoding()
    if encoder is None:
        log.warning("tiktoken 미설치. 단순 청킹으로 대체.")
        return simple_chunk(text)

    tokens = encoder.encode(text)

    if len(tokens) <= WINDOW_TOKENS:
        windows = [text]
    else:
        windows = list(_slice_windows(tokens, encoder, WINDOW_TOKENS, HOP_TOKENS))

    seen: set[str] = set()
    chunks: list[str] = []

    for w_idx, window_text in enumerate(windows):
        log.info("LLM 청킹 윈도우 %d/%d (%d토큰)", w_idx + 1, len(windows), len(encoder.encode(window_text)))
        window_chunks = _call_llm_chunk(window_text, config)

        if not window_chunks:
            # LLM 실패 → 단락 분할로 대체
            log.warning("LLM 청킹 실패. 단락 분할 사용.")
            window_chunks = [p.strip() for p in window_text.split("\n\n") if p.strip()]

        for chunk in window_chunks:
            key = _normalize_key(chunk)
            if key and key not in seen:
                seen.add(key)
                chunks.append(chunk)

    log.info("LLM 청킹 완료: %d개 청크", len(chunks))
    return chunks


def simple_chunk(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    """Fallback: 문자 기반 단순 청킹."""
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(text) <= chunk_size:
        return [text] if text.strip() else []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end < len(text):
            boundary = max(
                text.rfind("\n\n", start, end),
                text.rfind(".\n", start, end),
                text.rfind("。", start, end),
            )
            if boundary > start + chunk_size // 2:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap
    return chunks
