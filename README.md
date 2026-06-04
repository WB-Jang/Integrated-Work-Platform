---
title: Integrated Work Platform
emoji: 💼
colorFrom: gray
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
short_description: 통합 업무 플랫폼 (베타) — 문서 분석·요약·법률 검색·보고서 작성
---

# Integrated Work Platform (Beta on Hugging Face Spaces)

NiceGUI 기반 통합 업무 플랫폼의 베타 배포본입니다.

## 기능

- **문서 복합 분석** — DOCX/PDF/HWP 오타·논리·스타일 검사
- **문서 요약** — 계층적 Map-Reduce / 분량 축약
- **법률 검색** — BGE-M3 임베딩 + Reranker 기반 RAG
- **PDF 변환** — Word/PPT → PDF (LibreOffice headless)
- **보고서 작성** — AI 자동 보고서
- **메일 분석** — Outlook 연동 *(로컬 데스크톱 전용 — HF에서는 비활성화 안내만 표시)*
- **규제 동향** — 금감원·한은·금융위 보도자료 LLM 요약
- **DB 관리** — 법령 FAISS 벡터 DB 구축 *(관리자)*

## 운영 메모

### Secrets 설정

HF Spaces의 **Settings → Variables and secrets** 에서 다음을 등록하세요:

| 이름 | 필수 | 용도 |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | ✅ | 모든 LLM 호출 (committee/legal/summary 등). 없으면 LLM 기능 전체 동작 불가. |
| `NICEGUI_STORAGE_SECRET` | 권장 | 사용자 이니셜·세션을 브라우저에 영구 저장. 미설정 시 컨테이너 재시작마다 모든 사용자 이니셜 초기화. 임의의 64자 hex(`openssl rand -hex 32`)를 권장. |
| `FSS_API_KEY` | 선택 | 금감원 Open API 키 (규제동향 기능 사용 시). |

### 사용자 식별

- 최초 접속 시 모달에서 본인 이니셜(2~16자)을 입력합니다.
- 이후 모든 로그(`logs/*.log`)에 `[USER:XXX]` 토큰이 자동 첨부됩니다.
- 사이드바 하단 🚪 로그아웃 아이콘으로 이니셜을 재입력할 수 있습니다.

### 로그 회수 (재시작 시 휘발)

HF Spaces 무료 플랜은 영구 디스크가 없어 컨테이너 재시작 시 `logs/`가 모두 삭제됩니다.
회수 절차:

1. 사이드바 → **DB 관리** 메뉴 진입
2. 관리자 비밀번호 입력
3. **로그 다운로드 → `logs.zip` 다운로드** 버튼 클릭

운영 안정성을 위해 베타 기간 동안 **하루 1회 이상 회수**를 권장합니다.

### 임베딩 / 리랭크 서버

컨테이너 부팅 시 자동으로 함께 기동됩니다 (`entrypoint.sh`).

| 서비스 | 포트(내부) | 모델 |
| --- | --- | --- |
| 임베딩 서버 | 8081 | BAAI/bge-m3 |
| 리랭크 서버 | 8082 | BAAI/bge-reranker-v2-m3 |
| NiceGUI 앱 | 7860 (외부 노출) | — |

CPU-only 추론. GPU 사용을 원하면 Space hardware를 GPU 인스턴스로 업그레이드하면 자동으로 CUDA가 사용됩니다 (코드 변경 불필요).

### 관리자 비밀번호

`src/admin_panel.py:21` 의 `ADMIN_PASSWORD` 상수로 하드코딩되어 있습니다.
Public Space에서 공개 저장소를 통해 노출될 수 있으니 운영 전에 반드시 값을 변경하세요.

## 로컬 개발 (참고)

```bash
docker build -t iwp-hf .
docker run --rm -p 7860:7860 \
    -e OPENROUTER_API_KEY=sk-or-... \
    -e NICEGUI_STORAGE_SECRET=$(openssl rand -hex 32) \
    iwp-hf
# → http://localhost:7860
```

## 알려진 제약 (베타)

- **Outlook 메일 발송/조회** — Windows + MS Outlook 데스크톱 설치 환경에서만 동작. HF에서는 메뉴와 UI만 노출되며 액션은 안내 메시지로 대체됨.
- **MS Office COM 기반 PDF 변환** — Linux 컨테이너에서는 LibreOffice headless로 자동 폴백.
- **세션 데이터 휘발** — uploads/, report_outputs/, logs/ 모두 컨테이너 재시작 시 사라집니다.
