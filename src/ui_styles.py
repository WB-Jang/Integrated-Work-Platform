"""
Integrated Work Platform — Dark UX Design System (design/design-full-change)

NiceGUI 전용 글로벌 CSS 주입 모듈.
Claude Design "IWP-Redesign-B" 목업을 기준으로 한 다크 네이비 팔레트
(bg #050b14, sky-blue accent #0ea5e9) + Noto Sans KR/Space Grotesk +
상단 가로 탭바 레이아웃을 위한 클래스들을 정의합니다.

사용법:
    from ui_styles import inject_global_css
    inject_global_css()   # @ui.page 핸들러 안에서 호출
"""

import html as _html

from nicegui import ui


_GLOBAL_CSS = """
/* ─────────────────────────────────────────────────────────
   Quasar theme override — primary 컬러 자체를 모노크롬으로
   (CSS 변수를 바꾸면 bg-primary/text-primary 등 모든
    Quasar 유틸 클래스가 자동으로 검정으로 표시됨)
   ───────────────────────────────────────────────────────── */
:root,
html,
html body,
.q-app,
.q-page-container,
.body--light {
  --q-primary: #0ea5e9 !important;
  --q-secondary: #0369a1 !important;
  --q-accent: #0ea5e9 !important;
  --q-dark: #050b14 !important;
  --q-dark-page: #050b14 !important;
  --q-positive: #22c55e !important;
  --q-negative: #ef4444 !important;
  --q-info: #0ea5e9 !important;
  --q-warning: #f59e0b !important;
}

/* ─────────────────────────────────────────────────────────
   Design tokens (dark — IWP-Redesign-B)
   ───────────────────────────────────────────────────────── */
:root {
  --bg: #050b14;
  --bg-elev: #0b1524;
  --bg-sunken: #030710;
  --border: rgba(255,255,255,.07);
  --border-strong: rgba(255,255,255,.16);
  --text: #f1f5f9;
  --text-2: rgba(148,163,184,.9);
  --text-3: rgba(148,163,184,.6);
  --text-4: rgba(148,163,184,.35);
  --accent: #0ea5e9;
  --accent-hover: #38bdf8;
  --accent-2: #0369a1;
  --success: #22c55e;
  --warning: #f59e0b;
  --danger: #ef4444;
  --shadow-sm: 0 1px 2px rgba(0,0,0,.24);
  --shadow-md: 0 1px 3px rgba(0,0,0,.35), 0 1px 2px rgba(0,0,0,.28);
  --radius-sm: 6px;
  --radius: 8px;
  --radius-lg: 12px;
  --radius-full: 999px;
  --topnav-h: 58px;
  --font-sans: "Noto Sans KR", "Pretendard", -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
  --font-display: "Space Grotesk", "Noto Sans KR", sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
}

* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-sans) !important;
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}
.sg { font-family: var(--font-display); }

/* NiceGUI/Quasar 기본 폰트 오버라이드 */
body, .q-field, .q-btn, input, textarea, select, button {
  font-family: var(--font-sans) !important;
}

.material-symbols-outlined {
  font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 20;
}
/* 버그 수정 — 위 button/.q-btn 규칙의 font-family !important 가 그 안에 중첩된
   material-symbols-outlined span 까지 덮어써 아이콘이 리가처(ligature)로
   렌더링되지 못하고 "home"/"attach_file" 같은 원본 텍스트로 보이는 문제.
   (top-tab 버튼화로 새로 노출됐지만 button/.q-btn 안 아이콘 전반에 있던
   기존 버그.) 아이콘 폰트 패밀리를 다시 강제 복원.
   (family 이름은 material-symbols-local.css 의 'Material Symbols Outlined Local'
   과 반드시 일치시킬 것 — NiceGUI 가 등록하는 동명 원격 폰트와의 충돌 회피.) */
button .material-symbols-outlined,
.q-btn .material-symbols-outlined,
input.material-symbols-outlined,
select.material-symbols-outlined {
  font-family: 'Material Symbols Outlined Local' !important;
}

/* ─────────────────────────────────────────────────────────
   Top nav bar (IWP-Redesign-B — 가로 스크롤 탭바, 사이드바 대체)
   ───────────────────────────────────────────────────────── */
.top-nav-header {
  height: var(--topnav-h);
  width: 100%;
  background: rgba(5,11,20,.97);
  border-bottom: 1px solid rgba(14,165,233,.1);
  display: flex; align-items: center;
  padding: 0 28px;
  flex-shrink: 0;
  position: relative; z-index: 30;
  backdrop-filter: blur(20px);
}
.nav-logo {
  display: flex; align-items: center; gap: 9px;
  margin-right: 32px; flex-shrink: 0;
}
.nav-logo .logo-mark {
  width: 32px; height: 32px; border-radius: 8px;
  background: linear-gradient(135deg,#0ea5e9,#0369a1);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; color: #fff; font-size: 13px; font-weight: 700;
}
.nav-logo .logo-title {
  font-size: 13px; font-weight: 700; color: var(--text);
  letter-spacing: .02em; line-height: 1.2;
}
.nav-logo .logo-sub {
  font-size: 9px; color: var(--text-4); letter-spacing: .08em;
}
.beta-tag {
  display: inline-flex; align-items: center;
  padding: 2px 6px;
  font-size: 9.5px; font-weight: 600; letter-spacing: .04em;
  color: var(--text-3);
  background: rgba(255,255,255,.06);
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  flex-shrink: 0;
  margin-left: 6px;
}

/* 1) Tap highlight 차단 (사이드바 시절 잔상 이슈 재발 방지 — 상단 탭바에도 유지) */
html body #main-nav,
html body #main-nav * {
  -webkit-tap-highlight-color: transparent !important;
  -webkit-touch-callout: none !important;
}

#main-nav {
  display: flex; height: var(--topnav-h);
  align-items: stretch;
  overflow-x: auto; overflow-y: hidden;
  flex: 1; min-width: 0;
  scrollbar-width: thin;
  -webkit-overflow-scrolling: touch;
}
/* #main-nav 의 실제 직계 자식은 ui.html() 호출이 만드는 NiceGUI 래퍼 div
   하나뿐이라 #main-nav 자체의 display:flex 는 그 래퍼에만 적용되고, 래퍼
   내부의 버튼/그룹들은 일반 인라인 흐름(텍스트처럼 줄바꿈되는)으로 배치된다.
   탭 개수가 늘어 한 줄 너비를 넘기면 텍스트처럼 다음 줄로 "줄바꿈"되어
   버튼들이 두 번째 줄(y 좌표가 다른 곳)로 밀려나고, 그 줄은 #main-nav 의
   overflow-y:hidden 에 가려 화면에 전혀 안 보이게 된다(가로 스크롤바 유무만
   보면 정상처럼 보여서 자동화 테스트로 놓치기 쉬움). 래퍼 div를 구조적으로
   선택해 그 자체를 flex 컨테이너로 만들어 줄바꿈을 원천 차단한다. */
#main-nav > div {
  display: flex; align-items: stretch; height: 100%;
  min-width: -moz-max-content; min-width: max-content;
}
/* 탭이 화면 폭을 넘칠 때 스크롤 가능함을 항상 알아볼 수 있도록 — 숨김 대신
   상시 표시 (탭이 "사라진" 것처럼 보이는 문제 방지) */
#main-nav::-webkit-scrollbar { height: 5px; }
#main-nav::-webkit-scrollbar-track { background: rgba(255,255,255,.03); }
#main-nav::-webkit-scrollbar-thumb { background: rgba(14,165,233,.5); border-radius: 3px; }
#main-nav::-webkit-scrollbar-thumb:hover { background: rgba(14,165,233,.7); }

.top-tab {
  font-family: var(--font-sans);
  background: transparent !important;
  border: none; cursor: pointer;
  padding: 0 16px; height: 100%;
  font-size: 12.5px; font-weight: 500;
  color: var(--text-3);
  position: relative;
  transition: color .15s;
  white-space: nowrap; letter-spacing: -.01em;
  flex-shrink: 0;
  box-shadow: none !important;
  outline: 0 !important;
}
.top-tab:hover { color: var(--text) !important; }
.top-tab.active { color: var(--accent) !important; }
.top-tab.active::after {
  content: '';
  position: absolute; bottom: 0; left: 16px; right: 16px;
  height: 2px; background: var(--accent); border-radius: 1px;
}
.top-tab .material-symbols-outlined {
  font-size: 15px; vertical-align: -3px; margin-right: 4px;
}

/* ── 탭 그룹 드롭다운 (LLM 도구/업무 자동화/대시보드) ───────────────── */
/* display:flex(블록 레벨)로 두면 형제인 .top-tab(<button>, 기본 inline-block)과
   달리 항상 새 줄로 내려가 세로로 쌓여버린다(부모 #main-nav 의 실제 직계
   자식은 NiceGUI가 삽입하는 래퍼 div 하나뿐이라 flex가 적용되지 않고,
   버튼/그룹 div들은 그 래퍼 내부에서 일반 흐름으로 배치되기 때문 —
   그 결과 LLM 도구/업무 자동화/대시보드 그룹이 header 밖으로 밀려나
   overflow-y:hidden 에 가려 전혀 안 보이던 버그).
   inline-flex로 바꿔 그룹 자신은 flex 컨테이너를 유지하면서도 형제 버튼들과
   같은 줄에 나란히 흐르도록 한다. */
.nav-group { position: relative; height: 100%; display: inline-flex; flex-shrink: 0; vertical-align: top; }
.nav-group-btn { display: flex; align-items: center; }
.nav-caret { font-size: 14px !important; margin-left: 2px !important; margin-right: 0 !important; transition: transform .15s; }
.nav-group.open .nav-caret { transform: rotate(180deg); }
.nav-group.has-active .nav-group-btn { color: var(--accent) !important; }
.nav-group.has-active .nav-group-btn::after {
  content: ''; position: absolute; bottom: 0; left: 16px; right: 16px;
  height: 2px; background: var(--accent); border-radius: 1px;
}
/* #main-nav 는 overflow-y:hidden 이라 자식으로 둔 채로는 드롭다운이 header
   아래로 빠져나가는 부분이 통째로 잘려 안 보인다(getBoundingClientRect/
   getComputedStyle 상으로는 display:block·정상 크기로 보이지만 실제 페인트는
   조상의 overflow 클리핑에 가려짐 — Playwright is_visible() 같은 자동화
   체크로는 못 잡고 스크린샷으로만 드러나는 종류의 버그).
   그래서 열릴 때 JS가 body 로 reparent 하고 position:fixed 로 버튼 아래에
   직접 좌표를 계산해 배치한다("포탈" 패턴 — 커맨드 팔레트 오버레이와 동일
   레이어). display 토글도 .nav-group.open 자손 선택자 대신 드롭다운 자신의
   .open 클래스로 한다(reparent 후에는 더 이상 .nav-group 의 자손이 아니므로). */
.nav-dropdown {
  display: none;
  position: fixed;
  min-width: 210px; background: var(--bg-elev); border: 1px solid var(--border-strong);
  border-radius: var(--radius); box-shadow: 0 12px 28px rgba(0,0,0,.5), 0 2px 6px rgba(0,0,0,.4);
  padding: 4px; z-index: 200;
}
.nav-dropdown.open { display: block; }
.nav-dropdown-item {
  display: flex; align-items: center; gap: 8px; width: 100%;
  background: transparent !important; border: none; cursor: pointer;
  padding: 8px 10px; font-size: 12.5px; font-weight: 500; color: var(--text-2);
  border-radius: 6px; text-align: left; white-space: nowrap;
  box-shadow: none !important;
}
.nav-dropdown-item:hover { background: rgba(255,255,255,.06); color: var(--text); }
.nav-dropdown-item.active { background: rgba(14,165,233,.12); color: var(--accent); }
.nav-dropdown-item .material-symbols-outlined { font-size: 16px; margin-right: 0; }

/* ── 좌우 스크롤 버튼 + 가장자리 페이드 (오버플로 시 보조 힌트) ──────── */
.nav-scroll-btn {
  flex-shrink: 0; display: flex; align-items: center; justify-content: center;
  width: 24px; height: 100%; background: transparent !important; border: none;
  cursor: pointer; color: var(--text-3); box-shadow: none !important;
}
.nav-scroll-btn:hover { color: var(--text); }
.nav-scroll-btn .material-symbols-outlined { font-size: 18px; margin-right: 0; }
.nav-scroll-btn[disabled] { opacity: .25; cursor: default; pointer-events: none; }
.nav-fade-right, .nav-fade-left {
  position: absolute; top: 0; bottom: 0; width: 20px; pointer-events: none; z-index: 5;
  opacity: 0; transition: opacity .15s;
}
.nav-fade-right { right: 24px; background: linear-gradient(90deg, transparent, rgba(5,11,20,.97)); }
.nav-fade-left { left: 24px; background: linear-gradient(270deg, transparent, rgba(5,11,20,.97)); }
.nav-fade-right.show, .nav-fade-left.show { opacity: 1; }

/* ── 키보드 포커스 링 ──────────────────────────────────────────────── */
.top-tab:focus-visible,
.nav-dropdown-item:focus-visible,
.nav-scroll-btn:focus-visible {
  outline: 2px solid var(--accent) !important; outline-offset: -2px;
}

/* ── 커맨드 팔레트 (Cmd/Ctrl+K) ──────────────────────────────────────── */
.cmdk-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.55);
  z-index: 500; display: flex; align-items: flex-start; justify-content: center;
  padding-top: 12vh;
}
.cmdk-panel {
  width: 560px; max-width: 92vw; max-height: 60vh;
  background: var(--bg-elev); border: 1px solid var(--border-strong);
  border-radius: var(--radius-lg); box-shadow: 0 24px 60px rgba(0,0,0,.6);
  overflow: hidden; display: flex; flex-direction: column;
}
.cmdk-input {
  width: 100%; border: none; background: transparent; color: var(--text);
  font-size: 15px; padding: 16px 18px; outline: none; font-family: var(--font-sans);
  border-bottom: 1px solid var(--border);
}
.cmdk-input::placeholder { color: var(--text-4); }
.cmdk-list { overflow-y: auto; padding: 6px; }
.cmdk-item {
  display: flex; align-items: center; gap: 10px; padding: 10px 12px;
  border-radius: var(--radius); cursor: pointer; color: var(--text-2); font-size: 13px;
}
.cmdk-item .material-symbols-outlined { font-size: 16px; color: var(--text-3); margin-right: 0; }
.cmdk-item.sel { background: rgba(14,165,233,.12); color: var(--text); }
.cmdk-item .cmdk-group { margin-left: auto; font-size: 10.5px; color: var(--text-4); }
.cmdk-empty { padding: 20px; text-align: center; color: var(--text-4); font-size: 13px; }
.cmdk-hint {
  padding: 8px 14px; border-top: 1px solid var(--border);
  font-size: 11px; color: var(--text-4); display: flex; gap: 12px;
}

/* ── Phase 2: 상태 배너 (LLM 미연결 / 세션 데이터 휘발 안내) ──────────── */
.status-banner {
  width: 100%; flex-shrink: 0; display: flex; align-items: center; gap: 8px;
  padding: 7px 28px; font-size: 12.5px; font-weight: 500;
  border-bottom: 1px solid var(--border);
}
.status-banner .material-symbols-outlined { font-size: 16px; flex-shrink: 0; }
.status-banner-danger {
  background: rgba(239,68,68,.1); color: #fca5a5; border-bottom-color: rgba(239,68,68,.2);
}
.status-banner-info {
  background: rgba(14,165,233,.08); color: var(--text-2); border-bottom-color: rgba(14,165,233,.15);
}
.status-banner-link {
  background: transparent !important; border: none; cursor: pointer;
  color: var(--accent); font-weight: 600; font-size: 12.5px; padding: 0;
  text-decoration: underline; box-shadow: none !important;
}
.status-banner-dismiss {
  margin-left: auto; background: transparent !important; border: none; cursor: pointer;
  color: var(--text-4); box-shadow: none !important; padding: 2px; display: flex;
  flex-shrink: 0;
}
.status-banner-dismiss:hover { color: var(--text-2); }
.status-banner-dismiss .material-symbols-outlined { font-size: 16px; }

/* ── Phase 2: 실행 버튼 옆 모델 컨텍스트 라벨 ────────────────────────── */
/* .progress-block 등 공통 진행 컴포넌트 CSS는 파일 하단
   "ux/screens 공통 컴포넌트" 섹션에 통합되어 있음 (중복 제거). */
.exec-context-label {
  font-size: 11px; color: var(--text-4); display: flex; align-items: center; gap: 4px;
}
.exec-context-label .material-symbols-outlined { font-size: 13px; }
.exec-context-label b { color: var(--text-3); font-weight: 600; }

/* 서브탭 — 문서분석/요약/Q&A 등의 "실행/결과" 전환 바 */
.sub-tab-bar {
  display: flex; gap: 4px;
  padding: 10px 32px 0;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.sub-tab {
  font-family: var(--font-sans);
  background: transparent !important; border: none; cursor: pointer;
  padding: 6px 14px; font-size: 11.5px; font-weight: 500;
  color: var(--text-3); border-radius: 6px 6px 0 0;
  transition: all .15s; white-space: nowrap;
  box-shadow: none !important; outline: 0 !important;
}
.sub-tab:hover { color: var(--text) !important; background: rgba(255,255,255,.05) !important; }
.sub-tab.active { color: var(--accent) !important; background: rgba(14,165,233,.1) !important; }

.nav-status {
  display: flex; align-items: center; gap: 10px;
  flex-shrink: 0; margin-left: 12px;
}
.model-badge {
  display: flex; align-items: center; gap: 5px;
  padding: 4px 10px;
  background: rgba(34,197,94,.06);
  border: 1px solid rgba(34,197,94,.18);
  border-radius: 6px;
}
.model-badge .dot {
  width: 5px; height: 5px; background: var(--success);
  border-radius: 50%; animation: pulse 2s infinite;
}
.model-badge span { font-size: 10px; color: var(--success); font-weight: 500; }
@keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:.35;} }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes indeterminate {
  0%   { transform: translateX(-60%); width: 40%; }
  50%  { transform: translateX(40%);  width: 55%; }
  100% { transform: translateX(160%); width: 40%; }
}

/* 모델 선택 드롭다운 (구 sidebar-footer 위치 → 상단 우측으로 이동) */
.model-select-q.q-field { font-family: var(--font-sans) !important; }
.model-select-q .q-field__control,
.model-select-q .q-field__control * {
  background-color: transparent !important;
  background-image: none !important;
}
.model-select-q .q-field__control {
  background-color: rgba(255,255,255,.06) !important;
  border: 1px solid var(--border-strong) !important;
  border-radius: var(--radius) !important;
  min-height: 34px !important;
  padding: 0 12px !important;
  box-shadow: none !important;
  transition: border-color .12s, background-color .12s !important;
}
.model-select-q .q-field__control::before,
.model-select-q .q-field__control::after { display: none !important; }
.model-select-q .q-field__control:hover {
  background-color: rgba(255,255,255,.10) !important;
  border-color: rgba(14,165,233,.3) !important;
}
.model-select-q.q-field--focused .q-field__control {
  background-color: rgba(255,255,255,.12) !important;
  border-color: rgba(14,165,233,.4) !important;
}
.model-select-q,
.model-select-q .q-field__native,
.model-select-q .q-field__native *,
.model-select-q .q-field__input,
.model-select-q .q-select__input-value,
.model-select-q .q-select__display-value,
.model-select-q .q-field__control-container,
.model-select-q .q-field__control-container *,
.model-select-q [class*="q-field__"],
.model-select-q [class*="q-select__"] {
  color: var(--text) !important;
  -webkit-text-fill-color: var(--text) !important;
  font-size: 12.5px !important;
  font-weight: 500 !important;
}
.model-select-q .q-field__native { min-height: 32px !important; padding: 0 !important; }
.model-select-q .q-field__label { display: none !important; }
.model-select-q .q-field__append,
.model-select-q .q-field__append * { color: var(--text-3) !important; }

.q-menu.model-select-menu {
  background: var(--bg-elev) !important;
  border: 1px solid var(--border-strong) !important;
  border-radius: var(--radius) !important;
  box-shadow: 0 12px 28px rgba(0,0,0,.5), 0 2px 6px rgba(0,0,0,.4) !important;
  padding: 4px !important;
  margin-top: 4px !important;
}
.q-menu.model-select-menu .q-item {
  color: var(--text-2) !important;
  font-size: 12.5px !important;
  font-family: var(--font-sans) !important;
  min-height: 32px !important;
  padding: 6px 10px !important;
  border-radius: 6px !important;
  margin: 1px 0 !important;
}
.q-menu.model-select-menu .q-item:hover,
.q-menu.model-select-menu .q-item--active,
.q-menu.model-select-menu .q-item.q-manual-focusable--focused {
  background: rgba(14,165,233,.1) !important;
  color: var(--text) !important;
}
.q-menu.model-select-menu .q-item__label { color: inherit !important; }

/* ── 일반 ui.select 드롭다운 팝업 가독성 (기준월·연도·지표 선택 등) ───────────
   .q-menu.model-select-menu 외의 모든 Quasar 팝업 메뉴가 기본 흰 배경으로 떠서
   다크 테마의 밝은 글자와 겹쳐 '흰 글자 + 흰 배경'으로 안 보이던 문제 수정.
   (model-select-menu 는 더 높은 specificity 로 기존 스타일을 그대로 유지) */
.q-menu {
  background: var(--bg-elev) !important;
  color: var(--text-2) !important;
  border: 1px solid var(--border-strong) !important;
  border-radius: var(--radius) !important;
  box-shadow: 0 12px 28px rgba(0,0,0,.5), 0 2px 6px rgba(0,0,0,.4) !important;
}
.q-menu .q-item,
.q-menu .q-item__label,
.q-menu .q-item__section { color: var(--text-2) !important; }
.q-menu .q-item:hover,
.q-menu .q-item--active,
.q-menu .q-item.q-manual-focusable--focused {
  background: rgba(14,165,233,.1) !important;
  color: var(--text) !important;
}

/* Quasar global overrides — checkbox / upload / expansion 을 모노크롬에 맞춤 */
.q-checkbox { font-size: 12.5px !important; color: var(--text-2) !important; }
.q-checkbox__inner { color: var(--text-2) !important; }
.q-checkbox--dark .q-checkbox__inner,
.q-checkbox__inner--truthy { color: var(--accent) !important; }
.q-checkbox__label { color: var(--text-2) !important; font-size: 12.5px !important; }

.q-uploader {
  border-radius: var(--radius-lg) !important;
  border: 1px dashed var(--border-strong) !important;
  background: var(--bg-elev) !important;
  box-shadow: none !important;
  overflow: hidden;
}
.q-uploader__header {
  background: var(--bg) !important;
  color: var(--text) !important;
  border-bottom: 1px solid var(--border) !important;
}
.q-uploader__title { font-size: 12.5px !important; }
.q-uploader__list { background: transparent !important; }

/* 업로드 트리거 축소판 — shadcn Attachment 참조: 큰 점선 드롭존 대신 작고
   동적인 인라인 바 형태로 축소. 대부분의 패널은 별도 커스텀 HTML로 파일 목록을
   렌더링해 QUploader 자체 리스트를 즉시 비우지만, PDF 변환 패널처럼 변환 시작
   전까지 QUploader 리스트 자체가 유일한 파일 확인 수단인 곳도 있어 리스트는
   숨기지 않고 행 높이만 축소한다. 바이트 카운터 서브타이틀만 숨긴다.
   (class="upload-compact") */
.upload-compact.q-uploader {
  min-height: 0 !important;
  width: auto !important;
  max-width: 100%;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius) !important;
  background: transparent !important;
}
.upload-compact .q-uploader__header {
  background: var(--bg-elev) !important;
  border-bottom: none !important;
  min-height: 0 !important;
}
.upload-compact .q-uploader__header-content { padding: 3px 6px !important; }
.upload-compact .q-uploader__header .q-gutter-xs { padding: 2px 4px !important; }
.upload-compact .q-uploader__title { font-size: 11.5px !important; color: var(--text-2) !important; }
.upload-compact .q-uploader__subtitle { display: none !important; }
.upload-compact .q-uploader__list { min-height: 0 !important; padding: 2px !important; }
.upload-compact .q-uploader__list .q-item { min-height: 32px !important; padding: 2px 6px !important; }
.upload-compact .q-uploader__list .q-item__label { font-size: 11.5px !important; }
.upload-compact .q-uploader__list .q-item__section--avatar { min-width: 28px !important; }
.upload-compact .q-uploader__dnd { border: none !important; }
.upload-compact .q-btn--dense { min-height: 24px !important; padding: 0 6px !important; }
.upload-compact .q-btn--dense .q-icon { font-size: 17px !important; }

/* 보고서 패널 전용 — 파일별 업로드가 필수 입력이라 드래그 가능함이 시각적으로
   자명해야 한다. 다른 패널의 upload-compact 축소 트리거는 그대로 두고, 이
   조합 클래스에만 점선 드롭존 테두리 + 안내 문구(label=)를 추가한다.
   (class="upload-compact report-dropzone") */
.upload-compact.report-dropzone.q-uploader {
  border: 1px dashed var(--border-strong) !important;
  background: var(--bg-elev) !important;
}
.upload-compact.report-dropzone .q-uploader__header-content { padding: 8px 10px !important; }
.upload-compact.report-dropzone .q-uploader__title {
  font-size: 12px !important;
  color: var(--text-3) !important;
}

.q-expansion-item__container {
  border-radius: var(--radius) !important;
}
.q-expansion-item__container > .q-item {
  background: var(--bg-elev) !important;
  color: var(--text) !important;
  font-size: 13px !important;
  font-weight: 500 !important;
  min-height: 40px !important;
}

.q-notification {
  border-radius: var(--radius) !important;
  font-size: 12.5px !important;
}

/* ─────────────────────────────────────────────────────────
   Quasar tabs — monochrome
   ───────────────────────────────────────────────────────── */
.q-tabs {
  background: var(--bg) !important;
  border-bottom: 1px solid var(--border) !important;
}
.q-tab {
  font-family: var(--font-sans) !important;
  font-size: 13px !important;
  font-weight: 500 !important;
  text-transform: none !important;
  letter-spacing: 0 !important;
  color: var(--text-3) !important;
  min-height: 40px !important;
  padding: 0 14px !important;
}
.q-tab__indicator { background: var(--text) !important; height: 2px !important; }
.q-tab--active { color: var(--text) !important; }
.q-tab-panels, .q-tab-panel { background: transparent !important; padding: 16px 0 !important; }

/* Quasar input/textarea/number — monochrome underline */
.q-field--outlined .q-field__control {
  border-radius: var(--radius) !important;
  background: var(--bg) !important;
}
.q-field--outlined .q-field__control:hover::before {
  border-color: var(--border-strong) !important;
}
.q-field--outlined .q-field__control::before {
  border-color: var(--border) !important;
}
.q-field--outlined.q-field--focused .q-field__control::after {
  border-color: var(--text-2) !important;
  border-width: 1px !important;
}
.q-field__label { color: var(--text-3) !important; font-size: 12.5px !important; }
.q-field--focused .q-field__label { color: var(--text) !important; }
.q-field__native, .q-field__input {
  color: var(--text) !important;
  font-size: 13.5px !important;
  font-family: var(--font-sans) !important;
}

/* Quasar linear progress — monochrome */
.q-linear-progress {
  color: var(--accent) !important;
  background: var(--bg-sunken) !important;
  border-radius: var(--radius-full) !important;
  height: 4px !important;
}

/* Quasar dialog — monochrome card */
.q-dialog__inner > .q-card {
  border-radius: var(--radius-lg) !important;
  border: 1px solid var(--border) !important;
  box-shadow: var(--shadow-md) !important;
  background: var(--bg-elev) !important;
  color: var(--text) !important;
}

/* ─────────────────────────────────────────────────────────
   IWP-Redesign-B 목업 유틸리티 클래스
   (raw ui.html() 마크업에서 쓰는 카드/배지/칩 — Quasar 컴포넌트가 아니므로
   위 .q-btn 등 오버라이드와는 별개로 직접 정의해야 함)
   ───────────────────────────────────────────────────────── */
.card {
  background: rgba(255,255,255,.025);
  border: 1px solid var(--border);
  border-radius: 12px;
}
.result-item {
  background: rgba(255,255,255,.02);
  border: 1px solid rgba(255,255,255,.06);
  border-radius: 10px;
  padding: 16px 18px;
  cursor: pointer;
  transition: all .2s;
}
.result-item:hover {
  border-color: rgba(14,165,233,.28);
  background: rgba(14,165,233,.03);
  transform: translateY(-1px);
}
.err-highlight {
  background: rgba(239,68,68,.15);
  border-bottom: 2px solid var(--danger);
  cursor: pointer;
}
.err-card-item {
  background: rgba(255,255,255,.03);
  border: 1px solid rgba(255,255,255,.06);
  border-radius: 8px;
  padding: 12px 14px;
  font-size: 12px;
  line-height: 1.65;
}
.risk-bar-track {
  height: 6px; background: rgba(255,255,255,.07);
  border-radius: 3px; overflow: hidden;
}
.risk-bar-fill { height: 100%; border-radius: 3px; transition: width .8s ease; }
.tl-dot-new {
  width: 10px; height: 10px; background: var(--warning);
  border-radius: 50%; box-shadow: 0 0 0 3px rgba(245,158,11,.2);
}
.tl-dot-normal {
  width: 10px; height: 10px; background: var(--accent);
  border-radius: 50%; box-shadow: 0 0 0 3px rgba(14,165,233,.15);
}
.badge-new {
  font-size: 10px; padding: 2px 7px;
  background: rgba(245,158,11,.12); color: var(--warning);
  border-radius: 99px; font-weight: 600;
}
.badge-rag {
  font-size: 10px; padding: 2px 7px;
  background: rgba(14,165,233,.12); color: var(--accent);
  border-radius: 99px; font-weight: 600; letter-spacing: .04em;
}
.badge-done {
  font-size: 10px; padding: 2px 7px;
  background: rgba(34,197,94,.1); color: var(--success);
  border-radius: 99px; font-weight: 600;
}
.badge-reviewing {
  font-size: 10px; padding: 2px 7px;
  background: rgba(245,158,11,.1); color: var(--warning);
  border-radius: 99px; font-weight: 600;
}
.badge-error {
  font-size: 10px; padding: 2px 7px;
  background: rgba(239,68,68,.1); color: var(--danger);
  border-radius: 99px; font-weight: 600;
}
.badge-idle {
  font-size: 10px; padding: 2px 7px;
  background: rgba(255,255,255,.06); color: var(--text-3);
  border-radius: 99px; font-weight: 600;
}
.chip {
  padding: 4px 12px; border-radius: 99px;
  font-size: 11px; font-weight: 500; cursor: pointer;
  transition: all .15s; display: inline-flex; align-items: center;
}
.chip-active {
  background: rgba(14,165,233,.15); border: 1px solid rgba(14,165,233,.35);
  color: var(--accent);
}
.chip-inactive {
  background: rgba(255,255,255,.03); border: 1px solid rgba(255,255,255,.08);
  color: var(--text-3);
}
.chip-inactive:hover { border-color: rgba(255,255,255,.18); color: var(--text); }

/* raw <button>/<input> 마크업용 (Quasar 아닌 순수 HTML — 이름 충돌 없음) */
.btn-primary {
  padding: 10px 20px;
  background: linear-gradient(135deg,#0ea5e9,#0369a1);
  border: none; border-radius: 9px;
  font-size: 13px; font-weight: 600; color: #fff; cursor: pointer;
  font-family: var(--font-sans); transition: opacity .2s; letter-spacing: -.01em;
}
.btn-primary:hover { opacity: .85; }
.btn-secondary {
  padding: 8px 16px;
  background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.1);
  border-radius: 8px; font-size: 12px; font-weight: 500; color: var(--text-2);
  cursor: pointer; font-family: var(--font-sans); transition: all .15s;
}
.btn-secondary:hover { background: rgba(255,255,255,.09); color: var(--text); }
.inp {
  background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.1);
  border-radius: 9px; padding: 10px 14px; font-size: 13px; color: var(--text);
  font-family: var(--font-sans); outline: none; width: 100%;
  transition: border-color .15s;
}
.inp:focus { border-color: rgba(14,165,233,.4); }
.inp::placeholder { color: var(--text-4); }
textarea.inp { resize: none; line-height: 1.6; }
select.inp { cursor: pointer; color-scheme: dark; }
select.inp option { background: var(--bg-elev); color: var(--text); }

/* ─────────────────────────────────────────────────────────
   Generic panel helpers used by ported panels
   ───────────────────────────────────────────────────────── */
.section-card {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 16px;
  margin-bottom: 12px;
}
.section-card-title {
  font-size: 13px; font-weight: 600; color: var(--text);
  margin-bottom: 12px;
  display: flex; align-items: center; gap: 8px;
}
.section-card-title .material-symbols-outlined {
  font-size: 16px; color: var(--text-3);
}
.muted-label {
  font-size: 11px; color: var(--text-3);
  letter-spacing: .03em;
  text-transform: uppercase;
  margin-bottom: 8px; font-weight: 600;
}
.muted-text { color: var(--text-3); font-size: 12.5px; }
.divider { height: 1px; background: var(--border); margin: 12px 0; }

/* List of selectable items (e.g. report list, mail list) */
.list-item {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px;
  border-radius: var(--radius);
  cursor: pointer;
  margin-bottom: 4px;
  background: var(--bg);
  border: 1px solid var(--border);
  font-size: 13px; font-weight: 500;
  color: var(--text-2);
  transition: background-color .12s, border-color .12s, color .12s;
}
.list-item:hover {
  background: var(--bg-elev);
  border-color: var(--border-strong);
  color: var(--text);
}
.list-item.active {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}

/* Mail item (Outlook panel) */
.mail-item {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px 14px;
  margin-bottom: 6px;
  cursor: pointer;
  transition: border-color .12s, background-color .12s;
}
.mail-item:hover { border-color: var(--border-strong); background: var(--bg-elev); }
.mail-item.selected { border-color: var(--text-2); background: var(--bg-elev); }
.mail-subject { font-size: 13px; font-weight: 600; color: var(--text); margin-bottom: 4px; }
.mail-meta { font-size: 11.5px; color: var(--text-3); display: flex; align-items: center; gap: 6px; }

/* Tag — small monochrome label (direction, source badges, etc.) */
.tag {
  display: inline-flex; align-items: center;
  padding: 2px 7px;
  font-size: 10.5px; font-weight: 600;
  letter-spacing: .02em;
  border-radius: 4px;
  background: var(--bg-elev);
  color: var(--text-2);
  border: 1px solid var(--border);
}
.tag.solid {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}

/* Reg/news card */
.reg-card {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 14px 16px;
  margin-bottom: 10px;
}
.reg-card .reg-title {
  font-size: 13px; font-weight: 600; color: var(--text);
  margin-bottom: 8px;
  display: flex; align-items: center; gap: 6px;
  flex-wrap: wrap;
}
.reg-card .reg-summary {
  font-size: 13px; line-height: 1.7;
  color: var(--text-2);
  white-space: pre-wrap; word-break: break-word;
  margin-bottom: 8px;
}
.reg-card .reg-link {
  font-size: 11.5px;
  color: var(--text-2);
  text-decoration: none;
  border-bottom: 1px solid var(--text-4);
}
.reg-card .reg-link:hover {
  color: var(--text);
  border-bottom-color: var(--text);
}

/* Reusable info block ("선택된 메일", "조회 결과 N건" 등) */
.info-block {
  background: var(--bg-elev);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 14px;
  font-size: 12.5px;
  color: var(--text);
}
.info-block b { color: var(--text); font-weight: 600; }

/* Monospace log area */
.log-area {
  background: #0a0a0a;
  color: #d6d3d1;
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 14px;
  border-radius: var(--radius);
  height: 460px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
  border: 1px solid var(--border);
}

/* Server status row (admin panel) */
.server-row {
  display: flex; align-items: center; gap: 10px;
  padding: 6px 0;
  font-size: 12.5px;
  color: var(--text-2);
}
.server-row .dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--text-4);
}
.server-row .dot.up { background: var(--success); }
.server-row .dot.down { background: var(--danger); }

/* Two-column flexible layout (filter / result) */
.filter-result-row {
  display: flex;
  gap: 16px;
  align-items: stretch;
  flex: 1;
  padding: 20px 24px;
  overflow: hidden;
  min-height: 0;
}
.filter-col {
  width: clamp(220px, 24vw, 300px);
  min-width: 220px;
  flex-shrink: 0;
  overflow-y: auto;
}
.result-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Three-column variant (sidebar list / log / control) */
.tri-col-row {
  display: grid;
  grid-template-columns: minmax(190px, 230px) minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
  flex: 1;
  padding: 20px 24px;
  overflow: hidden;
  min-height: 0;
}
.tri-col-row > div {
  overflow-y: auto;
  min-width: 0;
}
/* 1280px 이하 — 3열을 세로 스택으로 전환. DOM 순서(목록 → 업로드/파라미터
   → AI 어시스턴트/로그)가 이미 보고서 작성 흐름과 일치하므로 별도 재배치 없이
   그대로 쌓는다. */
@media (max-width: 1280px) {
  .tri-col-row {
    grid-template-columns: 1fr;
    display: flex;
    flex-direction: column;
    overflow-y: auto;
  }
  .tri-col-row > div { overflow-y: visible; flex-shrink: 0; }
}

/* ─────────────────────────────────────────────────────────
   Main area & panels
   ───────────────────────────────────────────────────────── */
.main-area {
  /* flex:1 로 nicegui-content(세로 flex 컨테이너) 내 나머지 공간을 채운다.
     상태 배너(.status-banner)가 header 아래에 추가로 들어와도 자동으로
     남는 높이만 차지하므로 별도 calc() 보정이 필요 없다. */
  flex: 1;
  min-height: 0;
  width: 100%;
  display: flex; flex-direction: column;
  overflow: hidden;
}
.panel {
  flex: 1;
  display: flex; flex-direction: column;
  overflow: hidden; min-height: 0;
}
.page-head {
  padding: 24px 32px 16px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  display: flex; align-items: flex-start; gap: 12px;
}
.page-head > .titles { flex: 1; }
.page-title {
  font-size: 20px; font-weight: 600;
  letter-spacing: -0.015em; color: var(--text);
}
.page-subtitle {
  font-size: 13px; color: var(--text-3); margin-top: 4px;
}

/* ─────────────────────────────────────────────────────────
   Chat (Home / Legal)
   ───────────────────────────────────────────────────────── */
.chat-wrap {
  flex: 1;
  display: flex; flex-direction: column;
  overflow: hidden; min-height: 0;
}
.chat-scroll {
  flex: 1; overflow-y: auto;
  padding: 32px 0;
}
.chat-inner {
  max-width: 820px; margin: 0 auto;
  padding: 0 32px;
  display: flex; flex-direction: column;
  gap: 24px;
}
.msg {
  display: flex; flex-direction: column; gap: 6px;
  font-size: 14.5px; line-height: 1.7;
}
.msg-role {
  display: flex; align-items: center; gap: 8px;
  font-size: 12px; color: var(--text-3); font-weight: 500;
}
.msg-role .avatar {
  width: 22px; height: 22px; border-radius: 6px;
  display: grid; place-items: center;
  font-size: 11px; font-weight: 600; letter-spacing: -.02em;
}
.msg.user .msg-role .avatar { background: var(--accent); color: #fff; }
.msg.ai .msg-role .avatar {
  background: var(--bg-elev); color: var(--text);
  border: 1px solid var(--border);
}
.msg-body {
  padding-left: 30px;
  color: var(--text);
  white-space: pre-wrap; word-break: break-word;
}
.msg-meta {
  padding-left: 30px;
  display: flex; gap: 6px; flex-wrap: wrap;
  margin-top: 4px;
}
.meta-chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 2px 8px;
  background: var(--bg-elev);
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  font-size: 11px; color: var(--text-3);
}
.meta-chip .material-symbols-outlined { font-size: 12px; }

.chat-cursor::after {
  content: "▌";
  color: var(--text-3);
  margin-left: 2px;
  animation: blink 1.1s steps(2) infinite;
}
@keyframes blink { 50% { opacity: 0; } }

/* Empty state */
.chat-empty {
  flex: 1;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  padding: 40px 24px;
  max-width: 720px; margin: 0 auto;
  text-align: center;
}
.chat-empty .empty-mark {
  width: 44px; height: 44px;
  border-radius: 12px;
  background: var(--bg-elev);
  border: 1px solid var(--border);
  display: grid; place-items: center;
  color: var(--text-2);
  margin-bottom: 16px;
}
.chat-empty .empty-mark .material-symbols-outlined { font-size: 22px; }
.chat-empty h2 {
  font-size: 22px; font-weight: 600;
  letter-spacing: -.02em; margin: 0 0 8px;
  color: var(--text);
}
.chat-empty p {
  margin: 0 0 24px;
  color: var(--text-3);
  font-size: 14px; line-height: 1.6;
  max-width: 460px;
}
.suggestion-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px; width: 100%; max-width: 640px;
}
.suggestion {
  text-align: left;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 14px 16px;
  cursor: pointer;
  display: flex; flex-direction: column; gap: 4px;
  transition: background-color .12s, border-color .12s;
}
.suggestion:hover {
  background: var(--bg-elev);
  border-color: var(--border-strong);
}
.suggestion .s-title { font-size: 13px; font-weight: 500; color: var(--text); }
.suggestion .s-sub { font-size: 12px; color: var(--text-3); }

/* ─────────────────────────────────────────────────────────
   Composer (input)
   ───────────────────────────────────────────────────────── */
.composer-wrap {
  flex-shrink: 0;
  border-top: 1px solid var(--border);
  background: var(--bg);
  padding: 16px 32px 24px;
}
.composer {
  max-width: 820px; margin: 0 auto;
  background: var(--bg-elev);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 12px 12px 12px 16px;
  display: flex; align-items: flex-end; gap: 8px;
  transition: border-color .12s, background-color .12s;
}
.composer:focus-within { border-color: var(--text-2); background: var(--bg); }

/* NiceGUI textarea를 composer 안에 자연스럽게 삽입 */
.composer .q-field {
  flex: 1;
  background: transparent !important;
}
.composer .q-field__control,
.composer .q-field__control::before,
.composer .q-field__control::after {
  border: 0 !important;
  background: transparent !important;
  padding: 0 !important;
  min-height: 0 !important;
}
.composer .q-field__native, .composer textarea {
  font-family: var(--font-sans) !important;
  font-size: 14.5px !important;
  line-height: 1.6 !important;
  color: var(--text) !important;
  padding: 6px 0 !important;
  background: transparent !important;
}
.composer .q-field__native::placeholder,
.composer textarea::placeholder { color: var(--text-4); }
.composer-actions {
  display: flex; align-items: center; gap: 4px;
}
.composer-hint {
  max-width: 820px; margin: 8px auto 0;
  font-size: 11.5px; color: var(--text-4);
  display: flex; justify-content: space-between;
  padding: 0 4px;
}
.kbd {
  font-family: var(--font-mono);
  font-size: 10.5px;
  padding: 1px 5px;
  border: 1px solid var(--border);
  border-bottom-width: 2px;
  border-radius: 4px;
  background: var(--bg-elev);
  color: var(--text-2);
}

/* Icon buttons */
.icon-btn {
  width: 32px; height: 32px; border-radius: var(--radius);
  display: grid; place-items: center;
  border: 0; background: transparent;
  color: var(--text-3); cursor: pointer;
  transition: background-color .12s, color .12s;
}
.icon-btn:hover { background: rgba(0,0,0,.05); color: var(--text); }
.icon-btn .material-symbols-outlined { font-size: 18px; }
.send-btn {
  width: 32px; height: 32px; border-radius: var(--radius);
  border: 0; background: var(--accent); color: #fff;
  display: grid; place-items: center;
  cursor: pointer;
  transition: background-color .12s, opacity .12s;
}
.send-btn:hover { background: var(--accent-hover); }
.send-btn[disabled], .send-btn.is-disabled {
  background: var(--bg-sunken);
  color: var(--text-4);
  cursor: not-allowed;
}
.send-btn.is-stop {
  background: var(--danger);
}
.send-btn.is-stop:hover { background: var(--danger); opacity: .85; }
.send-btn .material-symbols-outlined {
  font-size: 18px;
  font-variation-settings: 'FILL' 1, 'wght' 500, 'GRAD' 0, 'opsz' 20;
}

/* ─────────────────────────────────────────────────────────
   Buttons & form controls
   ───────────────────────────────────────────────────────── */
.btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 7px 12px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text);
  font-size: 12.5px; font-weight: 500;
  cursor: pointer; font-family: inherit;
  transition: background-color .12s, border-color .12s;
}
.btn:hover { background: var(--bg-elev); border-color: var(--border-strong); }
.btn.primary {
  background: var(--accent); color: #fff; border-color: var(--accent);
}
.btn.primary:hover { background: var(--accent-hover); border-color: var(--accent-hover); }
.btn .material-symbols-outlined { font-size: 14px; }
.btn[disabled], .btn.is-disabled { opacity: .5; cursor: not-allowed; }

/* ─────────────────────────────────────────────────────────
   BUTTONS — v3.0 specificity 최종 해결
   
   Quasar 가 q-btn 에 붙이는 실제 클래스 4-5개 체인:
     q-btn  q-btn-item  q-btn--standard  q-btn--actionable
     q-btn--rectangle  bg-primary  text-white  btn-mono ...
   
   Quasar 내부 룰이 4개 클래스 체인 (specificity 0,0,4,0) 을 쓰므로,
   우리는 5개 클래스 + html body 로 0,0,5,2 를 만들어 cascade 승리.
   
   bg-primary 가 붙은 채로도 우리 색이 반드시 이기도록 모든 변형 케이스
   를 명시.
   ───────────────────────────────────────────────────────── */

/* ── GLOBAL DEFAULT (모든 q-btn) — 다크 카드 버튼(.btn-secondary 상당) ── */
html body .q-btn,
html body .q-btn.q-btn--standard,
html body .q-btn.q-btn--standard.q-btn--actionable,
html body .q-btn.q-btn--standard.q-btn--actionable.q-btn--rectangle,
html body .q-btn.bg-primary,
html body .q-btn.q-btn--standard.bg-primary,
html body .q-btn.q-btn--standard.q-btn--actionable.bg-primary,
html body .q-btn.q-btn--standard.q-btn--actionable.q-btn--rectangle.bg-primary,
html body .q-btn.text-white,
html body .q-btn.q-btn--standard.text-white {
  background: rgba(255,255,255,.05) !important;
  background-color: rgba(255,255,255,.05) !important;
  background-image: none !important;
  color: var(--text-2) !important;
  border: 1px solid var(--border-strong) !important;
  border-radius: 8px !important;
  text-transform: none !important;
  font-family: var(--font-sans) !important;
  font-weight: 500 !important;
  font-size: 13px !important;
  letter-spacing: 0 !important;
  box-shadow: none !important;
  min-height: 34px !important;
  padding: 0 14px !important;
  line-height: 1.2 !important;
}
html body .q-btn:hover,
html body .q-btn.q-btn--standard:hover,
html body .q-btn.q-btn--standard.q-btn--actionable:hover,
html body .q-btn.q-btn--standard.q-btn--actionable.bg-primary:hover {
  background: rgba(255,255,255,.09) !important;
  background-color: rgba(255,255,255,.09) !important;
  border-color: var(--border-strong) !important;
  color: var(--text) !important;
}
html body .q-btn .q-btn__content {
  font-size: 13px !important;
  line-height: 1.2 !important;
  gap: 6px;
  color: inherit !important;
}
html body .q-btn[disabled],
html body .q-btn.disabled,
html body .q-btn--disable { opacity: 0.5 !important; }

/* ── PRIMARY MONO — 스카이블루 그라디언트(.btn-primary 상당) ── */
html body .q-btn.btn-primary-mono,
html body .q-btn.q-btn--standard.btn-primary-mono,
html body .q-btn.q-btn--standard.q-btn--actionable.btn-primary-mono,
html body .q-btn.q-btn--standard.q-btn--actionable.q-btn--rectangle.btn-primary-mono,
html body .q-btn.btn-primary-mono.bg-primary,
html body .q-btn.q-btn--standard.btn-primary-mono.bg-primary,
html body .q-btn.q-btn--standard.q-btn--actionable.btn-primary-mono.bg-primary,
html body .q-btn.q-btn--standard.q-btn--actionable.q-btn--rectangle.btn-primary-mono.bg-primary,
html body .q-btn.btn-primary-mono.text-white,
html body .q-btn.q-btn--standard.btn-primary-mono.text-white {
  background: linear-gradient(135deg,#0ea5e9,#0369a1) !important;
  background-color: #0ea5e9 !important;
  background-image: linear-gradient(135deg,#0ea5e9,#0369a1) !important;
  color: #ffffff !important;
  border: none !important;
  min-height: 34px !important;
  padding: 0 14px !important;
  font-size: 13px !important;
  font-weight: 600 !important;
}
html body .q-btn.btn-primary-mono:hover,
html body .q-btn.q-btn--standard.btn-primary-mono:hover,
html body .q-btn.q-btn--standard.q-btn--actionable.btn-primary-mono:hover,
html body .q-btn.q-btn--standard.q-btn--actionable.btn-primary-mono.bg-primary:hover {
  opacity: .85 !important;
  color: #ffffff !important;
}
html body .q-btn.btn-primary-mono .q-btn__content,
html body .q-btn.btn-primary-mono .q-btn__content *,
html body .q-btn.q-btn--standard.btn-primary-mono .q-btn__content {
  color: #ffffff !important;
}

/* ── SECONDARY MONO — 다크 카드 배경 + 밝은 글자 + 보더 ── */
html body .q-btn.btn-mono,
html body .q-btn.q-btn--standard.btn-mono,
html body .q-btn.q-btn--standard.q-btn--actionable.btn-mono,
html body .q-btn.q-btn--standard.q-btn--actionable.q-btn--rectangle.btn-mono,
html body .q-btn.btn-mono.bg-primary,
html body .q-btn.q-btn--standard.btn-mono.bg-primary,
html body .q-btn.q-btn--standard.q-btn--actionable.btn-mono.bg-primary,
html body .q-btn.q-btn--standard.q-btn--actionable.q-btn--rectangle.btn-mono.bg-primary,
html body .q-btn.btn-mono.text-white,
html body .q-btn.q-btn--standard.btn-mono.text-white {
  background: rgba(255,255,255,.05) !important;
  background-color: rgba(255,255,255,.05) !important;
  background-image: none !important;
  color: var(--text-2) !important;
  border: 1px solid var(--border-strong) !important;
  min-height: 34px !important;
  padding: 0 14px !important;
  font-size: 13px !important;
}
html body .q-btn.btn-mono:hover,
html body .q-btn.q-btn--standard.btn-mono:hover,
html body .q-btn.q-btn--standard.q-btn--actionable.btn-mono:hover,
html body .q-btn.q-btn--standard.q-btn--actionable.btn-mono.bg-primary:hover {
  background: rgba(255,255,255,.09) !important;
  background-color: rgba(255,255,255,.09) !important;
  border-color: rgba(14,165,233,.3) !important;
  color: var(--text) !important;
}
html body .q-btn.btn-mono .q-btn__content,
html body .q-btn.btn-mono .q-btn__content *,
html body .q-btn.q-btn--standard.btn-mono .q-btn__content {
  color: inherit !important;
}

/* COMPACT — 작은 버튼 */
html body .q-btn.btn-sm,
html body .q-btn.q-btn--standard.btn-sm,
html body .q-btn.q-btn--standard.q-btn--actionable.btn-sm,
html body .q-btn.btn-primary-mono.btn-sm,
html body .q-btn.btn-mono.btn-sm {
  min-height: 28px !important;
  padding: 0 10px !important;
  font-size: 11.5px !important;
}
html body .q-btn.btn-sm .q-btn__content,
html body .q-btn.btn-sm .q-btn__content * { font-size: 11.5px !important; }

/* focus ripple / overlay 제거 */
html body .q-btn .q-focus-helper { background: transparent !important; opacity: 0 !important; }
html body .q-btn::before { box-shadow: none !important; }

/* Active toggle state */
html body .q-btn.btn-mono.is-active,
html body .q-btn.q-btn--standard.btn-mono.is-active,
html body .q-btn.q-btn--standard.q-btn--actionable.btn-mono.is-active,
html body .q-btn.btn-mono.active,
html body .q-btn.q-btn--standard.btn-mono.active {
  background: rgba(14,165,233,.15) !important;
  background-color: rgba(14,165,233,.15) !important;
  color: var(--accent) !important;
  border-color: rgba(14,165,233,.35) !important;
}
html body .q-btn.btn-mono.is-active .q-btn__content,
html body .q-btn.btn-mono.is-active .q-btn__content *,
html body .q-btn.btn-mono.active .q-btn__content,
html body .q-btn.btn-mono.active .q-btn__content * {
  color: var(--accent) !important;
}

/* ─────────────────────────────────────────────────────────
   Status chips (legal panel)
   ───────────────────────────────────────────────────────── */
.search-status-bar {
  padding: 12px 32px;
  border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 8px;
  flex-shrink: 0; flex-wrap: wrap;
}
.status-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px;
  border-radius: var(--radius-full);
  font-size: 11.5px;
  background: var(--bg-elev);
  border: 1px solid var(--border);
  color: var(--text-2); font-weight: 500;
}
.status-chip .dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--text-3);
}
.status-chip.ok .dot { background: var(--success); }
.status-chip.warn .dot { background: var(--warning); }
.status-chip.err .dot { background: var(--danger); }
.mem-bar {
  display: inline-flex; align-items: center; gap: 8px;
  font-size: 11.5px; color: var(--text-3);
  margin-left: auto;
}
.mem-bar .bar {
  width: 80px; height: 4px; border-radius: 2px;
  background: var(--bg-sunken); overflow: hidden;
}
.mem-bar .fill {
  height: 100%; background: var(--text-2);
  transition: width .3s;
}

/* ─────────────────────────────────────────────────────────
   Split layout (Document analysis / Summary)
   ───────────────────────────────────────────────────────── */
.split {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 1fr;
  overflow: hidden; min-height: 0;
}
.split > .pane {
  display: flex; flex-direction: column;
  overflow: hidden; min-height: 0;
}
.split > .pane + .pane { border-left: 1px solid var(--border); }
.pane-head {
  padding: 16px 24px;
  border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 12px;
  flex-shrink: 0;
}
.pane-head h3 {
  margin: 0; font-size: 14px; font-weight: 600;
  color: var(--text);
}
.pane-head .pane-sub { font-size: 12px; color: var(--text-3); }
.pane-body {
  flex: 1; overflow-y: auto;
  padding: 20px 24px;
}

/* Upload zone */
.dropzone {
  border: 1px dashed var(--border-strong);
  background: var(--bg-elev);
  border-radius: var(--radius-lg);
  padding: 28px 20px;
  text-align: center;
  cursor: pointer;
  display: flex; flex-direction: column;
  align-items: center; gap: 8px;
  transition: background-color .12s, border-color .12s;
}
.dropzone:hover { background: var(--bg-sunken); border-color: var(--text-3); }
.dropzone .material-symbols-outlined { font-size: 24px; color: var(--text-3); }
.dropzone .dz-title { font-size: 13px; font-weight: 500; color: var(--text); }
.dropzone .dz-sub { font-size: 12px; color: var(--text-3); }

.file-card {
  margin-top: 12px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 12px;
  display: flex; align-items: center; gap: 10px;
}
.file-card .material-symbols-outlined { font-size: 18px; color: var(--text-2); }
.file-card .fc-name {
  flex: 1; font-size: 13px; font-weight: 500; color: var(--text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.file-card .fc-size { font-size: 11.5px; color: var(--text-3); }

/* Preview text box */
.preview-text {
  margin-top: 16px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  min-height: 240px;
  max-height: 600px;
  overflow-y: auto;
  font-size: 13px; line-height: 1.7;
  color: var(--text-2);
  white-space: pre-wrap;
}

/* 업로드 영역 sticky — 분석 후에도 추가 업로드 가능 */
.upload-sticky {
  position: sticky;
  top: 0;
  z-index: 5;
  background: var(--bg);
  padding-bottom: 8px;
  margin-bottom: 4px;
  border-bottom: 1px solid var(--border);
}

/* Action row & checkbox */
.action-row {
  display: flex; gap: 6px; flex-wrap: wrap;
  margin-bottom: 16px;
}
.check-row {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--text-3);
  margin-bottom: 12px; user-select: none; cursor: pointer;
}

/* Section result expansion */
.section-result {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-bottom: 10px;
  overflow: hidden;
}
.section-result-head {
  cursor: pointer;
  padding: 10px 14px;
  font-size: 13px; font-weight: 500;
  color: var(--text);
  display: flex; align-items: center; gap: 8px;
  background: var(--bg-elev);
}
.section-result-head .count {
  margin-left: auto;
  font-size: 11px; color: var(--text-3);
  padding: 1px 8px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
}
.err-card {
  padding: 12px 14px;
  border-top: 1px solid var(--border);
}
.err-card .err-row {
  display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;
  margin-bottom: 8px;
}
.err-card .err-from {
  background: var(--bg-sunken);
  color: var(--text);
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 12.5px;
  text-decoration: line-through;
  text-decoration-color: var(--text-3);
}
.err-card .err-to {
  background: var(--text); color: #fff;
  padding: 2px 7px; border-radius: 4px;
  font-size: 12.5px; font-weight: 500;
}
.err-card .err-arrow { color: var(--text-4); }
.err-card .err-reason {
  font-size: 12px; color: var(--text-3);
  background: var(--bg-elev);
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  border-left: 2px solid var(--text-3);
  line-height: 1.6;
}
.err-card .err-reason b { color: var(--text); font-weight: 600; }

/* Highlight inline (for analyze_one_section output) */
.hl-err {
  background: var(--bg-sunken);
  color: var(--text);
  padding: 0 3px;
  border-radius: 3px;
  border-bottom: 1px solid var(--text-3);
}

/* Scrollbar polish */
*::-webkit-scrollbar { width: 8px; height: 8px; }
*::-webkit-scrollbar-thumb {
  background: var(--border-strong); border-radius: 4px;
}
*::-webkit-scrollbar-thumb:hover { background: var(--text-4); }

/* ─────────────────────────────────────────────────────────
   ux/screens 공통 컴포넌트 — 진행 상태(취소 가능) · 스텝퍼 · 체크리스트
   (A~D 전 패널에서 재사용. 새 색상 없이 기존 토큰만 사용)
   ───────────────────────────────────────────────────────── */
.progress-block {
  display: flex; align-items: center; gap: 10px; padding: 10px 0;
  color: var(--text-3); font-size: 13px;
}
.progress-block .material-symbols-outlined.spin {
  font-size: 16px; animation: spin 1.2s linear infinite; flex-shrink: 0;
}
.progress-block-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 5px; }
.progress-block-label {
  display: flex; align-items: baseline; gap: 8px; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis;
}
.progress-block-elapsed { color: var(--text-4); font-size: 11.5px; flex-shrink: 0; }
.progress-bar-track {
  width: 100%; height: 4px; border-radius: 2px; background: var(--border);
  overflow: hidden; position: relative;
}
.progress-bar-fill {
  position: absolute; top: 0; left: 0; height: 100%; border-radius: 2px;
  background: var(--accent); animation: indeterminate 1.4s ease-in-out infinite;
}
.progress-cancel-btn {
  flex-shrink: 0; display: flex; align-items: center; gap: 4px;
  background: transparent !important; border: 1px solid var(--border) !important;
  color: var(--text-3); cursor: pointer; font-size: 11.5px; font-weight: 500;
  padding: 4px 9px; border-radius: var(--radius); box-shadow: none !important;
}
.progress-cancel-btn:hover { color: var(--danger); border-color: rgba(239,68,68,.4) !important; }
.progress-cancel-btn .material-symbols-outlined { font-size: 14px; margin-right: 0; }

@keyframes spin { to { transform: rotate(360deg); } }
@keyframes indeterminate {
  0%   { transform: translateX(-60%); width: 40%; }
  50%  { transform: translateX(40%);  width: 55%; }
  100% { transform: translateX(160%); width: 40%; }
}

/* 스켈레톤 카드 (대기 상태 placeholder) */
.skeleton-card {
  height: 68px; border-radius: var(--radius); background: var(--bg-elev);
  border: 1px solid var(--border); margin-bottom: 8px; position: relative;
  overflow: hidden;
}
.skeleton-card::after {
  content: ''; position: absolute; inset: 0;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,.04), transparent);
  animation: skeleton-sweep 1.4s ease-in-out infinite;
}
@keyframes skeleton-sweep {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}

/* 다단계 스텝퍼 (규제동향 6단계 / 보고서 FX5260 4단계 / 문서분석 3단계) */
.step-list {
  display: flex; align-items: center; flex-wrap: wrap; gap: 0;
  padding: 12px 0; margin-bottom: 4px;
}
.step-item {
  display: flex; align-items: center; gap: 6px;
  font-size: 11.5px; color: var(--text-4); white-space: nowrap;
  padding: 4px 0;
}
.step-item .step-dot {
  width: 18px; height: 18px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 10px; font-weight: 700;
  border: 1.5px solid var(--border-strong); color: var(--text-4);
}
.step-item.done .step-dot {
  background: var(--accent); border-color: var(--accent); color: #fff;
}
.step-item.active .step-dot {
  border-color: var(--accent); color: var(--accent);
  animation: pulse 1.4s ease-in-out infinite;
}
.step-item.done span.step-label,
.step-item.active span.step-label { color: var(--text); }
.step-connector {
  width: 18px; height: 1.5px; background: var(--border-strong);
  margin: 0 4px; flex-shrink: 0;
}
.step-connector.done { background: var(--accent); }

/* 실행 전 필수 항목 체크리스트 */
.req-checklist {
  display: flex; flex-direction: column; gap: 6px;
  padding: 10px 12px; background: var(--bg-elev); border: 1px solid var(--border);
  border-radius: var(--radius); margin-bottom: 10px;
}
.req-item { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--text-3); }
.req-item .material-symbols-outlined { font-size: 15px; flex-shrink: 0; }
.req-item.ok { color: var(--text-2); }
.req-item.ok .material-symbols-outlined { color: var(--success); }
.req-item.missing .material-symbols-outlined { color: var(--text-4); }

/* 세그먼트 컨트롤 (붙은 두 버튼 — 모드 토글) */
.segmented { display: inline-flex; border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }
.segmented > .q-btn { border-radius: 0 !important; }

/* 결과/답변 공용 액션(복사·다운로드·재실행·원문이동) */
.result-actions { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
.result-action-btn {
  display: flex; align-items: center; gap: 4px;
  background: transparent !important; border: 1px solid var(--border) !important;
  color: var(--text-3); cursor: pointer; font-size: 11.5px; font-weight: 500;
  padding: 4px 10px; border-radius: var(--radius); box-shadow: none !important;
}
.result-action-btn:hover { color: var(--text); border-color: var(--border-strong) !important; }
.result-action-btn .material-symbols-outlined { font-size: 14px; margin-right: 0; }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important;
    scroll-behavior: auto !important;
  }
}
"""


def inject_global_css():
    """Noto Sans KR/Space Grotesk + Material Symbols + 다크 디자인 토큰을 주입합니다.

    Quasar 의 CSS가 head 끝쪽에 로드되므로, 우리 스타일이 cascade 에서 이기도록
    head 와 body 양쪽에 모두 주입합니다. (body 끝에 들어간 <style>이 가장
    마지막에 적용됨.)

    구 버전(v27)의 사이드바 전용 "JS paint enforcer"는 상단 탭바 전환과 함께
    제거했습니다 — 정적 ui.html() 블록 + 이벤트 위임 패턴은 사이드바 때와
    동일하게 유지되므로 Quasar/Vue의 동적 wrapper가 nav 안에 끼어들 일이
    구조적으로 없습니다. 잔상이 재발하면 원인은 다른 곳(nav 밖 컴포넌트)일
    가능성이 높습니다.
    """
    print("\n[ui_styles] Dark Design System (design-full-change) loaded "
          "(top nav, btn-primary-mono = sky-blue gradient, btn-mono = dark card)\n")

    ui.add_head_html(
        '<link rel="stylesheet" href="/static/fonts/pretendard-local.css">'
        '<link rel="stylesheet" href="/static/fonts/material-symbols-local.css">'
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700'
        '&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">'
    )
    # head 에 1차 주입
    ui.add_head_html(
        '<meta name="ipm-design-version" content="dark-v1">'
        f'<style id="ipm-global-styles-dark-v1">{_GLOBAL_CSS}</style>'
    )
    try:
        ui.add_body_html(
            f'<style id="ipm-global-styles-dark-v1-late">{_GLOBAL_CSS}</style>'
        )
    except AttributeError:
        ui.add_head_html(
            f'<style id="ipm-global-styles-dark-v1-late">{_GLOBAL_CSS}</style>'
        )


# ─────────────────────────────────────────────────────────────────────────
# ux/screens 공통 컴포넌트 헬퍼 (A~D 전 패널 재사용)
# ─────────────────────────────────────────────────────────────────────────
def progress_block_html(text: str, *, start_ts: float | None = None,
                         cancel_id: str | None = None) -> str:
    """스피너 + 진행바 + 실시간 경과시간 카운터.

    start_ts: time.time() epoch 초 — 같은 작업의 재렌더(.content 재할당) 사이에도
    경과가 끊기지 않도록, 작업 시작 시 한 번 얻은 값을 매 호출에 그대로 전달할 것.
    """
    import time as _time
    ts = start_ts if start_ts is not None else _time.time()
    cancel_html = (
        f'<button class="progress-cancel-btn" data-cancel-id="{_html.escape(cancel_id)}" '
        'type="button" aria-label="작업 취소">'
        '<span class="material-symbols-outlined">close</span>취소</button>'
    ) if cancel_id else ''
    return (
        '<div class="progress-block">'
        '<span class="material-symbols-outlined spin">progress_activity</span>'
        '<div class="progress-block-body">'
        f'<div class="progress-block-label"><span>{_html.escape(text)}</span>'
        f'<span class="progress-block-elapsed" data-elapsed-since="{ts}">0초 경과</span></div>'
        '<div class="progress-bar-track"><div class="progress-bar-fill"></div></div>'
        '</div>'
        f'{cancel_html}'
        '</div>'
    )


def elapsed_ticker_script() -> str:
    """[data-elapsed-since] 를 가진 모든 요소의 경과시간을 1초마다 갱신하는 스크립트.
    페이지당 한 번만 add_body_html 로 주입하면 됨 (여러 번 주입해도 안전 — setInterval 중복은
    무해하지만 굳이 여러 번 넣지 않도록 호출부에서 주의)."""
    return '''
<script>
(function(){
  function tick(){
    document.querySelectorAll('[data-elapsed-since]').forEach(function(el){
      const start = Number(el.getAttribute('data-elapsed-since'));
      if (!start) return;
      const sec = Math.max(0, Math.floor(Date.now() / 1000 - start));
      el.textContent = sec + '초 경과';
    });
  }
  setInterval(tick, 1000);
  tick();
})();
</script>
'''


def step_list_html(steps: list[str], current_index: int, failed: bool = False) -> str:
    """다단계 진행 스텝퍼. steps 이전 항목=완료, current_index=진행중, 이후=대기.

    current_index 가 len(steps) 이상이면 전 단계 완료로 표시.
    failed=True 면 current_index 단계를 오류 색상으로 표시하지 않고(토큰 제약상
    새 색상 추가 금지) 텍스트로만 실패를 표기하도록 호출부에서 별도 처리할 것.
    """
    parts = []
    for i, label in enumerate(steps):
        if i < current_index:
            cls, dot = 'done', '<span class="material-symbols-outlined" style="font-size:12px;">check</span>'
        elif i == current_index:
            cls, dot = 'active', str(i + 1)
        else:
            cls, dot = 'pending', str(i + 1)
        parts.append(
            f'<div class="step-item {cls}"><span class="step-dot">{dot}</span>'
            f'<span class="step-label">{_html.escape(label)}</span></div>'
        )
        if i < len(steps) - 1:
            conn_cls = 'done' if i < current_index else ''
            parts.append(f'<div class="step-connector {conn_cls}"></div>')
    return f'<div class="step-list">{"".join(parts)}</div>'


def req_checklist_html(items: list[tuple[str, bool]]) -> str:
    """실행 전 필수 항목 체크리스트. items: [(라벨, 충족여부), ...]"""
    rows = []
    for label, ok in items:
        cls = 'ok' if ok else 'missing'
        icon = 'check_circle' if ok else 'radio_button_unchecked'
        rows.append(
            f'<div class="req-item {cls}"><span class="material-symbols-outlined">{icon}</span>'
            f'<span>{_html.escape(label)}</span></div>'
        )
    return f'<div class="req-checklist">{"".join(rows)}</div>'


def result_actions_html(actions: list[tuple[str, str, str]]) -> str:
    """결과/답변 공용 액션 바. actions: [(action-id, 아이콘, 라벨), ...]
    각 버튼은 data-action="<action-id>" 로 렌더링되어 호출부에서 이벤트 위임으로 처리."""
    btns = ''.join(
        f'<button class="result-action-btn" data-action="{_html.escape(aid)}" type="button">'
        f'<span class="material-symbols-outlined">{icon}</span>{_html.escape(label)}</button>'
        for aid, icon, label in actions
    )
    return f'<div class="result-actions">{btns}</div>'
