"""
IWP 로컬 Outlook 브릿지 — 사용자 PC에서 실행되는 작은 localhost HTTP 서버.

배경:
  IWP는 중앙 서버에서 실행되고 사용자는 브라우저로 접속한다. 서버의 파이썬은
  원격 사용자 PC의 Outlook(COM)에 접근할 수 없다. 그래서 사용자 PC에서 이 브릿지를
  실행하면, 브라우저(사용자 PC에서 동작)가 127.0.0.1 로 이 브릿지를 호출해 **본인
  Outlook** 의 메일을 읽어 IWP 서버로 전달한다. LLM 분석은 IWP 서버에서 수행한다.

  [사용자 PC] 브라우저 ──fetch──▶ 127.0.0.1:8899 (이 브릿지) ──win32com──▶ 사용자 Outlook

동작 환경: Windows + MS Outlook 데스크톱 설치. pywin32 필요.
배포: 사용자 PC에 Python이 없으므로 PyInstaller 로 단일 .exe 빌드(build_bridge.bat 참조).

엔드포인트:
  GET  /health?token=...                    → {"ok":true,"mailbox":"me@bank.com","version":...}
  GET  /emails?start=&end=&sender=&recipient=&attachments=0|1&token=...
                                            → {"emails":[...]}   (outlook_ops.get_emails 스키마)
  POST /reply-draft   (JSON: entry_id, store_id, body, reply_all)
                                            → {"ok":true}        본인 Outlook에 회신 초안 창을 연다

보안(secure-by-default):
  - 127.0.0.1 에만 바인딩(외부 네트워크 비노출).
  - 토큰(IWP_BRIDGE_TOKEN, 헤더 X-IWP-Bridge-Token) **필수** — 미설정 시 데이터/액션 요청 거부.
  - CORS 오리진 허용목록(IWP_BRIDGE_ORIGIN) **필수** — 허용 오리진에만 응답을 노출해
    사용자가 방문한 악성 웹사이트의 브라우저 경유 메일 탈취를 차단. 미설정 시 거부.
  - Host 헤더를 루프백으로 검증(DNS 리바인딩 방지).
  두 환경변수는 배포 시 반드시 설정한다(예: IWP_BRIDGE_TOKEN=..., IWP_BRIDGE_ORIGIN=http://IWP주소).
"""
import os
import sys
import json
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# 같은 폴더의 자립형 Outlook 로직(win32com). ../src 에 의존하지 않는다
# (그래야 bridge 폴더만 받아 PyInstaller 로 빌드해도 모듈이 누락되지 않음).
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import outlook_ops

BRIDGE_VERSION = "1.2"
# 이 브릿지가 지원하는 엔드포인트(신/구 버전 판별용). /health 로 노출한다.
BRIDGE_CAPS = ["emails", "open-email", "reply-draft"]
HOST = "127.0.0.1"
PORT = int(os.environ.get("IWP_BRIDGE_PORT", "8899"))

# ── 보안 설정(secure-by-default) ─────────────────────────────────────────────
# 토큰: IWP 서버 config 의 outlook_bridge_token 과 동일해야 함. **미설정 시 모든
# 데이터/액션 요청을 거부**한다(오설정 방치 방지).
TOKEN = os.environ.get("IWP_BRIDGE_TOKEN", "").strip()
# 토큰 전달 헤더(URL 쿼리 ?token= 도 하위호환으로 허용).
TOKEN_HEADER = "X-IWP-Bridge-Token"
# CORS 허용 오리진(콤마 구분 다중). **기본값 없음** — 배포 시 IWP 접속 주소를
# IWP_BRIDGE_ORIGIN 환경변수로 지정해야 브라우저 요청이 허용된다(미설정 시 거부).
# 예: IWP_BRIDGE_ORIGIN=http://iwp.example.com  또는  http://10.20.30.40:8080


def _norm_origin(o: str) -> str:
    return (o or "").strip().rstrip("/").lower()


_ALLOWED_ORIGINS = {
    _norm_origin(o) for o in os.environ.get("IWP_BRIDGE_ORIGIN", "").split(",")
    if _norm_origin(o)
}
# DNS 리바인딩 방지를 위해 허용하는 Host 헤더의 호스트부.
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _log(msg: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ─── HTTP 핸들러 ──────────────────────────────────────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    server_version = f"IWPOutlookBridge/{BRIDGE_VERSION}"

    # 로그를 간결하게
    def log_message(self, fmt, *args):
        pass

    # ── 오리진/Host/토큰 판정 ────────────────────────────────────────────────
    def _origin(self) -> str:
        return _norm_origin(self.headers.get("Origin", ""))

    def _origin_allowed(self, origin: str) -> bool:
        return bool(origin) and origin in _ALLOWED_ORIGINS

    def _host_ok(self) -> bool:
        """DNS 리바인딩 방지 — Host 헤더의 호스트부가 루프백인지 확인."""
        host = (self.headers.get("Host", "") or "").strip().lower()
        if not host:
            return True  # Host 없는 저수준 클라이언트(예: 일부 도구)는 통과(토큰으로 통제)
        # IPv6 [::1]:port / host:port / host 모두 처리
        if host.startswith("["):
            hostname = host[1:host.find("]")] if "]" in host else host
        else:
            hostname = host.split(":", 1)[0]
        return hostname in _LOOPBACK_HOSTS

    def _token_ok(self) -> bool:
        """토큰 검증. TOKEN 미설정 시 항상 False(secure-by-default → 거부)."""
        if not TOKEN:
            return False
        got = (self.headers.get(TOKEN_HEADER, "") or "").strip()
        if not got:  # 헤더 없으면 URL 쿼리(?token=) 하위호환 확인
            qs = parse_qs(urlparse(self.path).query)
            got = (qs.get("token", [""])[0] or "").strip()
        return got == TOKEN

    def _guard(self) -> bool:
        """데이터/액션 요청 공통 보안 관문. 통과 시 True, 실패 시 오류 응답 후 False.

        순서: Host(리바인딩) → 오리진(브라우저 탈취) → 설정 존재 → 토큰.
        """
        if not self._host_ok():
            self._send_json({"error": "forbidden (host)"}, 403)
            return False
        origin = self._origin()
        # 브라우저 요청(Origin 존재)은 반드시 허용 오리진과 일치해야 함
        if origin and not self._origin_allowed(origin):
            self._send_json({"error": "forbidden (origin)"}, 403)
            return False
        # secure-by-default: 필수 환경변수 미설정 시 명확히 거부
        if not TOKEN:
            self._send_json(
                {"error": "브릿지 보안 미설정: IWP_BRIDGE_TOKEN 환경변수를 설정하세요."}, 503)
            return False
        if not _ALLOWED_ORIGINS:
            self._send_json(
                {"error": "브릿지 보안 미설정: IWP_BRIDGE_ORIGIN 환경변수를 설정하세요."}, 503)
            return False
        if not self._token_ok():
            self._send_json({"error": "unauthorized"}, 401)
            return False
        return True

    def _cors(self):
        # 허용된 오리진일 때만 ACAO/PNA 를 발급(브라우저 응답 읽기 차단이 기본).
        origin = self._origin()
        if self._origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", f"Content-Type, {TOKEN_HEADER}")
        self.send_header("Access-Control-Max-Age", "600")

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        # 프리플라이트: Host·오리진만 검증(토큰은 브라우저가 프리플라이트에 안 보냄).
        if not self._host_ok() or not self._origin_allowed(self._origin()):
            self.send_response(403)
            self._cors()
            self.end_headers()
            return
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = parse_qs(parsed.query)

        if path == "/health":
            if not self._guard():
                return
            try:
                mbox = outlook_ops.default_mailbox()
                return self._send_json({
                    "ok": True, "mailbox": mbox,
                    "version": BRIDGE_VERSION, "caps": BRIDGE_CAPS,
                })
            except Exception as e:
                return self._send_json({"ok": False, "error": f"Outlook 연결 실패: {e}"}, 500)

        if path == "/open-email":
            if not self._guard():
                return
            try:
                ok = outlook_ops.open_email(
                    qs.get("entry_id", [""])[0], qs.get("store_id", [""])[0])
                return self._send_json({"ok": bool(ok)})
            except Exception as e:
                _log(f"/open-email 오류: {e}")
                return self._send_json({"ok": False, "error": str(e)}, 500)

        if path == "/emails":
            if not self._guard():
                return
            try:
                start = _parse_date(qs.get("start", [""])[0])
                end = _parse_date(qs.get("end", [""])[0])
                if not (start and end):
                    return self._send_json({"error": "start/end(YYYY-MM-DD) 필요"}, 400)
                sender = qs.get("sender", [""])[0].strip()
                recipient = qs.get("recipient", [""])[0].strip()
                include_att = qs.get("attachments", ["0"])[0] in ("1", "true", "True")
                emails = outlook_ops.get_emails(start, end, sender, recipient, include_att)
                _log(f"/emails {start}~{end} sender='{sender}' → {len(emails)}건")
                return self._send_json({"emails": emails})
            except Exception as e:
                _log(f"/emails 오류: {e}")
                return self._send_json({"error": str(e)}, 500)

        return self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        if path == "/reply-draft":
            if not self._guard():
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
                data = json.loads(self.rfile.read(length) or b"{}")
                ok = outlook_ops.create_reply_draft(
                    data.get("entry_id", ""), data.get("store_id", ""),
                    data.get("body", ""), bool(data.get("reply_all", False)),
                )
                return self._send_json({"ok": bool(ok)})
            except Exception as e:
                _log(f"/reply-draft 오류: {e}")
                return self._send_json({"ok": False, "error": str(e)}, 500)
        return self._send_json({"error": "not found"}, 404)


def _parse_date(s: str):
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def main():
    _log(f"IWP Outlook 브릿지 v{BRIDGE_VERSION} 시작 — http://{HOST}:{PORT}")
    origins_disp = ", ".join(sorted(_ALLOWED_ORIGINS)) if _ALLOWED_ORIGINS else "(미설정)"
    _log(f"보안: 토큰 {'설정됨' if TOKEN else '미설정'} · 허용 오리진: {origins_disp}")
    if not TOKEN or not _ALLOWED_ORIGINS:
        _log("*** 경고: IWP_BRIDGE_TOKEN / IWP_BRIDGE_ORIGIN 미설정 시 모든 요청이 거부됩니다. ***")
        _log("***       배포 환경변수(예: set IWP_BRIDGE_TOKEN=... & set IWP_BRIDGE_ORIGIN=http://IWP주소)를 설정하세요. ***")
    try:
        mbox = outlook_ops.default_mailbox()
        _log(f"연결된 메일함: {mbox or '(확인 실패 — Outlook 실행 여부 확인)'}")
    except Exception as e:
        _log(f"Outlook 확인 실패: {e} (Outlook 실행 후 재시도)")
    httpd = ThreadingHTTPServer((HOST, PORT), _Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        _log("종료")
        httpd.shutdown()


if __name__ == "__main__":
    main()
