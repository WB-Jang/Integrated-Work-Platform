# 메일 분석 — 사용자 PC Outlook 연동 (로컬 브릿지)

## 배경 / 결정
- IWP는 **중앙 서버에서 실행**되고 사용자는 **브라우저로 접속**(사용자 확인).
- 서버 파이썬(win32com)은 **원격 사용자 PC의 Outlook에 접근 불가**(OS/COM 경계).
- IWP 접속은 **`http://`**(사내망) → mixed-content 문제 없음. 사용자 PC엔 **Python 미설치** → 브릿지는 **단일 `.exe`(PyInstaller)** 로 배포.

## 구조
```
[사용자 PC] 브라우저 ──fetch(127.0.0.1)──▶ outlook_bridge.exe ──COM──▶ 본인 Outlook
[서버]      IWP ◀── 메일 JSON ── 브라우저 ,   IWP ── LLM 분석 ──▶ 브라우저 표시
```
브라우저가 사용자 PC에서 돌기 때문에 `127.0.0.1` = 그 사용자의 PC → 본인 Outlook.

## 구현
- **`bridge/outlook_bridge.py`** (신규, 사용자 PC 실행): stdlib `http.server` 기반 localhost 서버.
  - `GET /health` → 연결·기본 메일함(SMTP) 확인
  - `GET /emails?start&end&sender&recipient&attachments` → `outlook_agent.get_emails` 재사용
  - `POST /reply-draft` → 본인 Outlook에 회신 초안 창 열기(자동 발송 안 함)
  - CORS(+PNA `Access-Control-Allow-Private-Network`) 처리, 선택적 토큰 인증, `127.0.0.1` 바인딩
- **`bridge/build_bridge.bat`**: PyInstaller 단일 exe 빌드(관리자 1회). `bridge/run_bridge.bat`: 소스 실행(개발).
- **`bridge/README.md`**: 배포·실행·빌드·설정·문제해결.
- **`src/outlook_panel.py`** (서버측): 조회를 서버 Outlook(`io_bound(get_emails)`) 대신
  **브라우저→브릿지**(`ui.run_javascript`로 `fetch`)로 전환. 브릿지 연결 상태 배지, 로드시 헬스체크,
  "Outlook에 초안 열기" 버튼(브릿지 POST). 분석/초안 생성 LLM은 서버 유지.
  서버 플랫폼 게이팅 제거(조회는 클라이언트 브릿지에 의존).

## 설정 (IWP config.json, 선택)
```json
{ "outlook_bridge_url": "http://127.0.0.1:8899", "outlook_bridge_token": "" }
```
브릿지 환경변수: `IWP_BRIDGE_PORT`, `IWP_BRIDGE_TOKEN`, `IWP_BRIDGE_ORIGIN`.

## 검증 (Windows 필요 — 이 샌드박스는 Outlook/win32com/빌드 불가)
1. 빌드 PC에서 `bridge\build_bridge.bat` → `outlook_bridge.exe`.
2. 사용자 PC에서 Outlook 로그인 후 exe 실행 → 콘솔 "연결된 메일함: 본인@..." 확인.
3. 브라우저 IWP → 메일 분석 → "브릿지 연결됨" 배지 → 조회/분석/회신 초안 동작 확인.
4. 미실행 시 "브릿지 미연결" 안내 + 조회 시 오류 처리 확인.

## 보안
- 브릿지는 `127.0.0.1` 에만 바인딩(외부 비노출). 토큰으로 로컬 무단호출 차단 가능.
- 메일 원문은 브라우저→서버로만 전달(서버가 원격 Outlook에 직접 붙지 않음).
