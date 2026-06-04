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

BASE_DIR = Path(__file__).parent.parent


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

        # 대화 히스토리
        self.history: list = []

        self._keyword_llm: Optional[ChatOpenAI] = None
        self._summary_llm: Optional[ChatOpenAI] = None
        self._memory_llm: Optional[ChatOpenAI] = None

    def _load_db(self):
        """faiss_dir의 모든 *_idx.index 파일을 스캔하여 로드합니다."""
        faiss_dir = (BASE_DIR / self.db_cfg.get("faiss_dir", "./legal_db")).resolve()
        self._law_indexes = {}

        if not faiss_dir.exists():
            return

        try:
            import faiss
        except ImportError:
            return

        for idx_file in sorted(faiss_dir.glob("*_idx.index")):
            law_name = idx_file.stem[: -len("_idx")]
            store_file = faiss_dir / f"{law_name}_store.json"
            if not store_file.exists():
                continue
            try:
                from legal_db_builder import faiss_read_index_safe
                index = faiss_read_index_safe(str(idx_file))
                with open(store_file, encoding="utf-8") as f:
                    docs = {int(k): v for k, v in json.load(f).items()}
                self._law_indexes[law_name] = (index, docs)
            except Exception as e:
                from logger import get_logger
                get_logger("legal_search").warning("법령 인덱스 로드 실패 (%s): %s", law_name, e)

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
        url = self.emb_cfg.get("url", "http://127.0.0.1:8081")
        model = self.emb_cfg.get("model", "bge-m3")
        timeout = self.emb_cfg.get("timeout", 45)
        try:
            r = requests.post(
                f"{url}/v1/embeddings",
                json={"model": model, "input": text},
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
        rerank_url = self.rerank_cfg.get("url", "http://127.0.0.1:8082/rerank")
        timeout = self.rerank_cfg.get("timeout", 30)
        try:
            r = requests.post(
                rerank_url,
                json={"query": query, "candidates": candidates},
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

        messages = [("system", system_msg)]

        for msg in self.history[-12:]:
            messages.append((msg["role"], msg["content"]))

        if no_rag:
            human_content = f"[질문]\n{query}\n\n[참고] 데이터베이스에서 관련 조항을 찾지 못했습니다. 일반 지식으로 답변합니다."
        else:
            human_content = f"[질문]\n{query}\n\n[관련 법률 조항]\n{context}"

        messages.append(("human", human_content))

        prompt = ChatPromptTemplate.from_messages(messages)
        chain = prompt | self._get_summary_llm() | StrOutputParser()
        try:
            return chain.invoke({})
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
        """DB 파일이 갱신된 후 모든 인덱스를 다시 로드합니다."""
        self._law_indexes = {}
        self._load_db()

    def clear_history(self):
        self.history.clear()

    def get_history_preview(self) -> str:
        lines = []
        for m in self.history:
            prefix = "사용자" if m["role"] == "user" else "AI"
            lines.append(f"[{prefix}] {m['content'][:80]}{'...' if len(m['content']) > 80 else ''}")
        return "\n".join(lines)
