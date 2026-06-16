"""
법률 문서 → FAISS 벡터 DB 빌더.
sentence-transformers BGE-M3 모델로 직접 임베딩.
DOCX / PDF / TXT / HWP 지원.
법령별 분리 인덱스: {law_name}_idx.index + {law_name}_store.json
"""
import glob
import json
import os
import re
import shutil
import tempfile

import numpy as np

from logger import get_logger

log = get_logger("legal_db_builder")

_MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "bge-m3")
_emb_model = None


def _get_embed_model():
    global _emb_model
    if _emb_model is None:
        from sentence_transformers import SentenceTransformer
        log.info("BGE-M3 임베딩 모델 로딩 중... (%s)", _MODEL_PATH)
        _emb_model = SentenceTransformer(_MODEL_PATH if os.path.exists(_MODEL_PATH) else "BAAI/bge-m3")
        # sentence-transformers: get_sentence_embedding_dimension → get_embedding_dimension 으로 개명됨
        get_dim = getattr(_emb_model, "get_embedding_dimension", None) \
                  or _emb_model.get_sentence_embedding_dimension
        log.info("BGE-M3 모델 로딩 완료 (dim=%d)", get_dim())
    return _emb_model


def _embed_via_http(texts: list[str], url: str, api_key: str = "") -> np.ndarray:
    """HTTP 임베딩 서버(RunPod 등)를 통해 배치 임베딩을 수행합니다."""
    import requests
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    vecs = []
    # 서버는 텍스트 배열을 한 번에 받을 수 있지만 메모리 안전을 위해 16개씩 분할
    batch_size = 16
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        r = requests.post(
            f"{url}/v1/embeddings",
            json={"model": "bge-m3", "input": batch},
            headers=headers,
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()["data"]
        data.sort(key=lambda x: x["index"])
        vecs.extend([d["embedding"] for d in data])
    return np.array(vecs, dtype="float32")


# ── FAISS Unicode-경로 안전 래퍼 ─────────────────────────────────────────────
# faiss의 C++ I/O는 Windows에서 fopen(const char*)을 사용하므로
# 한글 등 비-ASCII 파일명이 ANSI 코드페이지와 mismatch되어 실패함.
# (Illegal byte sequence: could not open ...)
# → ASCII 임시 파일로 우회 후 os.replace / shutil.copy 로 한글 경로 처리.

def _path_is_safe_for_faiss(path: str) -> bool:
    """파일명 부분이 ASCII만으로 구성되어 faiss 직접 I/O가 가능한지."""
    base = os.path.basename(path)
    try:
        base.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def faiss_write_index_safe(index, path: str) -> None:
    """한글 경로 안전 faiss.write_index. 같은 디렉터리에 ASCII 임시 파일로 쓴 뒤 atomic rename."""
    import faiss
    if _path_is_safe_for_faiss(path):
        faiss.write_index(index, path)
        return
    dir_ = os.path.dirname(path) or "."
    os.makedirs(dir_, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(suffix=".index", prefix="_faiss_tmp_", dir=dir_)
    os.close(fd)
    try:
        faiss.write_index(index, tmp_path)
        os.replace(tmp_path, path)   # os.replace는 Windows에서 wide-char API 사용 → 한글 OK
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def faiss_read_index_safe(path: str):
    """한글 경로 안전 faiss.read_index. 한글 경로면 ASCII 임시 파일로 복사 후 읽음."""
    import faiss
    if _path_is_safe_for_faiss(path):
        return faiss.read_index(path)
    dir_ = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(suffix=".index", prefix="_faiss_tmp_", dir=dir_)
    os.close(fd)
    try:
        shutil.copyfile(path, tmp_path)
        return faiss.read_index(tmp_path)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


# ── 텍스트 추출 ──────────────────────────────────────────────────────────────

def _extract_file(path: str, config: dict | None = None) -> list[dict]:
    """파일 확장자에 따라 적절한 파서로 섹션 목록을 반환합니다."""
    try:
        from read_docx_util import read_file_sections, read_file_with_llm_chunks
        if config:
            return read_file_with_llm_chunks(path, config)
        return read_file_sections(path)
    except Exception as e:
        log.warning("파일 파싱 오류 (%s): %s", path, e)
        return []


# ── 청킹 ────────────────────────────────────────────────────────────────────

def _split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """텍스트를 chunk_size 이하의 청크로 분할 (overlap 포함)."""
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(text) <= chunk_size:
        return [text] if text.strip() else []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end < len(text):
            boundary = max(
                text.rfind("。", start, end),
                text.rfind(".\n", start, end),
                text.rfind("\n\n", start, end),
            )
            if boundary > start + chunk_size // 2:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap
    return chunks


def _make_chunks(sections: list[dict], source_name: str, chunk_size: int, overlap: int) -> list[str]:
    """섹션 목록 → 포맷된 청크 문자열 목록."""
    chunks = []
    for sec in sections:
        title = sec.get("title", "").strip()
        content = sec.get("content", "").strip()
        if not content:
            continue
        source_label = f"{source_name} {title}".strip() if title else source_name
        for piece in _split_text(content, chunk_size, overlap):
            chunks.append(f"[법률정보]출처: {source_label}\n[법률조항]{piece}")
    return chunks


# ── 임베딩 + 인덱싱 ─────────────────────────────────────────────────────────

def _embed_via_serverless(texts: list[str], batch_size: int = 32, progress_callback=None) -> np.ndarray:
    """RunPod Serverless 엔드포인트로 배치 임베딩."""
    import runpod_client
    vecs = []
    total = len(texts)
    for i in range(0, total, batch_size):
        batch = texts[i:i + batch_size]
        embs = runpod_client.embed_texts(batch)
        vecs.extend(embs)
        if progress_callback:
            progress_callback(min(i + batch_size, total), total, "Serverless 임베딩 중...")
    return np.array(vecs, dtype="float32")


def _embed_chunks(chunks: list[str], batch_size: int = 16, progress_callback=None) -> np.ndarray:
    # 1순위: RunPod Serverless
    try:
        import runpod_client
        if runpod_client.serverless_enabled():
            log.info("RunPod Serverless 임베딩 사용 (%d 청크)", len(chunks))
            return _embed_via_serverless(chunks, progress_callback=progress_callback)
    except Exception as e:
        log.warning("Serverless 임베딩 실패, 다음 방식으로 폴백: %s", e)

    # 2순위: EMBEDDING_SERVER_URL HTTP 서버(원격 Pod)
    remote_url = os.environ.get("EMBEDDING_SERVER_URL", "")
    if remote_url:
        api_key = os.environ.get("INFERENCE_API_KEY", "")
        log.info("HTTP 임베딩 서버 사용: %s (%d 청크)", remote_url, len(chunks))
        if progress_callback:
            progress_callback(0, len(chunks), "HTTP 임베딩 서버로 임베딩 중...")
        vecs = _embed_via_http(chunks, remote_url, api_key)
        if progress_callback:
            progress_callback(len(chunks), len(chunks), "임베딩 완료")
        return vecs

    model = _get_embed_model()
    all_vecs = []
    total = len(chunks)
    for i in range(0, total, batch_size):
        batch = chunks[i:i + batch_size]
        vecs = model.encode(batch, normalize_embeddings=True, show_progress_bar=False)
        all_vecs.append(vecs)
        if progress_callback:
            progress_callback(min(i + batch_size, total), total, "임베딩 중...")
    return np.vstack(all_vecs).astype("float32")


# ── 공개 API ─────────────────────────────────────────────────────────────────

def build_index(
    file_paths: list[str],
    output_dir: str,
    law_name: str = "",
    store_filename: str | None = None,
    index_filename: str | None = None,
    chunk_size: int = 800,
    overlap: int = 100,
    append: bool = False,
    use_llm_chunking: bool = False,
    llm_config: dict | None = None,
    progress_callback=None,
) -> dict:
    """
    업로드된 파일로 FAISS 인덱스를 구축합니다.

    Args:
        file_paths: 처리할 파일 경로 목록
        output_dir: 결과 파일 저장 디렉터리
        law_name: 법령명 (지정 시 {law_name}_store.json / {law_name}_idx.index 자동 생성)
        store_filename: 문서 스토어 JSON 파일명 (law_name 미지정 시 사용)
        index_filename: FAISS 인덱스 파일명 (law_name 미지정 시 사용)
        chunk_size: 청크당 최대 문자 수 (use_llm_chunking=False 시)
        overlap: 청크 간 중복 문자 수 (use_llm_chunking=False 시)
        append: True이면 기존 DB에 추가; False이면 DB 새로 생성
        use_llm_chunking: True이면 LLM 기반 의미 단위 청킹 사용
        llm_config: OpenRouter 등 LLM 설정 (use_llm_chunking=True 시 필요)
        progress_callback: (current, total, message) 호출 가능 객체

    Returns:
        {"total_chunks": int, "total_files": int, "dim": int, "law_name": str}
    """
    import faiss

    # 파일명 결정
    if law_name:
        store_fn = f"{law_name}_store.json"
        index_fn = f"{law_name}_idx.index"
    else:
        store_fn = store_filename or "legal_store.json"
        index_fn = index_filename or "legal_idx.index"

    os.makedirs(output_dir, exist_ok=True)
    store_path = os.path.join(output_dir, store_fn)
    index_path = os.path.join(output_dir, index_fn)

    # 기존 데이터 로드 (append 모드)
    existing_docs: dict[int, str] = {}
    existing_index = None

    if append and os.path.exists(store_path) and os.path.exists(index_path):
        try:
            with open(store_path, encoding="utf-8") as f:
                existing_docs = {int(k): v for k, v in json.load(f).items()}
            existing_index = faiss_read_index_safe(index_path)
            log.info("기존 DB 로드: %d건", len(existing_docs))
        except Exception as e:
            log.warning("기존 DB 로드 실패 (새로 생성): %s", e)

    # LLM 청킹 설정
    chunking_config = llm_config if use_llm_chunking else None

    # 텍스트 추출 + 청킹
    def _process_file(path: str) -> tuple[str, list[str]]:
        source_name = os.path.splitext(os.path.basename(path))[0]
        sections = _extract_file(path, config=chunking_config)
        if chunking_config:
            # LLM 청킹: 섹션이 이미 의미 단위 → 법률 메타 태그만 추가
            chunks = [
                f"[법률정보]출처: {law_name or source_name}\n[법률조항]{sec.get('content','').strip()}"
                for sec in sections
                if sec.get("content", "").strip()
            ]
        else:
            chunks = _make_chunks(sections, law_name or source_name, chunk_size, overlap)
        return source_name, chunks

    all_chunks: list[str] = []
    total_files = len(file_paths)

    # LLM 청킹은 네트워크 대기(I/O)가 지배적이므로 파일 단위로 스레드 병렬 처리하여
    # 전체 시간을 크게 단축한다. (단순 문자 청킹은 CPU 작업이라 병렬화 이득 없음 → 순차)
    concurrency = 1
    if chunking_config:
        try:
            concurrency = max(1, int(chunking_config.get("llm_chunk_concurrency", 4)))
        except (TypeError, ValueError):
            concurrency = 4
    if total_files:
        concurrency = min(concurrency, total_files)

    done = 0
    if concurrency > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        log.info("청킹 병렬 처리: %d개 파일, 동시 실행 %d", total_files, concurrency)
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            futures = [ex.submit(_process_file, p) for p in file_paths]
            for fut in as_completed(futures):
                source_name, chunks = fut.result()
                all_chunks.extend(chunks)
                done += 1
                log.info("파일 처리 완료: %s → %d 청크 (%d/%d)",
                         source_name, len(chunks), done, total_files)
                if progress_callback:
                    progress_callback(done, total_files, f"청킹 {done}/{total_files}: {source_name}")
    else:
        for path in file_paths:
            source_name, chunks = _process_file(path)
            all_chunks.extend(chunks)
            done += 1
            log.info("파일 처리 완료: %s → %d 청크 (%d/%d)",
                     source_name, len(chunks), done, total_files)
            if progress_callback:
                progress_callback(done, total_files, f"청킹 {done}/{total_files}: {source_name}")

    if not all_chunks:
        return {"total_chunks": 0, "total_files": len(file_paths), "dim": 0, "law_name": law_name}

    # 임베딩
    if progress_callback:
        progress_callback(0, len(all_chunks), "임베딩 시작...")
    vectors = _embed_chunks(all_chunks, progress_callback=progress_callback)
    dim = vectors.shape[1]

    # FAISS 인덱스 구성
    start_id = len(existing_docs)
    new_docs = {start_id + i: chunk for i, chunk in enumerate(all_chunks)}

    if append and existing_index is not None and existing_index.d == dim:
        existing_index.add(vectors)
        final_index = existing_index
        final_docs = {**existing_docs, **new_docs}
    else:
        index = faiss.IndexFlatIP(dim)
        if append and existing_index is not None:
            log.warning("차원 불일치로 기존 인덱스 폐기 (기존=%d, 신규=%d)", existing_index.d, dim)
        index.add(vectors)
        final_index = index
        final_docs = new_docs if not append else {**existing_docs, **new_docs}

    # 저장
    with open(store_path, "w", encoding="utf-8") as f:
        json.dump(final_docs, f, ensure_ascii=False)
    faiss_write_index_safe(final_index, index_path)

    result = {
        "total_chunks": len(final_docs),
        "total_files": len(file_paths),
        "dim": dim,
        "law_name": law_name,
    }
    log.info("DB 구축 완료: 총 %d건, dim=%d → %s (%s)", result["total_chunks"], dim, output_dir, store_fn)

    if progress_callback:
        progress_callback(len(all_chunks), len(all_chunks), "완료")

    return result


def clear_index(output_dir: str, law_name: str = "", store_filename: str = "", index_filename: str = "") -> None:
    """인덱스 파일 삭제."""
    if law_name:
        fnames = [f"{law_name}_store.json", f"{law_name}_idx.index"]
    else:
        fnames = [store_filename, index_filename]
    for fname in fnames:
        if fname:
            path = os.path.join(output_dir, fname)
            if os.path.exists(path):
                os.remove(path)
    log.info("DB 초기화 완료: %s (%s)", output_dir, law_name or store_filename)


def rebuild_index_from_store(store_path: str, index_path: str, batch_size: int = 16, progress_callback=None) -> bool:
    """
    store JSON 파일로부터 FAISS index를 재구축합니다.
    git에 바이너리 index 파일이 없을 때 앱 시작 시 자동 호출됩니다.

    Returns:
        True if successful, False otherwise
    """
    import faiss

    try:
        with open(store_path, encoding="utf-8") as f:
            docs: dict[int, str] = {int(k): v for k, v in json.load(f).items()}
    except Exception as e:
        log.warning("store 로드 실패 (%s): %s", store_path, e)
        return False

    if not docs:
        return False

    chunks = [docs[i] for i in sorted(docs.keys())]
    log.info("store에서 FAISS index 재구축 중: %d 청크 (%s)", len(chunks), store_path)

    try:
        vectors = _embed_chunks(chunks, batch_size=batch_size, progress_callback=progress_callback)
    except Exception as e:
        log.warning("임베딩 실패 (%s): %s", store_path, e)
        return False

    dim = vectors.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(vectors)

    try:
        faiss_write_index_safe(index, index_path)
        log.info("FAISS index 재구축 완료: %s (dim=%d, n=%d)", index_path, dim, len(chunks))
        return True
    except Exception as e:
        log.warning("index 저장 실패 (%s): %s", index_path, e)
        return False


def list_law_indexes(output_dir: str) -> list[dict]:
    """법령별 인덱스 목록 반환. {law_name, doc_count, store_kb, index_kb} 목록."""
    result = []
    if not os.path.isdir(output_dir):
        return result
    for idx_file in sorted(glob.glob(os.path.join(output_dir, "*_idx.index"))):
        law_name = os.path.basename(idx_file)[: -len("_idx.index")]
        info = get_db_info(output_dir, law_name=law_name)
        result.append({"law_name": law_name, **info})
    return result


def get_db_info(output_dir: str, law_name: str = "", store_filename: str = "", index_filename: str = "") -> dict:
    """현재 DB 상태 반환."""
    if law_name:
        store_fn = f"{law_name}_store.json"
        index_fn = f"{law_name}_idx.index"
    else:
        store_fn = store_filename or "legal_store.json"
        index_fn = index_filename or "legal_idx.index"

    store_path = os.path.join(output_dir, store_fn)
    index_path = os.path.join(output_dir, index_fn)

    doc_count = 0
    store_kb = 0

    if os.path.exists(store_path):
        try:
            with open(store_path, encoding="utf-8") as f:
                doc_count = len(json.load(f))
        except Exception:
            pass
        store_kb = os.path.getsize(store_path) // 1024

    index_kb = 0
    if os.path.exists(index_path):
        index_kb = os.path.getsize(index_path) // 1024

    return {
        "doc_count": doc_count,
        "store_kb": store_kb,
        "index_kb": index_kb,
        "store_exists": os.path.exists(store_path),
        "index_exists": os.path.exists(index_path),
    }
