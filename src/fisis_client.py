"""
FISIS(금융통계정보시스템) OpenAPI 클라이언트.

DIVE(diva.fss.or.kr) 및 파인 '은행 핵심경영지표'(fine.fss.or.kr/.../fisisBank.do)의
원천 데이터는 모두 FISIS OpenAPI로 공개된다. 이 모듈은 은행별 재무·건전성 지표를
분기(term=Q) 시계열로 조회한다.

공식 안내: https://fisis.fss.or.kr/openapi/
인증키: 환경변수 FSS_API_KEY (또는 build 시 config['fss_api_key']).

■ 서버사이드 수집 — 망분리 관점
  이 호출은 IWP 서버 프로세스가 수행한다. 서버 PC가 망분리 예외로 fss.or.kr 접근이
  가능하면, 사용자 PC가 망분리로 차단돼 있어도 사용자는 브라우저에서 데이터를 볼 수
  있다(서버가 받아 UI로 그려주므로). DIVE iframe(브라우저가 직접 접속)과의 결정적 차이.

■ 코드 매핑 확정
  은행→financeCd, 지표→(listNo, account_cd) 매핑은 환경마다 확정이 필요하다.
  scripts/fisis_discover.py 를 서버에서 1회 실행해 실제 코드를 덤프한 뒤
  fisis_codes.py(또는 아래 상수)를 채운다. 확정 전에는 각 함수가 빈 결과를 반환하고,
  패널은 샘플 데이터로 자동 폴백한다(회귀 없음).
"""
from __future__ import annotations

import os
import json
import datetime

import requests

from logger import get_logger

log = get_logger("fisis")

BASE = "https://fisis.fss.or.kr/openapi"
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_TIMEOUT = 15

# 진단용 — 마지막 원문 응답을 보관/덤프 (rates_scraper 패턴과 동일)
_LAST_RAW: dict = {}


def _auth_key() -> str:
    return (os.environ.get("FSS_API_KEY", "") or "").strip()


def has_api_key() -> bool:
    return bool(_auth_key())


def _dump_raw(service: str, payload) -> str:
    """마지막 응답을 repo 루트에 저장해 코드 확정·디버깅에 활용."""
    _LAST_RAW[service] = payload
    try:
        path = os.path.join(os.getcwd(), f"fisis_debug_{service}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return path
    except Exception:
        return ""


def _call(service: str, **params) -> dict | None:
    """FISIS OpenAPI 단일 호출. result dict 반환(오류/키부재 시 None)."""
    key = _auth_key()
    if not key:
        log.warning("FSS_API_KEY 미설정 — FISIS 호출 생략")
        return None
    q = {"lang": "kr", "auth": key}
    q.update({k: v for k, v in params.items() if v not in (None, "")})
    url = f"{BASE}/{service}.json"
    try:
        r = requests.get(url, params=q, headers=_HEADERS, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning("FISIS %s 호출 실패: %s", service, e)
        return None

    _dump_raw(service, data)
    # 응답 포맷: {"result": {"err_cd","err_msg","list":[...]}} 형태를 기본 가정하되,
    # 평평한 형태({"list":[...]})도 허용한다.
    res = data.get("result") if isinstance(data, dict) else None
    if res is None:
        res = data if isinstance(data, dict) else {"list": []}
    err = str(res.get("err_cd", "") or res.get("errCd", "")).strip()
    if err and err not in ("000", "0"):
        log.warning("FISIS %s 오류(%s): %s", service, err,
                    res.get("err_msg") or res.get("errMsg"))
        return None
    return res


def _list_of(res: dict | None) -> list[dict]:
    if not res:
        return []
    lst = res.get("list")
    if isinstance(lst, list):
        return [x for x in lst if isinstance(x, dict)]
    return []


# ─── 저수준 서비스 ────────────────────────────────────────────────────────────
def company_search(finance_group_no: str = "") -> list[dict]:
    """금융회사 목록 → financeCd 확정용. finance_group_no 예: 은행권 그룹코드."""
    return _list_of(_call("companySearch", financeGroupNo=finance_group_no))


def statistics_list(finance_cd: str = "") -> list[dict]:
    """통계표(listNo) 목록 → '핵심경영지표' 통계표 확정용."""
    return _list_of(_call("statisticsListSearch", financeCd=finance_cd))


def account_list(list_no: str) -> list[dict]:
    """통계표 내 계정(account) 목록 → 지표별 account_cd 확정용."""
    return _list_of(_call("accountListSearch", listNo=list_no))


def statistics_info(finance_cd: str, list_no: str, term: str,
                    start_mm: str, end_mm: str, account_cd: str = "") -> list[dict]:
    """실제 통계 수치. 각 row = (기준월 × 계정) 값."""
    return _list_of(_call(
        "statisticsInfoSearch",
        financeCd=finance_cd, listNo=list_no, term=term,
        startBaseMm=start_mm, endBaseMm=end_mm, account=account_cd,
    ))


# ─── 파싱 헬퍼 ────────────────────────────────────────────────────────────────
def _row_base_month(row: dict) -> str:
    for k in ("base_month", "baseMonth", "baseMm", "base_mm", "BASE_MONTH"):
        v = row.get(k)
        if v:
            return str(v)
    return ""


def _row_account_cd(row: dict) -> str:
    for k in ("account_cd", "accountCd", "ACCOUNT_CD", "account"):
        v = row.get(k)
        if v:
            return str(v)
    return ""


def _row_value(row: dict) -> float | None:
    """row의 수치 값을 추출. 명시 필드(a/value/amt) 우선, 없으면 첫 숫자형."""
    for k in ("a", "value", "amt", "val", "A", "VALUE"):
        if k in row:
            f = _to_float(row.get(k))
            if f is not None:
                return f
    # 폴백: 계정/월/이름 필드를 제외한 첫 숫자형 값
    skip = {"finance_cd", "financeCd", "finance_nm", "financeNm", "account_cd",
            "accountCd", "account_nm", "accountNm", "base_month", "baseMonth",
            "base_mm", "term"}
    for k, v in row.items():
        if k in skip:
            continue
        f = _to_float(v)
        if f is not None:
            return f
    return None


def _to_float(v) -> float | None:
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if not s or s in ("-", "N/A", "NA"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ─── 분기 유틸 ────────────────────────────────────────────────────────────────
_QUARTER_END_MM = {1: "03", 2: "06", 3: "09", 4: "12"}


def quarter_label(base_mm: str) -> str:
    """YYYYMM(분기말) → 'YYYY Q n'."""
    try:
        y, m = int(base_mm[:4]), int(base_mm[4:6])
        q = (m - 1) // 3 + 1
        return f"{y} Q{q}"
    except Exception:
        return base_mm


def recent_quarters(n: int = 8, ref: datetime.date | None = None) -> list[str]:
    """최근 n개 '완료된' 분기말 YYYYMM 리스트(오름차순).

    진행 중 분기는 데이터가 없으므로 직전 완료 분기를 최신으로 잡는다.
    예: 2026-07(3분기 진행 중) → 최신 = 2026 Q2(202606).
    """
    ref = ref or datetime.date.today()
    q = (ref.month - 1) // 3 + 1
    y = ref.year
    # 직전 완료 분기로 이동
    q -= 1
    if q == 0:
        q = 4
        y -= 1
    out: list[str] = []
    for _ in range(n):
        out.append(f"{y}{_QUARTER_END_MM[q]}")
        q -= 1
        if q == 0:
            q = 4
            y -= 1
    return list(reversed(out))


def quarter_options(years_back: int = 4, ref: datetime.date | None = None) -> list[str]:
    """선택 UI용 분기 목록(YYYYMM, 오름차순)."""
    return recent_quarters(years_back * 4, ref)


# ─── 코드 매핑 (환경별 확정 필요) ─────────────────────────────────────────────
# scripts/fisis_discover.py 를 서버에서 실행해 아래를 채운다.
#   BANK_FINANCE_CD: 은행 code → FISIS financeCd
#   INDICATOR_SOURCE: 지표 key → (listNo, account_cd)
# 비어 있는 동안 fetch_bank_indicators()는 None을 반환하고 패널은 샘플로 폴백한다.
BANK_FINANCE_CD: dict[str, str] = {
    # 예) "kb": "0010927", "shinhan": "0010297", ...
}

INDICATOR_SOURCE: dict[str, tuple[str, str]] = {
    # 예) "bis": ("SA030", "A"), "npl": ("SB040", "C"), ...
}


def codes_ready() -> bool:
    """실데이터 조회에 필요한 코드 매핑이 확정되었는지."""
    return bool(BANK_FINANCE_CD and INDICATOR_SOURCE)


def fetch_bank_indicators(bank_code: str, indicator_keys: list[str],
                          start_mm: str, end_mm: str, term: str = "Q") -> dict | None:
    """은행 하나의 지표 시계열을 FISIS에서 조회.

    Returns (성공 시):
        {
          "series": {ind_key: [분기별 값...]},   # base_months 순서
          "latest": {ind_key: 마지막 값},
          "months": ['2024 Q1', ...],            # 표시용 라벨
          "base_months": ['202403', ...],        # YYYYMM
        }
    키/코드/네트워크 미비 또는 데이터 없음 시 None (→ 패널이 샘플로 폴백).
    """
    fc = BANK_FINANCE_CD.get(bank_code)
    if not (has_api_key() and fc and INDICATOR_SOURCE):
        return None

    base_months: list[str] = []
    per_ind: dict[str, dict[str, float | None]] = {}

    for key in indicator_keys:
        src = INDICATOR_SOURCE.get(key)
        if not src:
            continue
        list_no, acct = src
        rows = statistics_info(fc, list_no, term, start_mm, end_mm, acct)
        by_month: dict[str, float | None] = {}
        for r in rows:
            if acct and _row_account_cd(r) not in ("", acct):
                continue
            mm = _row_base_month(r)
            if mm:
                by_month[mm] = _row_value(r)
        if by_month:
            per_ind[key] = by_month
            for mm in by_month:
                if mm not in base_months:
                    base_months.append(mm)

    if not per_ind:
        return None

    base_months.sort()
    series = {k: [v.get(mm) for mm in base_months] for k, v in per_ind.items()}
    latest = {k: (vals[-1] if vals else None) for k, vals in series.items()}
    return {
        "series": series,
        "latest": latest,
        "months": [quarter_label(mm) for mm in base_months],
        "base_months": base_months,
    }
