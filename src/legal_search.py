"""
법률 검색 에이전트
OpenRouter LLM + FAISS 벡터 검색 (법령별 분리 인덱스 통합 검색) + 대화 메모리 자동 요약
"""
import json
import os
import requests
import numpy as np
from pathlib import Path
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

BASE_DIR = Path(__file__).parent.parent


def _inference_auth_headers() -> dict:
    """INFERENCE_API_KEY 환경변수가 설정된 경우 Authorization 헤더를 반환합니다."""
    key = os.environ.get("INFERENCE_API_KEY", "")
    return {"Authorization": f"Bearer {key}"} if key else {}


# 법령 FAISS 인덱스는 용량이 커서 사용자(에이전트 인스턴스)별로 중복 로드하지 않고
# faiss_dir 경로 기준으로 프로세스 전역 공유한다. reload 시 dict 를 in-place 로
# 갱신하므로 이미 생성된 모든 에이전트에 즉시 반영된다.
_INDEX_CACHE: dict[str, dict] = {}


def _make_llm(llm_cfg: dict, openrouter_cfg: dict) -> ChatOpenAI:
    provider = llm_cfg.get("provider", "openrouter")
    if provider == "openrouter":
        return ChatOpenAI(
            base_url=openrouter_cfg["base_url"],
            api_key=openrouter_cfg["api_key"],
            model=llm_cfg["model"],
            temperature=llm_cfg.get("temperature", 0.7),
            max_tokens=llm_cfg.get("max_tokens", 4096),
            max_retries=1,
        )
    else:
        return ChatOpenAI(
            base_url=llm_cfg["base_url"],
            api_key=llm_cfg.get("api_key", "not-needed"),
            model=llm_cfg["model"],
            temperature=llm_cfg.get("temperature", 0),
            max_tokens=llm_cfg.get("max_tokens", 4096),
            timeout=llm_cfg.get("timeout", 120),
            max_retries=0,
        )


class LegalSearchAgent:
    """
    법률 검색 에이전트.

    기능:
    - 사용자 질의 → 키워드 추출 → FAISS 벡터 검색 (모든 법령 인덱스 통합) → 리랭킹 → LLM 요약
    - 로컬 임베딩 서버 없을 시 키워드 텍스트 매칭으로 자동 대체
    - 대화 메모리 관리 + 자동 요약 (max_chars 초과 시)
    """

    def __init__(self, config: dict):
        self.config = config
        self.openrouter = config.get("openrouter", {})
        self.db_cfg = config.get("legal_db", {})
        self.emb_cfg = config.get("legal_embedding", {})
        self.rerank_cfg = config.get("legal_rerank", {})
        self.mem_cfg = config.get("legal_memory", {"max_chars": 5000})

        # {law_name: (faiss_index, docs_dict)} — 모든 법령 인덱스
        self._law_indexes: dict[str, tuple] = {}
        self._load_db()

        # 백엔드 진단 로그 (Serverless 활성 여부 / 인덱스 로드 개수)
        try:
            from logger import get_logger as _gl
            import runpod_client
            _gl("legal_search").info(
                "LegalSearchAgent init: serverless=%s, endpoint_id_set=%s, api_key_set=%s, 인덱스=%d개",
                runpod_client.serverless_enabled(),
                bool(os.environ.get("RUNPOD_ENDPOINT_ID")),
                bool(os.environ.get("RUNPOD_API_KEY")),
                len(self._law_indexes),
            )
        except Exception as _e:
            from logger import get_logger as _gl
            _gl("legal_search").warning("백엔드 진단 로그 실패: %s", _e)

        # 대화 히스토리
        self.history: list = []

        # 유저 페르소나 (COSTAR) — 설정 시 답변 생성 system 프롬프트에 주입.
        # 반드시 해당 유저(IP)의 페르소나만 set 되어야 한다.
        self.persona_block: str = ""

        self._keyword_llm: Optional[ChatOpenAI] = None
        self._summary_llm: Optional[ChatOpenAI] = None
        self._memory_llm: Optional[ChatOpenAI] = None

    def _load_db(self, force: bool = False):
        """faiss_dir의 모든 *_idx.index 파일을 스캔하여 로드합니다.

        인덱스는 프로세스 전역(_INDEX_CACHE)으로 공유 — 유저별 에이전트가
        늘어나도 FAISS 메모리는 1벌만 유지된다.
        """
        faiss_dir = (BASE_DIR / self.db_cfg.get("faiss_dir", "./legal_db")).resolve()
        cache_key = str(faiss_dir)
        cached = _INDEX_CACHE.get(cache_key)
        if cached is not None and not force:
            self._law_indexes = cached
            return

        loaded: dict[str, tuple] = {}
        self._law_indexes = loaded

        if not faiss_dir.exists():
            return

        try:
            import faiss
        except ImportError:
            return

        # store JSON이 있는 법령을 모두 수집 (index 파일 유무와 무관)
        store_files = sorted(faiss_dir.glob("*_store.json"))
        for store_file in store_files:
            law_name = store_file.stem[: -len("_store")]
            idx_file = faiss_dir / f"{law_name}_idx.index"

            # index 파일이 없으면 store JSON으로 자동 재구축
            if not idx_file.exists():
                from logger import get_logger as _gl
                _gl("legal_search").info(
                    "index 파일 없음, store에서 재구축 시작: %s", law_name
                )
                try:
                    from legal_db_builder import rebuild_index_from_store
                    ok = rebuild_index_from_store(str(store_file), str(idx_file))
                    if not ok:
                        from logger import get_logger as _gl2
                        _gl2("legal_search").warning("index 재구축 실패, 건너뜀: %s", law_name)
                        continue
                except Exception as e:
                    from logger import get_logger as _gl3
                    _gl3("legal_search").warning("index 재구축 오류 (%s): %s", law_name, e)
                    continue

            try:
                from legal_db_builder import faiss_read_index_safe
                index = faiss_read_index_safe(str(idx_file))
                with open(store_file, encoding="utf-8") as f:
                    docs = {int(k): v for k, v in json.load(f).items()}
                loaded[law_name] = (index, docs)
            except Exception as e:
                from logger import get_logger
                get_logger("legal_search").warning("법령 인덱스 로드 실패 (%s): %s", law_name, e)

        # 캐시 커밋 — 기존 캐시가 있으면 in-place 갱신해 공유 참조를 유지한다.
        if cached is not None:
            cached.clear()
            cached.update(loaded)
            self._law_indexes = cached
        else:
            _INDEX_CACHE[cache_key] = loaded

    def _get_keyword_llm(self) -> ChatOpenAI:
        if self._keyword_llm is None:
            self._keyword_llm = _make_llm(
                self.config.get("legal_keyword_llm", {}), self.openrouter
            )
        return self._keyword_llm

    def _get_summary_llm(self) -> ChatOpenAI:
        if self._summary_llm is None:
            self._summary_llm = _make_llm(
                self.config.get("legal_summary_llm", {}), self.openrouter
            )
        return self._summary_llm

    def _get_memory_llm(self) -> ChatOpenAI:
        if self._memory_llm is None:
            self._memory_llm = _make_llm(
                self.config.get("legal_memory_llm", {}), self.openrouter
            )
        return self._memory_llm

    # ─── 키워드 추출 ──────────────────────────────────────────────

    def _extract_keywords(self, query: str) -> list[str]:
        prompt = ChatPromptTemplate.from_messages([
            ("system", """당신은 법률 질문에서 핵심 키워드를 추출하는 전문가입니다.
질문에서 벡터 검색에 사용할 핵심 키워드 또는 하위 질문을 추출하세요.

출력 형식 (JSON 배열만):
["키워드1", "키워드2", "키워드3"]"""),
            ("human", "[질문]\n{query}"),
        ])
        chain = prompt | self._get_keyword_llm() | StrOutputParser()
        try:
            result = chain.invoke({"query": query})
            import ast
            cleaned = result.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            return ast.literal_eval(cleaned.strip())
        except Exception:
            return [query]

    # ─── 임베딩 ───────────────────────────────────────────────────

    def _embed_text(self, text: str) -> Optional[np.ndarray]:
        from logger import get_logger as _gl
        _log = _gl("legal_search")
        # 1순위: RunPod Serverless
        try:
            import runpod_client
            if runpod_client.serverless_enabled():
                _log.info("임베딩: RunPod Serverless 호출")
                embs = runpod_client.embed_texts([text])
                if embs:
                    v = np.array(embs[0], dtype=np.float32)
                    v /= np.linalg.norm(v) + 1e-12
                    return v
                _log.warning("Serverless 임베딩 응답이 비어있음")
            else:
                _log.info("임베딩: Serverless 비활성(env 미설정) → HTTP 폴백")
        except Exception as e:
            _log.warning("Serverless 임베딩 실패 → HTTP 폴백: %s", e)

        # 2순위: HTTP 임베딩 서버 (로컬/원격 Pod)
        url = os.environ.get("EMBEDDING_SERVER_URL") or self.emb_cfg.get("url", "http://127.0.0.1:8081")
        model = self.emb_cfg.get("model", "bge-m3")
        timeout = self.emb_cfg.get("timeout", 45)
        headers = _inference_auth_headers()
        try:
            r = requests.post(
                f"{url}/v1/embeddings",
                json={"model": model, "input": text},
                headers=headers,
                timeout=timeout,
            )
            if r.ok and "data" in r.json():
                v = np.array(r.json()["data"][0]["embedding"], dtype=np.float32)
                v /= np.linalg.norm(v) + 1e-12
                return v
        except Exception:
            pass
        return None

    # ─── 벡터 검색 (모든 법령 인덱스 통합) ──────────────────────

    def _vector_search(self, query: str, k: int) -> list[str]:
        if not self._law_indexes:
            return []
        vec = self._embed_text(query)
        if vec is None:
            return self._keyword_search(query, k)

        q = vec.reshape(1, -1).astype("float32")
        all_results: list[tuple[float, str]] = []

        for law_name, (index, docs) in self._law_indexes.items():
            try:
                top = min(k, index.ntotal)
                if top == 0:
                    continue
                D, I = index.search(q, top)
                for score, idx in zip(D[0], I[0]):
                    if idx != -1 and int(idx) in docs:
                        all_results.append((float(score), docs[int(idx)]))
            except Exception:
                pass

        all_results.sort(key=lambda x: -x[0])
        return [doc for _, doc in all_results[:k]]

    def _keyword_search(self, query: str, k: int) -> list[str]:
        """임베딩 서버 없을 때 단순 키워드 매칭 폴백"""
        if not self._law_indexes:
            return []
        words = set(query.split())
        scored: list[tuple[int, str]] = []
        for _, (_, docs) in self._law_indexes.items():
            for doc in docs.values():
                score = sum(1 for w in words if w in doc)
                if score > 0:
                    scored.append((score, doc))
        scored.sort(key=lambda x: -x[0])
        return [d for _, d in scored[:k]]

    # ─── 리랭킹 ──────────────────────────────────────────────────

    def _rerank(self, query: str, candidates: list[str], top_k: int) -> list[str]:
        if not candidates:
            return []

        # 1순위: RunPod Serverless
        try:
            import runpod_client
            if runpod_client.serverless_enabled():
                results = runpod_client.rerank(query, candidates)
                if results:
                    return [item["text"] for item in results[:top_k]]
        except Exception:
            pass

        # 2순위: HTTP 리랭크 서버 (로컬/원격 Pod)
        rerank_url = os.environ.get("RERANK_SERVER_URL") or self.rerank_cfg.get("url", "http://127.0.0.1:8082/rerank")
        timeout = self.rerank_cfg.get("timeout", 30)
        headers = _inference_auth_headers()
        try:
            r = requests.post(
                rerank_url,
                json={"query": query, "candidates": candidates},
                headers=headers,
                timeout=timeout,
            )
            if r.ok:
                results = r.json().get("results", [])
                return [item["text"] for item in results[:top_k]]
        except Exception:
            pass
        return candidates[:top_k]

    # ─── 최종 답변 생성 ────────────────────────────────────────────

    def _generate_answer(self, query: str, context_docs: list[str]) -> str:
        context = "\n\n---\n\n".join(context_docs) if context_docs else "관련 조항을 찾지 못했습니다."
        no_rag = not context_docs

        system_msg = """[Context]
당신은 한국의 법령, 감독규정, 규제 문서를 전문으로 다루는 법률 전문가입니다.
사용자는 금융기관 리스크관리·준법감시 담당자로, 실무 적용을 위한 정확한 법령 근거가 필요합니다.

[Objective]
제공된 법률 조항을 근거로 사용자 질문에 정확하게 답변하세요.

[Style]
원문의 의미를 변형하거나 재해석하지 않습니다. 법령 원문은 인용 부호(" ")로 표시하세요.

[Tone]
전문적이고 명확하게. 확인되지 않은 내용은 단정하지 마세요.

[Audience]
금융기관 리스크관리·준법감시 실무 담당자

[Response]
다음 순서로 작성하세요:
1. 핵심 답변 (2~3문장)
2. 근거 조항: [법령명] 제X조 제X항 — 해당 조문 원문 인용
3. 실무 유의사항 (있는 경우)
관련 조항을 찾지 못한 경우: "해당 DB에서 관련 조항을 찾지 못했습니다. 일반 지식으로 답변합니다."라고 먼저 밝히세요."""

        # 유저 페르소나(COSTAR) — 해당 IP 유저로 확인된 경우에만 set 되어 있음.
        if self.persona_block:
            system_msg += "\n\n" + self.persona_block

        # ※ ChatPromptTemplate 을 쓰지 않고 메시지 객체를 직접 구성한다.
        #   히스토리·법령 원문에 포함된 중괄호({})가 템플릿 변수로 오인되어
        #   INVALID_PROMPT_INPUT 오류를 일으키는 문제(메모리 압축 요약 직후 발생) 방지.
        messages = [SystemMessage(content=system_msg)]

        for msg in self.history[-12:]:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            else:
                messages.append(AIMessage(content=msg["content"]))

        if no_rag:
            human_content = f"[질문]\n{query}\n\n[참고] 데이터베이스에서 관련 조항을 찾지 못했습니다. 일반 지식으로 답변합니다."
        else:
            human_content = f"[질문]\n{query}\n\n[관련 법률 조항]\n{context}"

        messages.append(HumanMessage(content=human_content))

        try:
            resp = self._get_summary_llm().invoke(messages)
            return getattr(resp, "content", None) or str(resp)
        except Exception as e:
            return f"[오류] 답변 생성 실패: {e}"

    # ─── 메모리 관리 ─────────────────────────────────────────────

    def _total_history_chars(self) -> int:
        return sum(len(m["content"]) for m in self.history)

    def _summarize_memory(self):
        if not self.history:
            return
        prompt = ChatPromptTemplate.from_messages([
            ("system", "[Objective] 다음 법률 Q&A 대화를 핵심 내용 위주로 간결하게 요약하세요.\n[Rules] 중요한 법령명, 조문 번호, 핵심 결론을 반드시 포함하세요. 불필요한 인사·부연 제거.\n[Response] 요약문만 출력. 마크다운·설명 없이."),
            ("human", "{history}"),
        ])
        chain = prompt | self._get_memory_llm() | StrOutputParser()
        history_text = "\n".join(
            f"[{m['role'].upper()}] {m['content']}" for m in self.history
        )
        try:
            summary = chain.invoke({"history": history_text})
            self.history = [{"role": "assistant", "content": f"[이전 대화 요약]\n{summary}"}]
        except Exception:
            self.history = self.history[len(self.history) // 2:]

    def _maybe_compress_memory(self):
        max_chars = self.mem_cfg.get("max_chars", 5000)
        if self._total_history_chars() > max_chars:
            self._summarize_memory()

    # ─── 공개 API ────────────────────────────────────────────────

    def search(self, query: str) -> dict:
        """
        사용자 질의를 처리합니다.

        Returns:
            {"answer": str, "keywords": list, "retrieved_docs": list, "search_mode": str}
        """
        default_rank = self.db_cfg.get("default_rank", 5)
        default_rerank = self.db_cfg.get("default_rerank", 3)

        keywords = self._extract_keywords(query)

        search_mode = "no_db"
        all_candidates = []
        if self._law_indexes:
            for kw in keywords:
                docs = self._vector_search(kw, default_rank)
                all_candidates.extend(docs)
            all_candidates = list(dict.fromkeys(all_candidates))

            if self._embed_text(query) is not None:
                search_mode = "vector"
            else:
                search_mode = "keyword"

        top_docs = self._rerank(query, all_candidates, default_rerank)
        answer = self._generate_answer(query, top_docs)

        self.history.append({"role": "user", "content": query})
        self.history.append({"role": "assistant", "content": answer})
        self._maybe_compress_memory()

        return {
            "answer": answer,
            "keywords": keywords,
            "retrieved_docs": top_docs,
            "search_mode": search_mode,
        }

    def get_loaded_laws(self) -> list[str]:
        """로드된 법령 목록 반환."""
        return list(self._law_indexes.keys())

    def reload_db(self):
        """DB 파일이 갱신된 후 모든 인덱스를 다시 로드합니다.

        전역 캐시를 in-place 갱신하므로, 같은 faiss_dir 을 쓰는 다른 유저의
        에이전트에도 즉시 반영된다.
        """
        self._load_db(force=True)

    def clear_history(self):
        self.history.clear()

    def get_history_preview(self) -> str:
        lines = []
        for m in self.history:
            prefix = "사용자" if m["role"] == "user" else "AI"
            lines.append(f"[{prefix}] {m['content'][:80]}{'...' if len(m['content']) > 80 else ''}")
        return "\n".join(lines)
