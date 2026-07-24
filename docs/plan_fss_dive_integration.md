# Risk Dashboard — FSS/DIVE 실데이터 직접 연동 계획

## 배경 / 현재 상태

| 화면 | 파일 | 현재 데이터 소스 | 목표 |
|---|---|---|---|
| **Risk Indicator Dashboard** | `src/risk_indicator_panel.py` | **mock 난수** (`_mock_bank_indicators`) — `_fetch_from_fss`는 항상 `None` 반환하는 placeholder | DIVE의 실제 백엔드인 **FISIS OpenAPI**에서 은행별 BIS/NPL/ROA 등 실측치 조회 |
| **Risk DashBoard** | `src/fss_dashboard_panel.py` | **네이버 뉴스 검색 API** (감독원 관련 기사) | **금융감독원 보도·알림**(`fss.or.kr/.../sub6.do?menuNo=200747`)에서 직접 수집 |

## 핵심 발견 (조사 결과)

- **DIVE(diva.fss.or.kr)** = FISIS(금융통계정보시스템)의 시각화 프론트엔드. 원천 데이터는 전부 **FISIS OpenAPI**로 공개됨.
- **FISIS OpenAPI** 엔드포인트 (`http://fisis.fss.or.kr/openapi/`):
  - `statisticsInfoSearch.{json|xml}` — 실제 통계 수치. 파라미터:
    `lang`(kr), `auth`(인증키), `financeCd`(금융회사코드), `listNo`(통계표번호), `term`(Q/M/Y/H/A), `startBaseMm`/`endBaseMm`(YYYYMM)
  - `companySearch` — 금융회사 목록 → `financeCd` 획득
  - `statisticsListSearch` — 통계표(listNo) 목록
  - `accountListSearch` — 통계표 내 계정(account) 목록 → 특정 지표의 계정코드 획득
  - 예시:
    `http://fisis.fss.or.kr/openapi/statisticsInfoSearch.xml?lang=kr&auth={KEY}&financeCd=0010927&listNo=SA030&term=Q&startBaseMm=201812&endBaseMm=201906`
- **인증키**: FISIS 사이트에서 발급 → 기존 `FSS_API_KEY` 환경변수(HF Spaces Secrets)에 저장해 재사용.
- **감독원 페이지(menuNo=200747)** = 금융감독원 "보도·알림". 목록형 게시판(HTML), 별도 JSON API는 미확인 → HTML 스크래핑 또는 RSS 확인 필요.

## ⚠️ 환경 제약 (반드시 인지)

이 샌드박스의 아웃바운드 프록시가 `fss.or.kr` / `fisis.fss.or.kr` 접속을 **403으로 차단**한다(kofiabond와 동일). 따라서:
- **여기서는 라이브 응답을 못 받는다.** 실제 `financeCd`/`listNo`/`account` 코드 매핑과 응답 스키마 확정은 **사용자 로컬 또는 HF(FSS_API_KEY·아웃바운드 가능)에서 검증**해야 한다.
- 코드는 문서화된 API 계약에 맞춰 작성하고, **실패 시 기존 mock/네이버로 자동 폴백**하도록 유지한다(회귀 없음). 코드 매핑이 확정되면 상수 테이블만 교체.

---

## Part A. Risk Indicator Dashboard → FISIS OpenAPI

### A-1. 신규 모듈 `src/fisis_client.py`
FISIS OpenAPI 얇은 클라이언트. `requests` 사용, JSON 우선.
```python
BASE = "https://fisis.fss.or.kr/openapi"
def _get(service, **params) -> dict | None        # auth 자동주입, 실패 시 None
def company_search(...)                             # financeCd 조회
def statistics_list(...)                            # listNo 조회
def account_list(list_no)                           # 계정코드 조회
def statistics_info(finance_cd, list_no, term, start_mm, end_mm) -> list[dict]
```
- `auth = os.environ["FSS_API_KEY"]`
- 응답의 `result.err_cd`/`err_msg` 체크, `list` 배열 파싱.
- 모든 함수 네트워크·파싱 오류 시 `None`/`[]` 반환 (호출부에서 폴백).

### A-2. 코드 매핑 테이블 (확정 필요 — 초안은 표준 통계표 기준)
`risk_indicator_panel.py` 상단에 두 개의 매핑 상수 추가:
- `_BANK_FINANCE_CD`: 각 은행 `code` → FISIS `financeCd`
  (예: KB국민 `0010927` 형식 — companySearch로 전수 확정)
- `_INDICATOR_SOURCE`: 지표 `key` → `(listNo, accountCd, term)`
  (BIS/기본자본비율/NPL/ROA/ROE/LCR/예대율/총자산 각각의 통계표·계정코드)

> 이 두 테이블은 **API discovery 단계**(A-4)에서 companySearch·statisticsListSearch·accountListSearch를 돌려 확정한다. 확정 전까지 mock 유지.

### A-3. `_fetch_from_fss` 실제 구현
placeholder를 FISIS 호출로 교체:
```python
def _fetch_from_fss(api_key, bank_code) -> dict | None:
    fc = _BANK_FINANCE_CD.get(bank_code)
    if not (api_key and fc): return None
    latest, series, months = {}, {k: [] for k in ...}, _recent_months(12)
    for key, (list_no, acct, term) in _INDICATOR_SOURCE.items():
        rows = fisis_client.statistics_info(fc, list_no, term, start, end)
        # rows → {baseMm: value} 매핑 → series/latest 채움
    if 데이터 하나도 못 얻으면: return None   # → mock 폴백
    return {"latest": latest, "series": series, "months": months}
```
- 부분 성공(일부 지표만) 허용: 얻은 지표는 실데이터, 못 얻은 지표는 mock 보간 또는 "N/A".
- `build_...` 의 `has_real_data`/출처 배너가 자동으로 "FSS Open API 연동"으로 바뀜(기존 로직 재사용).

### A-4. Discovery 스크립트 (사용자 실행용)
`scripts/fisis_discover.py` — 사용자가 로컬/HF에서 1회 실행해 실제 코드표를 덤프:
- 은행명 → financeCd 목록 출력
- 후보 통계표(자본적정성/자산건전성/수익성 등) listNo + 계정 목록 출력
- 결과를 보고 A-2 매핑 상수를 확정 → 커밋.

### A-5. (대안) DIVE 화면 임베드 — 폴백 옵션
사용자가 "그냥 DIVE 화면 그대로도 OK"라 함. 단 외부 정부사이트는 **X-Frame-Options로 iframe 차단** 가능성이 높음. 따라서:
- 기본은 A-1~A-3의 **네이티브 지표 카드**(현재 UI 유지, 데이터만 실측).
- 추가로 탭/버튼 "DIVE 원본 열기"는 **새 창 링크**(`https://diva.fss.or.kr/`)로 제공(iframe 아님). iframe이 실제로 허용되면 임베드 탭도 추가 가능(검증 후 결정).

---

## Part B. Risk DashBoard 감독원 데이터 → FSS 보도·알림

### B-1. `fss_dashboard_panel.py` 데이터 소스 전환
`_fetch_all_categories`를 FSS 보도·알림(menuNo=200747) 수집으로 교체:
- 해당 게시판의 **목록 HTML을 파싱**(제목·날짜·상세링크) 또는 RSS가 있으면 RSS 사용.
- `requests` + 간단 정규식/`html.parser`로 `{title, url, regDate, content}` 리스트 생성.
- **네이버 뉴스는 폴백으로 유지** — FSS 접속 실패/파싱 실패 시 기존 네이버 경로로 자동 대체(회귀 없음).
- 카테고리 구조 유지(보도자료/사고/검사/경영공시) 또는 "감독원 보도·알림" 단일 피드로 단순화 — **확정 필요**(아래 질문).

### B-2. 링크 정규화
FSS 상세링크는 상대경로(`/fss/...`)일 수 있음 → 기존 `_normalize_url`을 확장해 `https://www.fss.or.kr` 베이스로 절대화.

---

## 수정/신규 파일 요약
- **신규** `src/fisis_client.py` — FISIS OpenAPI 클라이언트
- **신규** `scripts/fisis_discover.py` — 코드 매핑 확정용 1회성 스크립트
- **수정** `src/risk_indicator_panel.py` — `_fetch_from_fss` 실구현 + 매핑 상수 + (선택)DIVE 링크
- **수정** `src/fss_dashboard_panel.py` — 보도·알림 수집 + 네이버 폴백
- **문서** 이 계획 파일

## 대상 브랜치
Risk Dashboard는 두 라인 모두에 존재 → **`dev/reporting_system`에 먼저 반영 X**. 이 기능은 rates와 무관하고 두 라인 공통이므로:
- 우선 **`feature/interest-rates-local`** (현재 체크아웃 브랜치)에 구현·검증.
- 동일 변경을 **`feature/interest-rates`**(HF 라인)에도 cherry-pick 반영 (Risk Dashboard는 reporting 미포함 라인에도 존재).
- 두 파일(`risk_indicator_panel.py`, `fss_dashboard_panel.py`, 신규 client)은 rates 파일과 겹치지 않아 충돌 없음.

## 검증 (사용자 환경 필수)
1. `FSS_API_KEY`에 FISIS 인증키 설정 → `scripts/fisis_discover.py` 실행 → financeCd/listNo 확정.
2. Risk Indicator Dashboard 진입 → 지표 카드가 실측치로, 출처 배너 "FSS Open API 연동"으로 표시.
3. 키/네트워크 없을 때 → mock으로 폴백(회귀 없음) 확인.
4. Risk DashBoard → 감독원 보도·알림 실제 기사 목록 표시, 원문 링크 유효. 실패 시 네이버 폴백.

## Q4 확정 설계 — 은행별 주요 지표 FISIS 실데이터 (구현 완료·코드확정 대기)

사용자 결정: ① API 방식(인증키 보유), ② 지표세트 FINE 핵심경영지표 준거, ③ 분기 시계열 그래프,
④ 시점 선택값 = 카드 표시 / 기간(시작~종료) 선택 = 시계열 구간.

구현:
- **`src/fisis_client.py` (신규)** — FISIS OpenAPI(`fisis.fss.or.kr/openapi/*.json`) 클라이언트.
  서비스 `companySearch`/`statisticsListSearch`/`accountListSearch`/`statisticsInfoSearch`,
  파라미터 `lang·auth·financeCd·listNo·term·startBaseMm·endBaseMm`, 인증키=`FSS_API_KEY`.
  분기 유틸(`recent_quarters`=직전 완료분기 앵커, `quarter_label`), 방어적 파싱, `_dump_raw` 진단,
  고수준 `fetch_bank_indicators(bank, keys, start_mm, end_mm)` → {series, latest, months, base_months}.
  **서버사이드 호출** → 망분리 사용자도 조회 가능(Q5).
- **`src/risk_indicator_panel.py`** — "은행별 주요 지표" 탭 재구성:
  - INDICATORS를 FINE 준거 12종으로 교체(BIS·Tier1·CET1·NPL·연체율·ROA·ROE·NIM·원화예대율·LCR·총자산·당기순이익).
  - **조회 기간(시작~종료 분기) + 기준시점(분기) 선택 + [조회] 버튼**. 카드=기준시점 값(직전분기 대비 증감),
    시계열 차트=선택 기간 전체. `io_bound`로 비동기 조회, 결측(None) 안전 렌더.
  - FISIS 성공 시 실데이터, 실패/코드미확정 시 **샘플 자동 폴백**(출처 배지로 상태 표시).
- **`scripts/fisis_discover.py` (신규)** — 서버에서 1회 실행해 `financeCd`/`listNo`/`account_cd` 확정.

**남은 1단계(사용자 서버에서):** `FSS_API_KEY` 설정 후 `python scripts/fisis_discover.py` 실행 →
출력(은행 financeCd 목록 · 핵심경영지표 listNo · 계정코드 · 수치 응답 샘플)을 전달하면
`fisis_client.BANK_FINANCE_CD` / `INDICATOR_SOURCE` / `_row_*` 파서를 확정한다. (이 샌드박스는 fss.or.kr 차단)

## 확정된 결정 (사용자 선택)
1. **Risk Indicator 표시 방식** → **DIVE 화면 임베드 위주**. `diva.fss.or.kr` iframe을 기본 뷰로. X-Frame-Options 차단 대비 "새 창 열기" 버튼 상시 노출 + 기존 네이티브 지표 화면은 "참고 지표(샘플)" 보조 탭으로 유지(화면이 비지 않도록).
2. **감독원 피드 구조** → **보도·알림 단일 최신 피드**. FSS menuNo=200747에서 최신 게시물을 하나의 목록으로.
3. **네이버 뉴스** → **폴백으로 유지**. FSS 수집 실패 시 자동 대체.
