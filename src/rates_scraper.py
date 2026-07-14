"""
금리 정보 스크래퍼 — 금융투자협회 채권정보센터(kofiabond.or.kr).

수집 항목:
  1) CD 91일 금리        : 홈 > 채권금리 > 채권금리 (오늘 날짜)
  2) 채권시가평가수익률  : 시가평가 > 채권시가평가수익률
                           5개 평가사 × 국고채권 1/2/3/5년

저장:
  - 우선 루트 레벨 JSON 파일(interest_rates.json)로 저장한다.
  - 추후 MongoDB 등 DB 연동 시 load_rates/save_rates 만 교체하면 된다.

갱신:
  - 데이터는 하루 1회 갱신(영업일 장 마감 후 채권평가사 수익률 고시).
  - is_stale() 로 '오늘자 데이터 보유 여부'를 판단하고, 패널 열람 시 자동 조회 +
    수동 '갱신' 버튼으로 재조회한다.

저장 스키마(interest_rates.json):
{
  "fetched_at": "2026-07-14T18:30:00+09:00",   # 마지막 조회 시각(KST, ISO8601)
  "date":       "2026-07-14",                   # 데이터 기준일(YYYY-MM-DD)
  "cd_91": {
      "rate": 3.45,                              # CD 91일 금리(%)
      "date": "2026-07-14"                       # CD 금리 기준일
  },
  "market_valuation": {
      "date": "2026-07-14",                      # 시가평가 기준일
      "companies": ["KIS채권평가", "한국자산평가", ...],   # 평가사 컬럼 순서
      "bonds": {                                 # 채권종목 -> {평가사: 수익률(%)}
          "국고채권(1년)": {"KIS채권평가": 3.10, "한국자산평가": 3.11, ...},
          "국고채권(2년)": {...},
          "국고채권(3년)": {...},
          "국고채권(5년)": {...}
      }
  }
}
"""
import os
import re
import json
import datetime
import threading
import xml.etree.ElementTree as ET

import requests

from logger import get_logger

log = get_logger("rates_scraper")

# ── 저장 경로(루트 레벨 JSON) ────────────────────────────────────────────────
_DATA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'interest_rates.json'
)
_LOCK = threading.Lock()

# ── 수집 대상 채권 종목(시가평가) ────────────────────────────────────────────
# 실제 라벨은 사이트 응답을 기준으로 최종 확정. 화면 표시 순서를 정의한다.
BOND_LABELS = [
    "국고채권(1년)",
    "국고채권(2년)",
    "국고채권(3년)",
    "국고채권(5년)",
]

# ── kofiabond Proframe(WebSquare) XML 서비스 ─────────────────────────────────
# 데이터는 https://www.kofiabond.or.kr/proframeWeb/XMLSERVICES/ 로 raw-XML POST.
_BASE = "https://www.kofiabond.or.kr"
_ENDPOINT = f"{_BASE}/proframeWeb/XMLSERVICES/"
_PFM_APP = "BIS-KOFIABOND"

# 시가평가 selectDay 고정 파라미터(캡처 기준) — 국고채, 5개 평가사(A10002~A10006)
_VAL_REPORT_COMP_CD = "A20000"
_VAL_APPLY_GB_CD = "C00"
_VAL_COMPANY_CODES = ["A10002", "A10003", "A10004", "A10005", "A10006"]

# 평가사 코드 → 명칭 폴백(getHeadList 응답으로 우선 대체, 실패 시 사용)
_COMPANY_NAME_FALLBACK = {
    "A10002": "KIS채권평가",
    "A10003": "한국자산평가",
    "A10004": "NICE피앤아이",
    "A10005": "에프앤자산평가",
    "A10006": "이지스자산평가",
}

_REQUESTS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": _BASE,
    "Referer": f"{_BASE}/",
}

# KST(UTC+9) — 서버 타임존과 무관하게 기준일을 한국 시간으로 계산
_KST = datetime.timezone(datetime.timedelta(hours=9))


class RatesNotConfiguredError(RuntimeError):
    """실제 요청(엔드포인트/파라미터/파싱)이 아직 연결되지 않았을 때 발생."""


# ── 시간/기준일 유틸 ─────────────────────────────────────────────────────────
def _now_kst() -> datetime.datetime:
    return datetime.datetime.now(tz=_KST)


def today_str() -> str:
    """KST 기준 오늘 날짜(YYYY-MM-DD)."""
    return _now_kst().date().isoformat()


# ── JSON 저장/로드 (menu_state.py 관례 준수) ─────────────────────────────────
def load_rates() -> "dict | None":
    """저장된 금리 데이터를 반환. 없거나 손상 시 None."""
    with _LOCK:
        try:
            with open(_DATA_PATH, encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except Exception as exc:
            log.warning("interest_rates.json 로드 실패: %s", exc)
            return None


def save_rates(data: dict) -> None:
    """금리 데이터를 JSON으로 저장."""
    with _LOCK:
        try:
            with open(_DATA_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            log.error("interest_rates.json 저장 실패: %s", exc)
            raise


def is_stale(data: "dict | None") -> bool:
    """오늘자(KST) 데이터가 아니면 True(=갱신 필요)."""
    if not data:
        return True
    return data.get("date") != today_str()


# ── Proframe XML 전송/파싱 유틸 ──────────────────────────────────────────────
def _new_session() -> requests.Session:
    """세션 부트스트랩 — 메인 페이지를 먼저 열어 WMONID/JSESSIONID 쿠키 획득.

    캡처의 쿠키는 만료되므로 재사용하지 않고 매 조회마다 새 세션을 만든다.
    """
    s = requests.Session()
    s.headers.update(_REQUESTS_HEADERS)
    try:
        s.get(f"{_BASE}/websquare/websquare.html", timeout=10)
    except Exception as exc:
        # 쿠키 획득 실패해도 XMLSERVICES 는 세션 없이 응답하는 경우가 있어 진행
        log.debug("세션 부트스트랩 경고: %s", exc)
    return s


def _build_message(svc: str, fn: str, dto_xml: str) -> str:
    """Proframe 요청 XML(message) 조립."""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<message>\n'
        '  <proframeHeader>\n'
        f'    <pfmAppName>{_PFM_APP}</pfmAppName>\n'
        f'    <pfmSvcName>{svc}</pfmSvcName>\n'
        f'    <pfmFnName>{fn}</pfmFnName>\n'
        '  </proframeHeader>\n'
        '  <systemHeader></systemHeader>\n'
        f'{dto_xml}\n'
        '</message>\n'
    )


def _call(session: requests.Session, svc: str, fn: str, dto_xml: str) -> ET.Element:
    """XMLSERVICES 호출 후 응답을 파싱하여 root Element 반환."""
    body = _build_message(svc, fn, dto_xml).encode("utf-8")
    resp = session.post(_ENDPOINT, data=body, timeout=15)
    resp.raise_for_status()
    # ElementTree 는 XML 선언의 encoding 을 존중하므로 bytes 그대로 전달
    try:
        return ET.fromstring(resp.content)
    except ET.ParseError as exc:
        # euc-kr 등 선언과 실제 인코딩 불일치 시 폴백
        text = resp.content.decode("euc-kr", errors="replace")
        text = re.sub(r'encoding="[^"]*"', 'encoding="utf-8"', text, count=1)
        try:
            return ET.fromstring(text)
        except ET.ParseError:
            raise RuntimeError(f"응답 XML 파싱 실패: {exc}") from exc


def _rows(root: ET.Element, dto_suffix: str = "DTO") -> "list[dict]":
    """응답에서 반복되는 DTO 엘리먼트들을 {자식태그: 텍스트} dict 리스트로 추출.

    Proframe 응답은 <message>...<XxxDTO>...</XxxDTO>(반복) 형태가 일반적이며,
    <vector>/<data> 래퍼가 끼는 변형도 있어 태그 접미사로 유연하게 수집한다.
    """
    out = []
    for el in root.iter():
        tag = el.tag.split('}')[-1]  # 네임스페이스 제거
        if tag.endswith(dto_suffix) and len(list(el)) > 0:
            row = {}
            for child in el:
                ctag = child.tag.split('}')[-1]
                row[ctag] = (child.text or "").strip()
            if row:
                out.append(row)
    return out


def _to_float(v) -> "float | None":
    """'3.451', '3,451', '3.45%' 등 → float. 실패/공란 시 None."""
    if v is None:
        return None
    s = str(v).replace(",", "").replace("%", "").strip()
    if not s or s in ("-", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _pick(d: dict, candidates: "list[str]") -> "str | None":
    """dict 에서 후보 키(대소문자 무시) 중 첫 번째로 값이 있는 것을 반환."""
    lower = {k.lower(): v for k, v in d.items()}
    for c in candidates:
        v = lower.get(c.lower())
        if v not in (None, ""):
            return v
    return None


def _yyyymmdd(date_str: str) -> str:
    """'YYYY-MM-DD' → 'YYYYMMDD'."""
    return date_str.replace("-", "")


def _fmt_date(yyyymmdd: str) -> str:
    """'YYYYMMDD' → 'YYYY-MM-DD' (형식이 다르면 원본 반환)."""
    s = re.sub(r"\D", "", yyyymmdd or "")
    if len(s) == 8:
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return yyyymmdd


# ── 실제 사이트 요청부 (캡처 기반 구현) ──────────────────────────────────────
# 응답 XML 필드명은 사이트에서 실제 응답을 확인해 확정한다. 아래 파서는 흔한
# 필드명 후보를 시도하며, 모두 실패하면 발견된 태그를 오류로 노출해 진단을 돕는다.

# CD91 응답에서 수익률/종목명 후보 필드
_CD_RATE_FIELDS = ["askPrc", "rop", "prc", "yld", "yield", "rate", "aplPrc", "asaPrc", "val2"]
_CD_NAME_FIELDS = ["bondNm", "krbNm", "itmNm", "dspNm", "name", "gubun", "val1"]

# 시가평가 selectDay 응답에서 채권종목명/만기 후보 필드
_VAL_NAME_FIELDS = ["bondNm", "krbNm", "itmNm", "dspNm", "trmNm", "termNm", "srtNm", "name"]


def _latest_valuation_date(session: requests.Session) -> "str | None":
    """getExistMaxDate 로 시가평가 최신 기준일(YYYYMMDD) 조회."""
    try:
        root = _call(session, "BISBndSrtPrcSrchSO", "getExistMaxDate",
                     "<BISComDspDatDTO></BISComDspDatDTO>")
        rows = _rows(root)
        for r in rows:
            v = _pick(r, ["standardDt", "existMaxDate", "maxDt", "dt", "val1"])
            if v and re.sub(r"\D", "", v):
                return re.sub(r"\D", "", v)[:8]
    except Exception as exc:
        log.warning("getExistMaxDate 실패: %s", exc)
    return None


def _get_company_names(session: requests.Session, ymd: str) -> "dict[str, str]":
    """getHeadList 로 평가사 코드→명칭 매핑 조회(실패 시 폴백)."""
    names = dict(_COMPANY_NAME_FALLBACK)
    try:
        dto = (
            "<BISBndSrtPrcDayDTO>"
            f"<standardDt>{ymd}</standardDt>"
            f"<applyGbCd>{_VAL_APPLY_GB_CD}</applyGbCd>"
            "</BISBndSrtPrcDayDTO>"
        )
        root = _call(session, "BISBndSrtPrcSrchSO", "getHeadList", dto)
        rows = _rows(root)
        parsed = {}
        for r in rows:
            code = _pick(r, ["reportCompCd", "compCd", "cd", "code"])
            nm = _pick(r, ["reportCompNm", "compNm", "nm", "name", "dspNm"])
            if code and nm:
                parsed[code] = nm
        if parsed:
            names.update(parsed)
    except Exception as exc:
        log.warning("getHeadList 실패(폴백 사용): %s", exc)
    return names


def _fetch_cd91(session: requests.Session, ymd: str) -> dict:
    """CD 91일 금리 조회 → {'rate': float, 'date': 'YYYY-MM-DD'}."""
    dto = f"<BISComDspDatDTO><val1>{ymd}</val1></BISComDspDatDTO>"
    root = _call(session, "BISLastAskPrcROPSrchSO", "listDay", dto)
    rows = _rows(root)
    if not rows:
        raise RuntimeError("CD91 응답에 데이터 행이 없습니다.")

    # 종목명에 'CD'와 '91'이 포함된 행을 찾는다.
    for r in rows:
        name = _pick(r, _CD_NAME_FIELDS) or " ".join(r.values())
        if "CD" in name.upper() and "91" in name:
            rate = _to_float(_pick(r, _CD_RATE_FIELDS))
            if rate is not None:
                return {"rate": rate, "date": _fmt_date(ymd)}

    # 못 찾으면 진단용으로 발견된 필드 노출
    sample = rows[0] if rows else {}
    raise RuntimeError(
        "CD91(91일) 행을 응답에서 찾지 못했습니다. "
        f"응답 필드 예시: {list(sample.keys())}"
    )


def _fetch_valuation(session: requests.Session, ymd: str) -> dict:
    """채권시가평가수익률(국고채, 5개 평가사) 조회.

    반환: {'date','companies','bonds': {라벨: {평가사: 수익률}}}
    """
    company_names = _get_company_names(session, ymd)
    companies = [company_names.get(c, c) for c in _VAL_COMPANY_CODES]

    val_slots = "".join(
        f"<val{i+1}>{code}</val{i+1}>" for i, code in enumerate(_VAL_COMPANY_CODES)
    )
    dto = (
        "<BISBndSrtPrcDayDTO>"
        f"<standardDt>{ymd}</standardDt>"
        f"<reportCompCd>{_VAL_REPORT_COMP_CD}</reportCompCd>"
        f"<applyGbCd>{_VAL_APPLY_GB_CD}</applyGbCd>"
        f"{val_slots}"
        "</BISBndSrtPrcDayDTO>"
    )
    root = _call(session, "BISBndSrtPrcSrchSO", "selectDay", dto)
    rows = _rows(root)
    if not rows:
        raise RuntimeError("시가평가 응답에 데이터 행이 없습니다.")

    # 각 행: 채권종목명 + val1..val5(5개 평가사 수익률)
    bonds: "dict[str, dict]" = {}
    for r in rows:
        label = _pick(r, _VAL_NAME_FIELDS)
        if not label:
            continue
        per_company = {}
        for i, comp_nm in enumerate(companies):
            per_company[comp_nm] = _to_float(r.get(f"val{i+1}"))
        # 값이 하나라도 있는 행만 채택
        if any(v is not None for v in per_company.values()):
            bonds[label] = per_company

    if not bonds:
        sample = rows[0] if rows else {}
        raise RuntimeError(
            "시가평가 수익률을 응답에서 추출하지 못했습니다. "
            f"응답 필드 예시: {list(sample.keys())}"
        )

    return {"date": _fmt_date(ymd), "companies": companies, "bonds": bonds}


# ── 조회 오케스트레이션 ──────────────────────────────────────────────────────
def fetch_rates() -> dict:
    """사이트에서 CD91 + 시가평가수익률을 조회해 저장 스키마 dict 로 반환.

    두 항목은 독립적으로 조회하며, 한쪽이 실패해도 나머지는 채운다.
    (부분 성공 시 실패 사유는 로그로 남기고 해당 항목은 None.)
    실패 항목이 있으면 예외 대신 부분 데이터를 반환하되, 둘 다 실패하면 예외.
    """
    errors = []
    session = _new_session()

    # 시가평가 기준일: getExistMaxDate 우선, 실패 시 오늘(KST)
    val_ymd = _latest_valuation_date(session) or _yyyymmdd(today_str())

    cd_91 = None
    try:
        cd_91 = _fetch_cd91(session, val_ymd)
    except Exception as exc:
        log.warning("CD91 조회 실패: %s", exc)
        errors.append(("cd_91", exc))

    market_valuation = None
    try:
        market_valuation = _fetch_valuation(session, val_ymd)
    except Exception as exc:
        log.warning("시가평가수익률 조회 실패: %s", exc)
        errors.append(("market_valuation", exc))

    if cd_91 is None and market_valuation is None:
        # 둘 다 실패 — 첫 오류를 대표로 전달
        raise errors[0][1]

    # 기준일: 시가평가 기준일 우선, 없으면 CD 기준일, 그것도 없으면 조회 기준일
    base_date = None
    if market_valuation:
        base_date = market_valuation.get("date")
    if not base_date and cd_91:
        base_date = cd_91.get("date")
    if not base_date:
        base_date = _fmt_date(val_ymd)

    return {
        "fetched_at": _now_kst().isoformat(timespec="seconds"),
        "date": base_date,
        "cd_91": cd_91,
        "market_valuation": market_valuation,
    }


def get_rates(force_refresh: bool = False) -> dict:
    """캐시(오늘자)면 그대로, 아니면 조회 후 저장하여 반환.

    - force_refresh=True: 캐시 무시하고 무조건 재조회.
    - 조회 실패 시: 예외를 그대로 전파(호출부에서 notify 처리).
      단, 조회는 실패했지만 이전 캐시가 있으면 호출부가 이를 활용할 수 있도록
      예외에 담지 않고 여기서는 순수 조회 결과만 다룬다.
    """
    if not force_refresh:
        cached = load_rates()
        if cached and not is_stale(cached):
            return cached

    data = fetch_rates()
    save_rates(data)
    return data
