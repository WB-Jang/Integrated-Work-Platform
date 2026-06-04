"""
Integrated Work Platform — Monochrome UX Design System

NiceGUI 전용 글로벌 CSS 주입 모듈.
검정·회색·흰색 기반 모노크롬 팔레트, Pretendard + Material Symbols,
풀-블리드 채팅 / 분할 레이아웃을 위한 클래스들을 정의합니다.

사용법:
    from ui_styles import inject_global_css
    inject_global_css()   # @ui.page 핸들러 안에서 호출
"""

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
  --q-primary: #171717 !important;
  --q-secondary: #404040 !important;
  --q-accent: #0a0a0a !important;
  --q-dark: #0a0a0a !important;
  --q-dark-page: #ffffff !important;
  --q-positive: #166534 !important;
  --q-negative: #b91c1c !important;
  --q-info: #404040 !important;
  --q-warning: #92400e !important;
}

/* ─────────────────────────────────────────────────────────
   Design tokens (light)
   ───────────────────────────────────────────────────────── */
:root {
  --bg: #ffffff;
  --bg-elev: #fafaf9;
  --bg-sunken: #f5f5f4;
  --border: #e7e5e4;
  --border-strong: #d6d3d1;
  --text: #0a0a0a;
  --text-2: #404040;
  --text-3: #737373;
  --text-4: #a3a3a3;
  --accent: #171717;
  --accent-hover: #000000;
  --shadow-sm: 0 1px 2px rgba(0,0,0,.04);
  --shadow-md: 0 1px 3px rgba(0,0,0,.06), 0 1px 2px rgba(0,0,0,.04);
  --radius-sm: 6px;
  --radius: 8px;
  --radius-lg: 12px;
  --radius-full: 999px;
  --sidebar-w: 248px;
  --font-sans: "Pretendard", -apple-system, BlinkMacSystemFont, "Segoe UI",
    "Noto Sans KR", sans-serif;
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

/* NiceGUI/Quasar 기본 폰트 오버라이드 */
body, .q-field, .q-btn, input, textarea, select, button {
  font-family: var(--font-sans) !important;
}

.material-symbols-outlined {
  font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 20;
}

/* ─────────────────────────────────────────────────────────
   Sidebar  (dark charcoal)
   ───────────────────────────────────────────────────────── */
:root {
  --sidebar-bg:        #22252a;
  --sidebar-border:    rgba(255,255,255,.08);
  --sidebar-text:      rgba(255,255,255,.72);
  --sidebar-text-dim:  rgba(255,255,255,.38);
  --sidebar-hover:     rgba(255,255,255,.07);
  --sidebar-active:    rgba(255,255,255,.13);
  --sidebar-logo-bg:   #ffffff;
  --sidebar-logo-fg:   #22252a;
}

.sidebar {
  position: fixed; top: 0; left: 0;
  width: var(--sidebar-w);
  height: 100vh;
  background: var(--sidebar-bg);
  border-right: 1px solid var(--sidebar-border);
  display: flex; flex-direction: column;
  padding: 16px 12px;
  overflow-y: auto;
  z-index: 10;
}

/* ─────────────────────────────────────────────────────────
   사이드바 — hover/click 시 보이던 박스 잔상 차단

   원인 분석 (사용자 보고: hover/click 시에만 나타남):
   1. -webkit-tap-highlight-color 브라우저 기본값(반투명 검정)이
      어두운 사이드바 위에서 옅은 회색 박스로 보임
   2. transition 으로 인한 GPU 합성 paint layer artifact
   3. Quasar의 q-focus-helper / q-ripple overlay

   해결: 사이드바 내부 모든 자손의 hover/focus/active 상태에서
   background / box-shadow / outline / tap-highlight 를 모두 제거.
   ───────────────────────────────────────────────────────── */

/* 1) Tap highlight (모바일 + 일부 데스크톱 브라우저) 차단 */
html body .sidebar,
html body .sidebar * {
  -webkit-tap-highlight-color: transparent !important;
  -webkit-touch-callout: none !important;
}

/* 2) 모든 hover/focus/active/focus-within 상태에서 시각 효과 차단 */
html body .sidebar *:hover,
html body .sidebar *:focus,
html body .sidebar *:focus-visible,
html body .sidebar *:focus-within,
html body .sidebar *:active {
  background-color: transparent !important;
  background-image: none !important;
  box-shadow: none !important;
  outline: 0 !important;
  outline-color: transparent !important;
}

/* 3) nav-item 의 모든 상태 — background 완전 차단, color 변경만 허용 */
html body .sidebar .nav-item,
html body .sidebar .nav-item:hover,
html body .sidebar .nav-item:focus,
html body .sidebar .nav-item:focus-visible,
html body .sidebar .nav-item:focus-within,
html body .sidebar .nav-item:active,
html body .sidebar .nav-item.active,
html body .sidebar .nav-item.expanded {
  background: transparent !important;
  background-color: transparent !important;
  background-image: none !important;
  box-shadow: none !important;
  outline: 0 !important;
  border: 0 !important;
}

/* 4) nav-item 안의 자식 요소도 모두 동일 처리 */
html body .sidebar .nav-item *,
html body .sidebar .nav-item *:hover,
html body .sidebar .nav-item *:focus,
html body .sidebar .nav-item *:active {
  background-color: transparent !important;
  background-image: none !important;
  box-shadow: none !important;
}

/* 5) Quasar overlay 완전 차단 */
html body .sidebar .q-focus-helper,
html body .sidebar .q-ripple,
html body .sidebar .q-hoverable__bg,
html body .sidebar .q-focus-helper:before,
html body .sidebar .q-focus-helper:after {
  display: none !important;
  background: transparent !important;
  opacity: 0 !important;
}

/* 6) 사이드바 모든 요소 transition 완전 제거 + outline/border 강제 0
       (진단 결과 hover 시 시각적 박스를 만들 수 있는 유일한 변화가
        color 변경 + transition 이었음. transition 으로 인한 GPU paint
        artifact를 차단하기 위해 transition을 완전히 끔.) */
html body .sidebar,
html body .sidebar *,
html body .sidebar ::before,
html body .sidebar ::after {
  transition: none !important;
  outline-width: 0 !important;
  outline-style: none !important;
  outline-color: transparent !important;
  border-width: 0 !important;
  box-shadow: none !important;
  filter: none !important;
  backdrop-filter: none !important;
  -webkit-filter: none !important;
}

/* active 상태의 좌측 인디케이터(::before)는 위 규칙으로 사라졌을 수 있으니
   indicator 전용 규칙으로 복원 (높은 specificity로 위 와일드카드 덮어쓰기) */
html body aside.sidebar .nav-item.active::before {
  content: "" !important;
  position: absolute !important;
  left: 0 !important;
  top: 50% !important;
  transform: translateY(-50%) !important;
  height: 18px !important;
  width: 2px !important;
  background: #ffffff !important;
  border-radius: 2px !important;
}
.sidebar-logo {
  display: flex; align-items: center; gap: 8px;
  padding: 4px 8px 16px;
  font-size: 13px; font-weight: 600;
  letter-spacing: -0.01em; color: #ffffff;
  min-width: 0;
}
.sidebar-logo .logo-mark {
  width: 22px; height: 22px; border-radius: 6px;
  background: var(--sidebar-logo-bg); color: var(--sidebar-logo-fg);
  display: grid; place-items: center;
  font-size: 11px; font-weight: 700; letter-spacing: -.02em;
  flex-shrink: 0;
}
.sidebar-logo .logo-text {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1; min-width: 0;
  font-size: 12.5px;
}
.beta-tag {
  display: inline-flex; align-items: center;
  padding: 2px 6px;
  font-size: 9.5px; font-weight: 600; letter-spacing: .04em;
  color: var(--sidebar-text-dim);
  background: rgba(255,255,255,.06);
  border: 1px solid var(--sidebar-border);
  border-radius: var(--radius-full);
  flex-shrink: 0;
}
.sidebar-divider {
  height: 1px; background: var(--sidebar-border); margin: 8px 4px;
}
.nav-group-label {
  font-size: 10.5px; font-weight: 600;
  color: var(--sidebar-text-dim);
  padding: 12px 10px 6px;
  letter-spacing: .06em;
  text-transform: uppercase;
}
/* ─────────────────────────────────────────────────────────
   Sidebar — nav items
   (active 상태도 사이드바 배경과 완전 동일한 톤을 유지하기 위해
    배경 오버레이 없이 글자 밝기 + 좌측 액센트 바로만 표시)
   ───────────────────────────────────────────────────────── */
html body .sidebar .nav-item {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 10px;
  border-radius: 0;
  background: transparent !important;
  color: var(--sidebar-text);
  font-size: 13px; font-weight: 500;
  cursor: pointer;
  position: relative;
  /* transition 제거 — GPU paint artifact 방지 */
  user-select: none;
}
/* hover 시 색 변경 제거 — 진단 결과 이 변화가 박스 잔상의 원인.
   클릭한 항목(.active)만 흰색으로 강조됨. cursor:pointer 가 시각적 affordance 제공. */
html body .sidebar .nav-item:hover {
  background: transparent !important;
  color: var(--sidebar-text) !important;
}
html body .sidebar .nav-item:hover .nav-icon {
  color: var(--sidebar-text) !important;
}
html body .sidebar .nav-item.active {
  background: transparent !important;
  color: #ffffff;
  font-weight: 600;
}
html body .sidebar .nav-item.active::before {
  content: "";
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  height: 18px;
  width: 2px;
  border-radius: 2px;
  background: #ffffff;
}
html body .sidebar .nav-item .nav-icon {
  font-size: 18px; line-height: 1; flex-shrink: 0;
  color: var(--sidebar-text);
  transition: color .12s;
  font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 20;
}
html body .sidebar .nav-item:hover .nav-icon,
html body .sidebar .nav-item.active .nav-icon {
  color: #ffffff;
}
html body .sidebar .nav-item.active .nav-icon {
  font-variation-settings: 'FILL' 1, 'wght' 500, 'GRAD' 0, 'opsz' 20;
}
html body .sidebar .nav-item .nav-label {
  flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
html body .sidebar .nav-item .nav-chev {
  font-size: 16px; color: var(--sidebar-text-dim);
  transition: transform .2s;
}
html body .sidebar .nav-item.expanded .nav-chev { transform: rotate(90deg); }
html body .sidebar .nav-sub {
  overflow: hidden; max-height: 0;
  transition: max-height .22s cubic-bezier(.4,0,.2,1);
}
html body .sidebar .nav-sub.open { max-height: 320px; }
html body .sidebar .nav-sub .nav-item { padding-left: 36px; font-size: 12.5px; }
html body .sidebar .nav-sub .nav-item .nav-icon { font-size: 15px; }

.sidebar-footer {
  margin-top: auto;
  padding-top: 14px;
  border-top: 1px solid var(--sidebar-border);
}
.sidebar-footer .footer-label {
  font-size: 11px; color: var(--sidebar-text-dim); padding: 0 4px 6px;
}
.model-select {
  width: 100%;
  appearance: none;
  background: rgba(255,255,255,.08);
  border: 1px solid var(--sidebar-border);
  border-radius: var(--radius);
  padding: 8px 28px 8px 10px;
  font-size: 12.5px;
  color: #ffffff;
  cursor: pointer;
  font-family: inherit;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23aaaaaa' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>");
  background-repeat: no-repeat;
  background-position: right 10px center;
}
.model-select:hover { border-color: rgba(255,255,255,.2); }

/* ui.select (Quasar) — 다크 사이드바 풋터용 (모델 선택)
   사이드바 안에서만 적용되도록 .sidebar 로 스코프하여
   본문 다른 select 와 격리. */
.sidebar .model-select-q.q-field { font-family: var(--font-sans) !important; }

.sidebar .model-select-q .q-field__control,
.sidebar .model-select-q .q-field__control * {
  background-color: transparent !important;
  background-image: none !important;
}
.sidebar .model-select-q .q-field__control {
  background-color: rgba(255,255,255,.06) !important;
  border: 1px solid rgba(255,255,255,.12) !important;
  border-radius: var(--radius) !important;
  min-height: 36px !important;
  padding: 0 12px !important;
  box-shadow: none !important;
  transition: border-color .12s, background-color .12s !important;
}
.sidebar .model-select-q .q-field__control::before,
.sidebar .model-select-q .q-field__control::after { display: none !important; }
.sidebar .model-select-q .q-field__control:hover {
  background-color: rgba(255,255,255,.10) !important;
  border-color: rgba(255,255,255,.20) !important;
}
.sidebar .model-select-q.q-field--focused .q-field__control {
  background-color: rgba(255,255,255,.12) !important;
  border-color: rgba(255,255,255,.30) !important;
}

/* 선택된 값 텍스트 — 모든 가능한 셀렉터 강제 white */
.sidebar .model-select-q,
.sidebar .model-select-q .q-field__native,
.sidebar .model-select-q .q-field__native *,
.sidebar .model-select-q .q-field__input,
.sidebar .model-select-q .q-select__input-value,
.sidebar .model-select-q .q-select__display-value,
.sidebar .model-select-q .q-field__control-container,
.sidebar .model-select-q .q-field__control-container *,
.sidebar .model-select-q [class*="q-field__"],
.sidebar .model-select-q [class*="q-select__"] {
  color: #ffffff !important;
  -webkit-text-fill-color: #ffffff !important;
  font-size: 12.5px !important;
  font-weight: 500 !important;
}
.sidebar .model-select-q .q-field__native {
  min-height: 34px !important;
  padding: 0 !important;
}

/* floating label 비활성화 (label 없이 사용) */
.sidebar .model-select-q .q-field__label { display: none !important; }

/* dropdown arrow */
.sidebar .model-select-q .q-field__append,
.sidebar .model-select-q .q-field__append * { color: rgba(255,255,255,.6) !important; }

/* ───── 드롭다운 메뉴 (popup) — 다크 톤으로 통일 ───── */
.q-menu.model-select-menu {
  background: #2a2d33 !important;
  border: 1px solid rgba(255,255,255,.12) !important;
  border-radius: var(--radius) !important;
  box-shadow: 0 12px 28px rgba(0,0,0,.4), 0 2px 6px rgba(0,0,0,.3) !important;
  padding: 4px !important;
  margin-top: 4px !important;
}
.q-menu.model-select-menu .q-item {
  color: rgba(255,255,255,.85) !important;
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
  background: rgba(255,255,255,.10) !important;
  color: #ffffff !important;
}
.q-menu.model-select-menu .q-item__label { color: inherit !important; }

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
  background: var(--bg) !important;
}

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
  background: var(--text);
  color: #fff;
  border-color: var(--text);
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
.server-row .dot.up { background: #16a34a; }
.server-row .dot.down { background: #dc2626; }

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
  width: 280px;
  min-width: 280px;
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
  grid-template-columns: 230px 1fr 1fr;
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

/* ─────────────────────────────────────────────────────────
   Main area & panels
   ───────────────────────────────────────────────────────── */
.main-area {
  margin-left: var(--sidebar-w);
  height: 100vh;
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

/* ── GLOBAL DEFAULT (모든 q-btn) — 흰 버튼 ── */
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
  background: #ffffff !important;
  background-color: #ffffff !important;
  background-image: none !important;
  color: #0a0a0a !important;
  border: 1px solid #e7e5e4 !important;
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
  background: #fafaf9 !important;
  background-color: #fafaf9 !important;
  border-color: #d6d3d1 !important;
  color: #0a0a0a !important;
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

/* ── PRIMARY MONO — 검정 배경 + 흰 글자 ── */
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
  background: #0a0a0a !important;
  background-color: #0a0a0a !important;
  background-image: none !important;
  color: #ffffff !important;
  border: 1px solid #0a0a0a !important;
  min-height: 34px !important;
  padding: 0 14px !important;
  font-size: 13px !important;
}
html body .q-btn.btn-primary-mono:hover,
html body .q-btn.q-btn--standard.btn-primary-mono:hover,
html body .q-btn.q-btn--standard.q-btn--actionable.btn-primary-mono:hover,
html body .q-btn.q-btn--standard.q-btn--actionable.btn-primary-mono.bg-primary:hover {
  background: #000000 !important;
  background-color: #000000 !important;
  border-color: #000000 !important;
  color: #ffffff !important;
}
html body .q-btn.btn-primary-mono .q-btn__content,
html body .q-btn.btn-primary-mono .q-btn__content *,
html body .q-btn.q-btn--standard.btn-primary-mono .q-btn__content {
  color: #ffffff !important;
}

/* ── SECONDARY MONO — 흰 배경 + 검정 글자 + 회색 보더 ── */
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
  background: #ffffff !important;
  background-color: #ffffff !important;
  background-image: none !important;
  color: #0a0a0a !important;
  border: 1px solid #e7e5e4 !important;
  min-height: 34px !important;
  padding: 0 14px !important;
  font-size: 13px !important;
}
html body .q-btn.btn-mono:hover,
html body .q-btn.q-btn--standard.btn-mono:hover,
html body .q-btn.q-btn--standard.q-btn--actionable.btn-mono:hover,
html body .q-btn.q-btn--standard.q-btn--actionable.btn-mono.bg-primary:hover {
  background: #fafaf9 !important;
  background-color: #fafaf9 !important;
  border-color: #d6d3d1 !important;
  color: #0a0a0a !important;
}
html body .q-btn.btn-mono .q-btn__content,
html body .q-btn.btn-mono .q-btn__content *,
html body .q-btn.q-btn--standard.btn-mono .q-btn__content {
  color: #0a0a0a !important;
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
  background: #0a0a0a !important;
  background-color: #0a0a0a !important;
  color: #ffffff !important;
  border-color: #0a0a0a !important;
}
html body .q-btn.btn-mono.is-active .q-btn__content,
html body .q-btn.btn-mono.is-active .q-btn__content *,
html body .q-btn.btn-mono.active .q-btn__content,
html body .q-btn.btn-mono.active .q-btn__content * {
  color: #ffffff !important;
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
.status-chip.ok .dot { background: #16a34a; }
.status-chip.warn .dot { background: #d97706; }
.status-chip.err .dot { background: #dc2626; }
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
"""


# ─────────────────────────────────────────────────────────────────────────────
# 사이드바 잔상 제거 — JS 런타임 강제 페인터
# ─────────────────────────────────────────────────────────────────────────────
# 배경:
#   CSS specificity로는 NiceGUI 3.x / Quasar / Vue가 동적으로 추가하는
#   wrapper 요소나 inline style이 cascade에서 이기는 경우가 발생.
#   .nav-item 주위에 미세한 박스 잔상이 남는 문제가 어떤 CSS 조합으로도
#   완전 해결되지 않아 JS 런타임에서 inline `style + !important` 로 강제.
#
# 동작:
#   1) aside.sidebar 의 모든 자손에 대해 background-color를 #22252a 로,
#      box-shadow / border / outline 을 모두 제거.
#   2) 예외 셀렉터( .logo-mark / .beta-tag / Quasar 입력·드롭다운 내부 ) 는
#      자체 디자인 유지.
#   3) MutationObserver 로 NiceGUI가 나중에 mount 하는 자식까지 즉시 처리.
#   4) 안전망으로 1초마다 한 번 더 전체 페인트 (성능 영향 미미, 멱등).
#
# 이 방식은 CSS specificity 와 무관하게 inline style + !important 로
# 박히기 때문에 외부 CSS가 어떤 색을 시도하든 항상 이깁니다.
_SIDEBAR_PAINT_JS = r"""
(function() {
  var BG = '#22252a';
  function isExcluded(el) {
    if (!el || el.nodeType !== 1 || !el.classList) return false;
    if (el.classList.contains('logo-mark')) return true;
    if (el.classList.contains('beta-tag')) return true;
    if (el.classList.contains('material-symbols-outlined')) return true;
    if (el.tagName === 'I' || el.tagName === 'SPAN' && el.classList.contains('material-symbols-outlined')) return true;
    if (typeof el.closest === 'function') {
      if (el.closest('.q-field__control')) return true;
      if (el.closest('.q-menu')) return true;
      if (el.closest('.q-select__dropdown-icon')) return true;
      if (el.closest('.model-select-q')) return true;
    }
    return false;
  }
  function paint(el) {
    if (!el || el.nodeType !== 1 || !el.style) return;
    if (isExcluded(el)) return;
    el.style.setProperty('background-color', BG, 'important');
    el.style.setProperty('background-image', 'none', 'important');
    el.style.setProperty('box-shadow', 'none', 'important');
    el.style.setProperty('border-color', 'transparent', 'important');
    el.style.setProperty('outline-color', 'transparent', 'important');
  }
  function paintAll() {
    var sb = document.querySelector('aside.sidebar');
    if (!sb) return false;
    paint(sb);
    var nodes = sb.querySelectorAll('*');
    for (var i = 0; i < nodes.length; i++) paint(nodes[i]);
    return true;
  }
  var painting = false;
  function safePaintAll() {
    if (painting) return;
    painting = true;
    try { paintAll(); }
    finally { setTimeout(function(){ painting = false; }, 0); }
  }
  function start() {
    if (!paintAll()) { setTimeout(start, 100); return; }
    var sb = document.querySelector('aside.sidebar');
    try {
      // childList + subtree: 새 노드 추가 감지
      // attributes(style/class): 동적 inline style 변경 감지 (hover/click 시 끼어드는 효과)
      var mo = new MutationObserver(function(){ safePaintAll(); });
      mo.observe(sb, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['style', 'class']
      });
    } catch (e) { console.warn('[IPM] MutationObserver setup failed:', e); }

    // hover/click 시점에도 즉시 강제 재페인트 (잔상 차단의 핵심)
    ['mouseover', 'mouseout', 'mousedown', 'mouseup', 'focusin', 'focusout', 'click']
      .forEach(function(ev){
        sb.addEventListener(ev, function(){
          // 다음 프레임에 페인트 — 브라우저가 hover 효과를 적용한 직후 덮어씀
          requestAnimationFrame(safePaintAll);
        }, true);
      });

    // 안전망: 1초 주기 멱등 페인트
    setInterval(safePaintAll, 1000);
    console.info('[IPM] sidebar paint enforcer started — bg locked to', BG);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
"""


def inject_global_css():
    """Pretendard + Material Symbols + 모노크롬 디자인 토큰을 주입합니다.

    Quasar 의 CSS가 head 끝쪽에 로드되므로, 우리 스타일이 cascade 에서 이기도록
    head 와 body 양쪽에 모두 주입합니다. (body 끝에 들어간 <style>이 가장
    마지막에 적용됨.)
    """
    # 터미널에 버전 마커 출력 — 새 ui_styles 가 로드됐는지 즉시 확인 가능
    print("\n[ui_styles] Monochrome Design System v3.0 loaded "
          "(btn-mono = WHITE bg + black text, btn-primary-mono = BLACK bg + white text)\n")

    ui.add_head_html(
        '<link rel="stylesheet" href="/static/fonts/pretendard-local.css">'
        '<link rel="stylesheet" href="/static/fonts/material-symbols-local.css">'
    )
    # head 에 1차 주입
    ui.add_head_html(
        '<meta name="ipm-design-version" content="v3.0">'
        f'<style id="ipm-global-styles-v27">{_GLOBAL_CSS}</style>'
    )
    try:
        ui.add_body_html(
            f'<style id="ipm-global-styles-v27-late">{_GLOBAL_CSS}</style>'
            f'<script id="ipm-sidebar-paint">{_SIDEBAR_PAINT_JS}</script>'
            '<script>console.info("[IPM] Design System v3.0 — JS sidebar paint enforcer active");</script>'
        )
    except AttributeError:
        ui.add_head_html(
            f'<style id="ipm-global-styles-v27-late">{_GLOBAL_CSS}</style>'
            f'<script id="ipm-sidebar-paint">{_SIDEBAR_PAINT_JS}</script>'
        )
