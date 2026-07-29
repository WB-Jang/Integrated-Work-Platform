# IWP Outlook 브릿지 (사용자 PC용)

IWP는 중앙 서버에서 실행되고 사용자는 브라우저로 접속합니다. 서버의 파이썬은 원격
사용자 PC의 Outlook에 접근할 수 없으므로, **사용자 PC에서 이 작은 브릿지를 실행**하면
브라우저가 `127.0.0.1`로 브릿지를 호출해 **본인 Outlook** 메일을 읽어옵니다.
LLM 분석은 IWP 서버가 수행합니다. (메일 원문은 브라우저→서버로만 전달됩니다.)

```
[사용자 PC] 브라우저 ──fetch──▶ 127.0.0.1:8899 (브릿지) ──COM──▶ 본인 Outlook
[서버]     IWP 서버 ◀─ 메일 JSON ─ 브라우저 ,   IWP 서버 ─ LLM 분석 ─▶ 브라우저 표시
```

## 요구 사항
- Windows + MS Outlook 데스크톱(로그인된 상태)
- 사용자 PC에는 Python 불필요 — **`outlook_bridge.exe`** 단일 파일만 실행

## 사용자 배포·실행
1. 관리자가 `outlook_bridge.exe`를 배포(빌드 방법은 아래).
2. 사용자는 Outlook을 켠 상태에서 `outlook_bridge.exe`를 실행(백그라운드 상주).
   - 실행 시 콘솔에 `연결된 메일함: 본인@은행.com` 이 표시되면 정상.
   - 시작프로그램에 등록하면 매번 실행할 필요가 없습니다.
3. 브라우저에서 IWP 접속 → 메일 분석 메뉴 → 상단 "브릿지 연결됨" 확인 후 사용.

## EXE 빌드 (관리자, 1회)
Python + pywin32 가 설치된 빌드용 Windows PC에서:
```
cd bridge
build_bridge.bat
```
→ `bridge\dist\outlook_bridge.exe` 생성. 이 파일을 사용자에게 배포합니다.

## 설정(선택)
환경변수로 조정할 수 있습니다.
| 변수 | 기본값 | 설명 |
|---|---|---|
| `IWP_BRIDGE_PORT` | `8899` | 브릿지 포트 |
| `IWP_BRIDGE_TOKEN` | (없음) | 설정 시 IWP `config.json`의 `outlook_bridge_token` 과 동일해야 호출 허용 |
| `IWP_BRIDGE_ORIGIN` | `*` | CORS 허용 오리진(특정 IWP 주소로 좁힐 수 있음) |

IWP 서버 `config.json`(선택):
```json
{
  "outlook_bridge_url": "http://127.0.0.1:8899",
  "outlook_bridge_token": ""
}
```

## 엔드포인트
- `GET /health` → `{"ok":true,"mailbox":"me@bank.com","version":"1.1","caps":["emails","open-email","reply-draft"]}`
- `GET /emails?start=YYYY-MM-DD&end=YYYY-MM-DD&sender=&recipient=&attachments=0|1`
- `GET /open-email?entry_id=&store_id=` → 본인 Outlook에서 해당 메일 창을 엽니다. **(v1.1에서 추가)**
- `POST /reply-draft` (JSON: `entry_id`,`store_id`,`body`,`reply_all`) → 본인 Outlook에 회신 초안 창을 엽니다(자동 발송 안 함).

> **버전 주의:** IWP 서버가 업데이트되어 새 엔드포인트가 추가되면, **`outlook_bridge.exe`도 다시 빌드해 재배포**해야 합니다.
> 구버전 exe는 새 엔드포인트를 모르므로 해당 호출이 `HTTP 404`로 실패합니다(예: v1.1 이전 exe에서 "메일 열기").
> 현재 실행 중인 브릿지 버전은 `GET /health` 의 `version`/`caps` 로 확인할 수 있습니다.

## 보안
- `127.0.0.1` 에만 바인딩되어 외부 네트워크에 노출되지 않습니다.
- 토큰을 설정하면 로컬의 다른 프로세스가 무단 호출하는 것을 막을 수 있습니다.
- IWP는 `http://` 사내망 접속이라 혼합 콘텐츠(mixed content) 문제가 없습니다.

## 문제 해결
- **"브릿지 미연결"**: `outlook_bridge.exe` 실행 여부 확인, Outlook 로그인 확인, 포트(8899) 충돌 확인.
- **메일함이 다른 사람 것으로 보임**: 해당 PC Outlook에 로그인된 계정이 본인인지 확인.
- **회신 초안이 안 열림**: Outlook 보안 정책(프로그래밍 방식 접근) 설정을 확인.
- **"메일 열기" 시 `HTTP 404`**: 실행 중인 exe가 `/open-email` 미지원 **구버전(v1.1 이전)** 입니다.
  최신 소스로 `build_bridge.bat`을 다시 실행해 exe를 재빌드·재배포하세요.
- **`build_bridge.bat` 실행 시 `'XE'…'tlook_bridge.exe' 은(는) … 아닙니다`류 오류**:
  배치 파일이 한글(UTF-8)로 저장돼 CP949 콘솔에서 깨진 경우입니다. 배치 파일은 **영문(ASCII)로만**
  유지하세요(현재 저장소의 `.bat`은 ASCII로 정리됨). 편집기에서 다시 저장할 때 한글을 넣지 마세요.
