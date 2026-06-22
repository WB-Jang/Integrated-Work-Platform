"""
금융감독원(FSS), 한국은행(BOK), 금융위원회(FSC) 규제 동향 수집 및 LLM 요약 에이전트.

데이터 소스:
- FSS: 금융감독원 Open API (API 키 필요; www.fss.or.kr) → 실패 시 네이버 뉴스 폴백
- BOK/FSC: 네이버 뉴스 검색 API (NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 필요)
"""
import datetime
import re
import math

import requests
import numpy as np

from logger import get_logger

log = get_logger("regulatory")

# ── 데이터 소스 URL 상수 ──────────────────────────────────────────────────────
# 구 open.fss.or.kr 서비스 종료 → www.fss.or.kr 로 이전, 파라미터명 auth→authKey
FSS_API_URL     = "http://www.fss.or.kr/fss/kr/openApi/api/fcnInfo.jsp"
_REQUESTS_HEADERS = {"User-Agent": "Mozilla/5.0"}

NAVER_NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"


def _parse_date_input(s: str | None) -> "datetime.date | None":
    """YYYY-MM-DD 또는 YYYYMMDD 문자열을 datetime.date로 변환. 파싱 실패 시 None."""
    if not s:
        return None
    s = s.strip()
    if len(s) == 8 and s.isdigit():
        s = f"{s[:4]}-{s[4:6]}-{s[6:]}"
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        return None


# ── 네이버 뉴스 API ──────────────────────────────────────────────────────────

def _clean_html(text: str) -> str:
    """HTML 태그 제거 + 엔티티 디코딩."""
    import html as _h
    return _h.unescape(re.sub(r'<[^>]+>', '', text)).strip()


def _fetch_naver_news(
    query: str,
    date_from: str | None,
    date_to: str | None,
    count: int,
    client_id: str,
    client_secret: str,
) -> list[dict]:
    """네이버 뉴스 검색 API → [{source, title, url, summary, published_date, lexical_score}, ...]"""
    import email.utils as _eu

    from_dt = _parse_date_input(date_from)
    to_dt   = _parse_date_input(date_to)

    results: list[dict] = []
    start    = 1
    per_page = min(100, max(count * 2, 20))

    while len(results) < count and start <= 1000:
        resp = requests.get(
            NAVER_NEWS_API_URL,
            headers={
                "User-Agent": "Mozilla/5.0",
                "X-Naver-Client-Id": client_id,
                "X-Naver-Client-Secret": client_secret,
            },
            params={"query": query, "display": per_page, "start": start, "sort": "date"},
            timeout=10,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            break

        for item in items:
            pub: datetime.date | None = None
            try:
                t = _eu.parsedate(item.get("pubDate", ""))
                if t:
                    pub = datetime.date(t[0], t[1], t[2])
            except Exception:
                pass

            if from_dt and pub and pub < from_dt:
                continue
            if to_dt and pub and pub > to_dt:
                continue

            results.append({
                "source": "네이버뉴스",
                "title": _clean_html(item.get("title", "")),
                "url": item.get("originallink") or item.get("link", ""),
                "summary": _clean_html(item.get("description", "")),
                "published_date": str(pub) if pub else "",
                "lexical_score": 1.0,
                "match_count": 1,
            })
            if len(results) >= count:
                break

        if len(items) < per_page:
            break
        start += per_page

    log.info("네이버 뉴스 검색 완료 (%r): %d건", query, len(results))
    return results


# ── 기관별 수집 함수 ─────────────────────────────────────────────────────────

def get_fss_updates(
    api_key: str,
    count: int = 3,
    naver_client_id: str = "",
    naver_client_secret: str = "",
) -> list[dict]:
    """금융감독원 Open API → [{source, title, url}, ...].
    FSS API 키 없거나 실패 시 네이버 뉴스로 폴백.
    """
    if api_key:
        try:
            today = datetime.date.today().strftime("%Y%m%d")
            start = (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
            resp = requests.get(
                FSS_API_URL,
                params={
                    "authKey": api_key,
                    "pageCount": max(count, 5),
                    "apiType": "json",
                    "startDate": start,
                    "endDate": today,
                },
                timeout=10,
                headers=_REQUESTS_HEADERS,
            )
            resp.raise_for_status()
            data = resp.content.decode("euc-kr", errors="replace")
            import json as _json
            parsed = _json.loads(data)
            raw_items = parsed.get("reponse", {}).get("result", [])[:count]
            results = [
                {
                    "source": "금융감독원",
                    "title": item.get("subject", "").strip(),
                    "url": item.get("originUrl", "").strip(),
                }
                for item in raw_items
                if item.get("subject")
            ]
            if results:
                log.info("FSS API 수집 완료: %d건", len(results))
                return results
            log.warning("FSS API 결과 0건 → 네이버 폴백")
        except Exception as exc:
            log.warning("FSS API 호출 실패 → 네이버 폴백: %s", exc)

    if naver_client_id and naver_client_secret:
        try:
            items = _fetch_naver_news(
                "금융감독원 금감원", None, None, count, naver_client_id, naver_client_secret,
            )
            if items:
                for it in items:
                    it["source"] = "금융감독원"
                log.info("FSS 네이버 폴백 수집: %d건", len(items))
                return items
        except Exception as exc:
            log.warning("FSS 네이버 폴백 실패: %s", exc)

    log.warning("FSS 수집 실패 (API 키 및 네이버 키 모두 없거나 오류)")
    return []


def get_bok_updates(
    count: int = 3,
    naver_client_id: str = "",
    naver_client_secret: str = "",
) -> list[dict]:
    """한국은행 관련 기사 → [{source, title, url}, ...]. 네이버 API 사용."""
    if naver_client_id and naver_client_secret:
        try:
            items = _fetch_naver_news(
                "한국은행 기준금리", None, None, count, naver_client_id, naver_client_secret,
            )
            if items:
                for it in items:
                    it["source"] = "한국은행"
                log.info("BOK 수집 완료: %d건", len(items))
                return items
        except Exception as exc:
            log.warning("BOK 네이버 검색 실패: %s", exc)
    log.warning("BOK 수집 실패 (네이버 키 없거나 오류)")
    return []


def get_fsc_updates(
    count: int = 3,
    naver_client_id: str = "",
    naver_client_secret: str = "",
) -> list[dict]:
    """금융위원회 관련 기사 → [{source, title, url}, ...]. 네이버 API 사용."""
    if naver_client_id and naver_client_secret:
        try:
            items = _fetch_naver_news(
                "금융위원회", None, None, count, naver_client_id, naver_client_secret,
            )
            if items:
                for it in items:
                    it["source"] = "금융위원회"
                log.info("FSC 수집 완료: %d건", len(items))
                return items
        except Exception as exc:
            log.warning("FSC 네이버 검색 실패: %s", exc)
    log.warning("FSC 수집 실패 (네이버 키 없거나 오류)")
    return []


# ── LLM 요약 ────────────────────────────────────────────────────────────────

def summarize_update(source: str, title: str, url: str, llm) -> str:
    """리스크 관리 관점 2~3문장 요약. 마지막 줄에 출처 URL 포함."""
    from langchain_core.prompts import PromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    template = """당신은 은행 리스크 관리 부서 실무자를 위한 뉴스 브리핑 어시스턴트입니다.
다음 기관의 발표·보도 제목을 보고 리스크 업무 관점에서 핵심적인 시사점을 2~3문장으로 간결하게 요약하세요.

발표기관: {source}
제목: {title}

[필수 조건]
응답의 가장 마지막 줄에 반드시 아래 출처 URL을 텍스트 그대로 표기할 것.
출처: {url}

[요약]:"""

    prompt = PromptTemplate.from_template(template)
    chain = prompt | llm | StrOutputParser()
    return chain.invoke({"source": source, "title": title, "url": url})


def fetch_and_summarize(
    fss_api_key: str,
    llm,
    count_per_source: int = 3,
    naver_client_id: str = "",
    naver_client_secret: str = "",
) -> list[dict]:
    """
    세 기관 데이터 수집 후 각 항목을 LLM으로 요약.

    FSS: FSS API → 네이버 폴백. BOK/FSC: 네이버 API.

    Returns:
        list of dict: source, title, url, summary
    """
    all_items = (
        get_fss_updates(fss_api_key, count_per_source, naver_client_id, naver_client_secret)
        + get_bok_updates(count_per_source, naver_client_id, naver_client_secret)
        + get_fsc_updates(count_per_source, naver_client_id, naver_client_secret)
    )

    if not all_items:
        log.warning("수집된 규제 동향 항목이 없습니다.")
        return []

    results: list[dict] = []
    for item in all_items:
        try:
            summary = summarize_update(item["source"], item["title"], item["url"], llm)
        except Exception as exc:
            log.warning("LLM 요약 실패 (%s): %s", item["title"][:40], exc)
            summary = f"(요약 실패: {exc})\n출처: {item['url']}"
        results.append({**item, "summary": summary})

    log.info("규제 동향 수집·요약 완료: 총 %d건", len(results))
    return results


def extract_search_queries(question: str, llm, max_n: int = 5) -> list[str]:
    """
    질문으로부터 뉴스 헤드라인에 실제 등장할 법한 검색 표현을 최대 max_n개 생성.

    기존 extract_question_keywords()와 달리 같은 개념을 다양하게 변형한
    표현을 생성하여 검색 recall을 높임.
    예: "기준금리 인하 전망" → ["기준금리 인하", "금통위 동결", "한은 금리 결정",
                               "통화정책 완화", "기준금리 인상"]
    """
    from langchain_core.prompts import PromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    template = """[Context]
당신은 금융 규제·리스크 뉴스 검색 시스템의 검색 표현 생성기입니다.
검색 대상: 네이버 뉴스 헤드라인 (금융·경제·규제 섹션)
사용 목적: 같은 개념을 다양하게 표현하여 검색 recall을 높입니다.

[Objective]
아래 질문의 답을 찾기 위해 뉴스 기사 제목에서 검색할 표현을 {max_n}개 생성하세요.

[Rules]
- 각 표현은 실제 뉴스 헤드라인에 등장할 법한 짧은 표현 (1~4 어절).
- 같은 개념을 다르게 표현한 변형도 포함 (동의어·약어·반대 개념 포함).
- 기관명·정책명·인물명 등 고유명사를 우선 사용.
- '경제', '한국', '전망'처럼 과도하게 일반적인 단어만으로 구성된 표현은 제외.

[예시]
질문: 한국은행이 기준금리를 인하할 것 같은지?
출력: 기준금리 인하, 금통위 결정, 한은 통화정책, 금리 동결, 기준금리 인상

[Response]
쉼표 구분 검색 표현 한 줄만 출력. 번호·따옴표·설명 없이.

[질문]
{question}

[검색 표현]:"""
    prompt = PromptTemplate.from_template(template)
    chain = prompt | llm | StrOutputParser()
    try:
        raw = chain.invoke({"question": question, "max_n": max_n})
    except Exception as exc:
        log.warning("검색 표현 생성 실패: %s", exc)
        return [question.strip()] if question.strip() else []

    tokens = re.split(r"[,\n;·•\|]+", raw)
    queries: list[str] = []
    for t in tokens:
        q = t.strip().strip("\"'`[](){}<>")
        q = re.sub(r"^\d+[\.\)]\s*", "", q)
        if not q or len(q) > 30:
            continue
        if q in queries:
            continue
        queries.append(q)
        if len(queries) >= max_n:
            break

    if not queries:
        queries = [question.strip()]
    log.info("검색 표현 생성: %r → %s", question[:40], queries)
    return queries


def rerank_by_question(
    question: str,
    candidates: list[dict],
    embed_url: str,
    embed_model: str = "bge-m3",
    embed_timeout: int = 45,
    top_n: int = 10,
) -> list[dict]:
    """
    질문과 후보 기사를 BGE-M3로 임베딩하여 코사인 유사도 기준 재정렬 후 top_n 반환.

    각 반환 항목에 코사인 유사도를 rerank_score 로 부여한다(관련성 임계값 판정용).
    임베딩 서버 실패 시 렉시컬 순서 그대로 top_n 반환(rerank_score 없음 →
    호출부는 임계값 판정 불가로 보고 렉시컬 신호로 대체한다).
    """
    if not candidates:
        return []

    texts = [
        f"{item.get('title', '')} {item.get('summary', '')[:200]}"
        for item in candidates
    ]

    q_vec = _embed_texts([question], embed_url, embed_model, embed_timeout)
    if q_vec is None:
        log.warning("rerank: 질문 임베딩 실패 → 렉시컬 순서 유지")
        return candidates[:top_n]

    c_vecs = _embed_texts(texts, embed_url, embed_model, embed_timeout)
    if c_vecs is None:
        log.warning("rerank: 기사 임베딩 실패 → 렉시컬 순서 유지")
        return candidates[:top_n]

    try:
        from sklearn.preprocessing import normalize
        q_norm = normalize(q_vec)[0]
        c_norm = normalize(c_vecs)
        sims = c_norm @ q_norm

        ranked_indices = np.argsort(sims)[::-1]
        reranked = []
        for i in ranked_indices[:top_n]:
            item = dict(candidates[i])
            item["rerank_score"] = round(float(sims[i]), 4)
            reranked.append(item)

        log.info(
            "BGE-M3 재정렬 완료: 후보 %d건 → 상위 %d건 (유사도 %.3f~%.3f)",
            len(candidates), len(reranked),
            reranked[-1]["rerank_score"] if reranked else 0,
            reranked[0]["rerank_score"] if reranked else 0,
        )
        return reranked
    except Exception as exc:
        log.warning("rerank 계산 오류: %s → 원래 순서 유지", exc)
        return candidates[:top_n]


def search_news_by_keywords(
    keywords: list[str],
    date_from: str | None = None,
    date_to: str | None = None,
    count: int = 10,
    naver_client_id: str = "",
    naver_client_secret: str = "",
) -> list[dict]:
    """네이버 뉴스 API로 키워드별 검색 후 URL 중복 제거하여 반환.

    네이버 키 미설정 시 빈 리스트 반환.
    반환 항목: source, title, url, summary, published_date, lexical_score, match_count.
    """
    if not (naver_client_id and naver_client_secret):
        log.warning("네이버 API 키 미설정 — 뉴스 검색 불가")
        return []

    try:
        per_kw    = max(count // max(len(keywords), 1), 5)
        seen_urls: set[str] = set()
        merged: list[dict]  = []
        for kw in keywords[:5]:
            for item in _fetch_naver_news(kw, date_from, date_to, per_kw,
                                          naver_client_id, naver_client_secret):
                if item["url"] and item["url"] not in seen_urls:
                    seen_urls.add(item["url"])
                    item["matched_keywords"] = [kw]
                    merged.append(item)
        log.info("네이버 뉴스 통합 결과: %d건", len(merged))
        return merged[:count]
    except Exception as exc:
        log.warning("네이버 뉴스 검색 실패: %s", exc)
        return []


# ── Outlook 메일 발송 ────────────────────────────────────────────────────────

def _is_outlook_available() -> bool:
    """로컬 Outlook COM 클래스(Outlook.Application) 등록 여부 확인."""
    import sys
    if sys.platform != 'win32':
        return False
    try:
        import winreg
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, 'Outlook.Application')
        return True
    except Exception:
        return False


def send_regulatory_email(to_address: str, results: list[dict]) -> None:
    """수집·요약된 규제 동향을 로컬 Outlook으로 메일 발송."""
    if not _is_outlook_available():
        raise RuntimeError(
            "로컬 Microsoft Outlook이 설치되어 있지 않거나 COM 등록이 되어 있지 않습니다. "
            "Outlook 데스크톱 앱을 설치·실행한 후 다시 시도해 주세요."
        )

    import win32com.client
    import pythoncom

    today_str = datetime.date.today().strftime("%Y-%m-%d")

    body_lines = [
        f"[{today_str}] 은행 리스크 업무 관련 주요 규제 동향 브리핑입니다.",
        "",
        "=" * 50,
        "",
    ]

    for item in results:
        body_lines.append(f"[{item['source']}] {item['title']}")
        body_lines.append(item.get("summary", ""))
        body_lines.append("-" * 50)
        body_lines.append("")

    body = "\n".join(body_lines)
    subject = f"[Daily Risk Brief] {today_str} 규제 동향 업데이트"

    pythoncom.CoInitialize()
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)
        mail.To = to_address
        mail.Subject = subject
        mail.Body = body
        mail.Send()
        log.info("규제 동향 메일 발송 완료: %s", to_address)
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


# ── 뉴스 임베딩 + 클러스터링 ────────────────────────────────────────────────

def _embed_texts(texts: list[str], embed_url: str, model: str = "bge-m3", timeout: int = 45) -> np.ndarray | None:
    """BGE-M3 임베딩 서버를 통해 텍스트 목록을 벡터화합니다."""
    try:
        resp = requests.post(
            f"{embed_url.rstrip('/')}/v1/embeddings",
            json={"model": model, "input": texts},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        vecs = [item["embedding"] for item in data["data"]]
        return np.array(vecs, dtype=np.float32)
    except Exception as exc:
        log.warning("임베딩 서버 호출 실패: %s", exc)
        return None


def cluster_news_results(
    results: list[dict],
    query: str,
    embed_url: str,
    embed_model: str = "bge-m3",
    embed_timeout: int = 45,
) -> list[dict]:
    """
    뉴스 검색 결과를 임베딩 후 KMeans 클러스터링하여 클러스터별 대표 기사 2개를 반환합니다.

    Args:
        results: search_news_by_keywords 결과 (source, title, url, summary, ...)
        query: 원래 검색 키워드 (임베딩에 포함하여 의미 정렬에 활용)
        embed_url: BGE-M3 서버 base URL
        embed_model: 모델명
        embed_timeout: 요청 타임아웃

    Returns:
        list of dict: 원본 결과 각 항목에 'cluster' 키 추가,
                      'is_representative'=True인 항목이 클러스터당 최대 2개
    """
    if len(results) < 2:
        for item in results:
            item['cluster'] = 0
            item['is_representative'] = True
            item['cluster_rank'] = 0
            item['cluster_similarity'] = 1.0
        return results

    # 검색어 + 제목 + 요약 합산 텍스트 (각 기사당)
    texts = [
        f"{query} | {item.get('title', '')} | {item.get('summary', '')[:300]}"
        for item in results
    ]

    vecs = _embed_texts(texts, embed_url, embed_model, embed_timeout)
    if vecs is None:
        # 임베딩 실패 시 클러스터링 없이 순서대로 반환
        for i, item in enumerate(results):
            item['cluster'] = i // 3
            item['is_representative'] = (i % 3 < 2)
        return results

    # 클러스터 수: 기사 수에 비례 (최소 2, 최대 min(8, n//2))
    n = len(results)
    k = max(2, min(8, math.ceil(n / 3)))

    try:
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import normalize

        vecs_norm = normalize(vecs)
        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = km.fit_predict(vecs_norm)
        centers = km.cluster_centers_

        # 클러스터 할당
        for item, label in zip(results, labels):
            item['cluster'] = int(label)
            item['is_representative'] = False

        # 각 클러스터에서 centroid와 가장 가까운 기사 2개를 대표로 선정
        cluster_reps: dict[int, list[int]] = {}
        for c_idx in range(k):
            cluster_indices = [i for i, lbl in enumerate(labels) if lbl == c_idx]
            if not cluster_indices:
                continue
            center = centers[c_idx]
            dists = [
                np.linalg.norm(vecs_norm[i] - center)
                for i in cluster_indices
            ]
            sorted_indices = [cluster_indices[j] for j in np.argsort(dists)]
            cluster_reps[c_idx] = sorted_indices[:2]
            for rep_idx in sorted_indices[:2]:
                results[rep_idx]['is_representative'] = True

        # ── 클러스터 정렬: 질문(query) 임베딩과 각 클러스터 대표 기사 평균
        #    유사도(cosine) 기준 내림차순.
        q_vec = _embed_texts([query], embed_url, embed_model, embed_timeout)
        cluster_sim: dict[int, float] = {}
        if q_vec is not None and len(q_vec) > 0:
            from sklearn.preprocessing import normalize as _norm
            q_norm = _norm(q_vec)[0]
            for c_idx, rep_indices in cluster_reps.items():
                if not rep_indices:
                    cluster_sim[c_idx] = -1.0
                    continue
                rep_vecs = vecs_norm[rep_indices]
                # cosine 유사도 = 정규화된 벡터의 내적
                sims = rep_vecs @ q_norm
                cluster_sim[c_idx] = float(np.mean(sims))
        else:
            # 임베딩 실패 시 centroid-쿼리 유사도 대용 — 순서대로 0
            for c_idx in cluster_reps:
                cluster_sim[c_idx] = 0.0

        ranked = sorted(cluster_sim.items(), key=lambda x: x[1], reverse=True)
        rank_of: dict[int, int] = {c: r for r, (c, _) in enumerate(ranked)}
        for item in results:
            c = item.get('cluster', 0)
            item['cluster_rank'] = rank_of.get(c, 999)
            item['cluster_similarity'] = round(cluster_sim.get(c, 0.0), 4)

        log.info("뉴스 클러스터링 완료: %d건 → %d 클러스터 (정렬됨)", n, k)
    except ImportError:
        log.warning("scikit-learn 미설치 — 클러스터링 생략, 전체 표시")
        for i, item in enumerate(results):
            item['cluster'] = i // 3
            item['is_representative'] = (i % 3 < 2)
            item['cluster_rank'] = item['cluster']
            item['cluster_similarity'] = 0.0
    except Exception as exc:
        log.warning("클러스터링 오류: %s", exc)
        for item in results:
            item['cluster'] = 0
            item['is_representative'] = True
            item['cluster_rank'] = 0
            item['cluster_similarity'] = 0.0

    return results


def summarize_clusters_for_question(
    question: str, results: list[dict], llm, approximate: bool = False,
) -> str:
    """클러스터별 대표 기사들을 입력으로 받아, 질문에 답하는 통합 요약을 생성.

    approximate=True 면 관련성이 확인되지 않은 '참고용 근접 기사' 기반이므로,
    단정하지 말고 관련 정보 부족을 먼저 밝히도록 지시한다.
    """
    from langchain_core.prompts import PromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    # 클러스터 순위 → 대표 기사만 추려서 LLM에 전달
    rep_items = [it for it in results if it.get('is_representative')]
    if not rep_items:
        rep_items = results[:6]

    # cluster_rank 오름차순 정렬
    rep_items = sorted(rep_items, key=lambda x: x.get('cluster_rank', 999))

    lines = []
    for it in rep_items[:12]:   # 토큰 절약: 최대 12건
        lines.append(
            f"- (클러스터 {it.get('cluster_rank', 0) + 1}) "
            f"{it.get('title', '')}\n"
            f"  요약: {(it.get('summary') or '')[:300]}\n"
            f"  출처: {it.get('url', '')}"
        )
    articles_text = "\n".join(lines)

    caveat = ""
    if approximate:
        caveat = (
            "\n[중요] 아래 기사들은 질문과의 명확한 관련성이 확인되지 않은 "
            "'참고용 근접 기사'입니다. 단정적으로 답하지 말고, 질문에 직접 답할 만한 "
            "관련 정보가 부족하다는 점을 먼저 밝힌 뒤, 참고가 될 만한 내용만 신중히 전달하세요.\n"
        )

    template = """당신은 은행 리스크 관리 부서를 위한 뉴스 분석 어시스턴트입니다.
사용자의 질문에 대해 아래 뉴스 대표 기사들의 정보를 종합하여 답하세요.
{caveat}
[질문]
{question}

[참고 기사 (클러스터별 대표)]
{articles}

[작성 지침]
- 3~6문장으로 핵심만 요약.
- 가능하면 기사에 언급된 수치·기관·일자 등을 인용.
- 추측·일반론 금지. 기사에 없는 사실은 만들지 말 것.
- 마지막에 한 줄 비워두고, 참고한 기사 URL을 "참고:" 뒤에 쉼표로 나열.

[답변]:"""
    prompt = PromptTemplate.from_template(template)
    chain = prompt | llm | StrOutputParser()
    try:
        return chain.invoke(
            {"question": question, "articles": articles_text, "caveat": caveat}
        )
    except Exception as exc:
        log.warning("질문 통합 요약 실패: %s", exc)
        return f"(통합 요약 실패: {exc})"
