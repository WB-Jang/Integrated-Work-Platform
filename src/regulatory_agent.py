"""
금융감독원(FSS), 한국은행(BOK), 금융위원회(FSC) 규제 동향 수집 및 LLM 요약 에이전트.

데이터 소스:
- FSS: 금융감독원 Open API (API 키 필요; www.fss.or.kr — 구 open.fss.or.kr 서비스 종료)
- BOK/FSC: 연합뉴스 경제 RSS → 기관별 키워드 필터링
  (BOK·FSC 공식 RSS는 현재 서비스 중단 상태)
"""
import datetime
import re
import math

import feedparser
import requests
import numpy as np

from logger import get_logger

log = get_logger("regulatory")

# ── 데이터 소스 URL 상수 ──────────────────────────────────────────────────────
# 구 open.fss.or.kr 서비스 종료 → www.fss.or.kr 로 이전, 파라미터명 auth→authKey
FSS_API_URL     = "http://www.fss.or.kr/fss/kr/openApi/api/fcnInfo.jsp"
YONHAP_ECON_RSS   = "https://www.yna.co.kr/rss/economy.xml"
YONHAP_MARKET_RSS = "https://www.yna.co.kr/rss/market.xml"

# 기관 대시보드(BOK/FSC/FSS) 정규식 필터용 — 좁은 피드(경제+시장)만 사용.
YONHAP_AGENCY_FEEDS = (YONHAP_ECON_RSS, YONHAP_MARKET_RSS)
# 자연어 직접 검색용 — 정책/산업/일반 카테고리를 추가해 후보 풀(=recall) 확대.
# (각 피드 약 120건 → 중복 제거 후 수백 건. 정밀도는 의미 재정렬+임계값이 담당.)
YONHAP_SEARCH_FEEDS = (
    YONHAP_ECON_RSS,
    YONHAP_MARKET_RSS,
    "https://www.yna.co.kr/rss/politics.xml",
    "https://www.yna.co.kr/rss/industry.xml",
    "https://www.yna.co.kr/rss/news.xml",
)

# 기관별 키워드 (정규식): 연합뉴스 기사에서 해당 기관 관련 기사만 추출
# BOK: 한국은행 공식명 + 주요 업무 키워드 (기준금리·금통위는 BOK 전용 용어)
_BOK_RE  = re.compile(r"한국은행|금통위|기준금리|한은(?!행)")   # "신한은행" 제외
_FSC_RE  = re.compile(r"금융위원회|금융위(?!원)")
_FSS_RE  = re.compile(r"금융감독원|금감원")

_REQUESTS_HEADERS = {"User-Agent": "Mozilla/5.0"}


# ── 연합뉴스 RSS 단일 fetch (BOK/FSC/FSS 공통) ──────────────────────────────

def _parse_entry_date(entry) -> datetime.date | None:
    """feedparser 항목의 published_parsed를 datetime.date로 변환."""
    t = entry.get("published_parsed")
    if t:
        try:
            return datetime.date(t.tm_year, t.tm_mon, t.tm_mday)
        except Exception:
            pass
    return None


def _fetch_yonhap_entries(feeds: "tuple[str, ...] | list[str] | None" = None) -> list[dict]:
    """연합뉴스 RSS(여러 카테고리)를 합쳐서 반환. 중복 URL 제거.

    feeds 미지정 시 기관 대시보드용 좁은 피드(경제+시장)를 사용한다.
    자연어 직접 검색은 YONHAP_SEARCH_FEEDS(정책·산업·일반 포함)를 명시 전달한다.
    """
    if feeds is None:
        feeds = YONHAP_AGENCY_FEEDS
    entries: dict[str, dict] = {}
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            count = len(feed.entries)
            log.info("연합뉴스 RSS 수신: %d건 (%s)", count, url)
            if count == 0:
                log.warning("연합뉴스 RSS 항목 없음 (bozo=%s): %s", getattr(feed, 'bozo', '?'), url)
            for e in feed.entries:
                link = e.get("link", "")
                if link and link not in entries:
                    entries[link] = {
                        "title": e.get("title", "").strip(),
                        "url": link,
                        "summary": e.get("summary", "").strip(),
                        "published_date": _parse_entry_date(e),
                    }
        except Exception as exc:
            log.warning("연합뉴스 RSS 파싱 오류 (%s): %s", url, exc)
    log.info("연합뉴스 전체 항목: %d건 (중복 제거 후)", len(entries))
    return list(entries.values())


def _filter_yonhap(entries: list[dict], pattern: re.Pattern, source: str, count: int) -> list[dict]:
    """연합뉴스 전체 항목 중 pattern에 매칭되는 항목만 source 라벨로 반환."""
    results = []
    for e in entries:
        text = e["title"] + " " + e["summary"]
        if pattern.search(text):
            results.append({"source": source, "title": e["title"], "url": e["url"]})
            if len(results) >= count:
                break
    return results


# ── 기관별 수집 함수 ─────────────────────────────────────────────────────────

def get_fss_updates(api_key: str, count: int = 3, yonhap_entries: list | None = None) -> list[dict]:
    """
    금융감독원 Open API → [{source, title, url}, ...].
    API 키가 없으면 연합뉴스 RSS에서 '금감원/금융감독원' 언급 기사로 대체.

    www.fss.or.kr fcnInfo API: authKey 파라미터, startDate/endDate(YYYYMMDD) 필요.
    응답 필드: subject(제목), originUrl(URL), regDate(날짜), publishOrg(발행기관).
    """
    if api_key:
        try:
            today = datetime.date.today().strftime("%Y%m%d")
            start = (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
            resp = requests.get(
                FSS_API_URL,
                params={
                    "authKey": api_key,
                    "pageCount": max(count, 5),  # API 최소 응답 보장
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
            log.warning("FSS API 결과 0건 (연합뉴스로 대체)")
        except Exception as exc:
            log.warning("FSS API 호출 실패 (연합뉴스로 대체): %s", exc)

    # API 키 없거나 호출 실패 → 연합뉴스 필터링
    entries = yonhap_entries if yonhap_entries is not None else _fetch_yonhap_entries()
    results = _filter_yonhap(entries, _FSS_RE, "금융감독원", count)
    log.info("FSS 연합뉴스 대체 수집: %d건", len(results))
    return results


def get_bok_updates(count: int = 3, yonhap_entries: list | None = None) -> list[dict]:
    """한국은행 관련 연합뉴스 기사 → [{source, title, url}, ...]"""
    entries = yonhap_entries if yonhap_entries is not None else _fetch_yonhap_entries()
    results = _filter_yonhap(entries, _BOK_RE, "한국은행", count)
    log.info("BOK 수집 완료: %d건", len(results))
    return results


def get_fsc_updates(count: int = 3, yonhap_entries: list | None = None) -> list[dict]:
    """금융위원회 관련 연합뉴스 기사 → [{source, title, url}, ...]"""
    entries = yonhap_entries if yonhap_entries is not None else _fetch_yonhap_entries()
    results = _filter_yonhap(entries, _FSC_RE, "금융위원회", count)
    log.info("FSC 수집 완료: %d건", len(results))
    return results


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
) -> list[dict]:
    """
    세 기관 데이터 수집 후 각 항목을 LLM으로 요약.

    연합뉴스 RSS를 한 번만 fetch해서 BOK·FSC·FSS(API 키 없을 때)에 공유.

    Returns:
        list of dict: source, title, url, summary
    """
    # 연합뉴스 RSS 공통 fetch
    yonhap = _fetch_yonhap_entries()

    all_items = (
        get_fss_updates(fss_api_key, count_per_source, yonhap)
        + get_bok_updates(count_per_source, yonhap)
        + get_fsc_updates(count_per_source, yonhap)
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


# ── 연합뉴스 직접 키워드 검색 ────────────────────────────────────────────────

def search_yonhap_by_keyword(
    keyword: str,
    date_from: str | None = None,
    date_to: str | None = None,
    count: int = 10,
) -> list[dict]:
    """
    연합뉴스 RSS에서 키워드/문장으로 직접 검색.

    Args:
        keyword: 검색 키워드 또는 문장 (제목+요약에서 단어 매칭)
        date_from: 시작일 "YYYY-MM-DD" (없으면 제한 없음)
        date_to: 종료일 "YYYY-MM-DD" (없으면 제한 없음)
        count: 최대 반환 건수

    Returns:
        list of dict: source, title, url, summary, published_date
    """
    try:
        from_dt = datetime.date.fromisoformat(date_from) if date_from else None
        to_dt = datetime.date.fromisoformat(date_to) if date_to else None
    except ValueError:
        from_dt = to_dt = None

    entries = _fetch_yonhap_entries()
    keywords = keyword.lower().split()
    results = []

    for e in entries:
        # 날짜 필터
        pub = e.get("published_date")
        if from_dt and pub and pub < from_dt:
            continue
        if to_dt and pub and pub > to_dt:
            continue

        # 키워드 매칭 (하나라도 포함되면 채택)
        text = (e["title"] + " " + e["summary"]).lower()
        if any(kw in text for kw in keywords):
            results.append({
                "source": "연합뉴스",
                "title": e["title"],
                "url": e["url"],
                "summary": e.get("summary", ""),
                "published_date": str(pub) if pub else "",
            })
            if len(results) >= count:
                break

    log.info("연합뉴스 키워드 검색 완료 (%r): %d건", keyword, len(results))
    return results


def extract_question_keywords(question: str, llm, max_n: int = 5) -> list[str]:
    """질문에서 연합뉴스 RSS 검색에 쓸 핵심 키워드를 최대 max_n개 추출."""
    from langchain_core.prompts import PromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    template = """[Context]
당신은 금융 규제·리스크 뉴스 검색 시스템의 키워드 생성기입니다.
검색 대상: 연합뉴스 RSS 헤드라인 (금융·경제·규제 섹션)
사용 목적: 생성된 키워드로 연합뉴스에서 관련 기사를 검색합니다.

[Objective]
아래 질문의 답을 찾기 위한 핵심 검색 키워드를 {max_n}개 이하로 추출하세요.

[Rules]
- 한 키워드는 1~3 단어의 짧은 명사구.
- 일반적/모호한 단어(예: '한국','경제','뉴스','전망')는 제외.
- 고유명사(기관·인물·정책명)와 핵심 사건/지표를 우선.
- 결과는 쉼표(,)로만 구분하여 한 줄로 출력. 다른 설명·번호·따옴표 금지.

[Response]
쉼표 구분 키워드 한 줄만 출력. 다른 텍스트 없이.

[질문]
{question}

[키워드]:"""
    prompt = PromptTemplate.from_template(template)
    chain = prompt | llm | StrOutputParser()
    try:
        raw = chain.invoke({"question": question, "max_n": max_n})
    except Exception as exc:
        log.warning("키워드 추출 실패: %s", exc)
        return [question.strip()] if question.strip() else []

    tokens = re.split(r"[,\n;·•\|]+", raw)
    keywords: list[str] = []
    for t in tokens:
        kw = t.strip().strip("\"'`[](){}<>")
        kw = re.sub(r"^\d+[\.\)]\s*", "", kw)
        if not kw or len(kw) > 30:
            continue
        if kw in keywords:
            continue
        keywords.append(kw)
        if len(keywords) >= max_n:
            break

    if not keywords:
        keywords = [question.strip()]
    log.info("질문 키워드 추출: %r → %s", question[:40], keywords)
    return keywords


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
검색 대상: 연합뉴스 RSS 헤드라인 (금융·경제·규제 섹션)
사용 목적: 같은 개념을 다양하게 표현하여 검색 recall을 높입니다.

[Objective]
아래 질문의 답을 찾기 위해 연합뉴스 기사 제목에서 검색할 표현을 {max_n}개 생성하세요.

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


def _tokenize_queries(keywords: list[str]) -> "tuple[list[str], list[str]]":
    """검색표현 리스트를 (구절, 단어) 두 목록으로 정규화한다.

    - 구절: 공백을 포함한 원본 표현(연속일치 보너스 판정용).
    - 단어: 각 표현을 어절 단위로 분해(부분일치 점수용). 1글자 토큰은 노이즈라 제외.
    한국어 조사는 substring 매칭으로 자연 흡수된다(예: '기준금리' in '기준금리를' = True).
    """
    phrases: list[str] = []
    words: list[str] = []
    for kw in keywords:
        if not kw or not kw.strip():
            continue
        p = kw.lower().strip()
        if p not in phrases:
            phrases.append(p)
        for w in p.split():
            if len(w) >= 2 and w not in words:
                words.append(w)
    return phrases, words


def search_yonhap_by_keywords(
    keywords: list[str],
    date_from: str | None = None,
    date_to: str | None = None,
    count: int = 10,
) -> list[dict]:
    """검색표현(구절) 리스트로 연합뉴스 후보 기사를 생성한다 (하이브리드 렉시컬 스코어링).

    기존 방식은 '기준금리 인하' 같은 다단어 구절을 통째로 연속일치(`kw in text`)시키려
    해서 실제 헤드라인과 거의 맞지 않아 0건이 되었다. 이를 어절 단위 부분일치로 바꾼다.
    - 단어 부분일치: 매칭 단어 1개당 +1
    - 구절 전체가 연속일치하면 추가 보너스: +2
    매칭 0인 기사도 버리지 않고(의미 재정렬 단계에서 회수될 수 있음) 후보로 유지하되,
    렉시컬 점수 ↓ → 날짜 최신순으로 정렬해 상위 count건을 반환한다. 정밀도(관련성 판정)는
    호출부의 BGE-M3 의미 재정렬 + 유사도 임계값이 담당한다.
    """
    try:
        from_dt = datetime.date.fromisoformat(date_from) if date_from else None
        to_dt = datetime.date.fromisoformat(date_to) if date_to else None
    except ValueError:
        from_dt = to_dt = None

    phrases, words = _tokenize_queries(keywords)
    if not phrases:
        return []

    entries = _fetch_yonhap_entries(YONHAP_SEARCH_FEEDS)
    scored: list[tuple[float, datetime.date, dict]] = []

    for e in entries:
        pub = e.get("published_date")
        if from_dt and pub and pub < from_dt:
            continue
        if to_dt and pub and pub > to_dt:
            continue
        text = (e["title"] + " " + e["summary"]).lower()
        matched_words = [w for w in words if w in text]
        matched_phrases = [p for p in phrases if " " in p and p in text]
        score = float(len(matched_words)) + 2.0 * len(matched_phrases)
        item = {
            "source": "연합뉴스",
            "title": e["title"],
            "url": e["url"],
            "summary": e.get("summary", ""),
            "published_date": str(pub) if pub else "",
            "matched_keywords": matched_words,
            "match_count": len(matched_words),
            "lexical_score": score,
        }
        scored.append((score, pub or datetime.date.min, item))

    # 렉시컬 점수 ↓, 날짜 ↓ 정렬 (0점 기사도 후보 유지 → 의미 재정렬이 정밀도 담당)
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    results = [item for _, _, item in scored[:count]]

    n_hit = sum(1 for s, _, _ in scored if s > 0)
    log.info(
        "연합뉴스 후보 생성: 표현 %d개(단어 %d) → 후보 %d건 반환 "
        "(렉시컬 매칭 %d건 / 전체 후보 %d건)",
        len(phrases), len(words), len(results), n_hit, len(scored),
    )
    return results


def fetch_and_summarize_yonhap(
    keyword: str,
    date_from: str | None,
    date_to: str | None,
    llm,
    count: int = 10,
) -> list[dict]:
    """
    연합뉴스 키워드 검색 후 LLM으로 요약.

    Returns:
        list of dict: source, title, url, summary (LLM 요약)
    """
    items = search_yonhap_by_keyword(keyword, date_from, date_to, count)
    if not items:
        log.warning("연합뉴스 키워드 검색 결과 없음: %r", keyword)
        return []

    results: list[dict] = []
    for item in items:
        try:
            summary = summarize_update(item["source"], item["title"], item["url"], llm)
        except Exception as exc:
            log.warning("LLM 요약 실패 (%s): %s", item["title"][:40], exc)
            summary = f"(요약 실패: {exc})\n출처: {item['url']}"
        results.append({**item, "summary": summary})

    log.info("연합뉴스 검색·요약 완료: 총 %d건", len(results))
    return results


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


# ── 연합뉴스 임베딩 + 클러스터링 ─────────────────────────────────────────────

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


def cluster_yonhap_results(
    results: list[dict],
    query: str,
    embed_url: str,
    embed_model: str = "bge-m3",
    embed_timeout: int = 45,
) -> list[dict]:
    """
    연합뉴스 검색 결과를 임베딩 후 KMeans 클러스터링하여 클러스터별 대표 기사 2개를 반환합니다.

    Args:
        results: fetch_and_summarize_yonhap의 출력 (source, title, url, summary, ...)
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

        log.info("연합뉴스 클러스터링 완료: %d건 → %d 클러스터 (정렬됨)", n, k)
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
사용자의 질문에 대해 아래 연합뉴스 대표 기사들의 정보를 종합하여 답하세요.
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
