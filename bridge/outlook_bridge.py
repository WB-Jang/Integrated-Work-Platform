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

보안: 127.0.0.1 에만 바인딩(외부 비노출). 선택적 토큰(IWP_BRIDGE_TOKEN)으로
      로컬 다른 프로세스의 무단 호출을 차단할 수 있다.
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

BRIDGE_VERSION = "1.1"
# 이 브릿지가 지원하는 엔드포인트(신/구 버전 판별용). /health 로 노출한다.
BRIDGE_CAPS = ["emails", "open-email", "reply-draft"]
HOST = "127.0.0.1"
PORT = int(os.environ.get("IWP_BRIDGE_PORT", "8899"))
# 선택적 공유 토큰(설정 시 IWP 서버 config 의 outlook_bridge_token 과 일치해야 함)
TOKEN = os.environ.get("IWP_BRIDGE_TOKEN", "").strip()
# CORS 허용 오리진(기본 * — IWP가 http 사내망이라 안전). 특정 오리진으로 좁힐 수 있음.
ALLOW_ORIGIN = os.environ.get("IWP_BRIDGE_ORIGIN", "*").strip() or "*"


def _log(msg: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ─── HTTP 핸들러 ──────────────────────────────────────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    server_version = f"IWPOutlookBridge/{BRIDGE_VERSION}"

    # 로그를 간결하게
    def log_message(self, fmt, *args):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", ALLOW_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        # 사설망 접근(PNA) 프리플라이트 대응 (공개/사설 → 로컬 요청 허용)
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "600")

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_token(self, qs) -> bool:
        if not TOKEN:
            return True
        got = (qs.get("token", [""])[0] or "").strip()
        return got == TOKEN

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = parse_qs(parsed.query)

        if path == "/health":
            if not self._check_token(qs):
                return self._send_json({"ok": False, "error": "unauthorized"}, 401)
            try:
                mbox = outlook_ops.default_mailbox()
                return self._send_json({
                    "ok": True, "mailbox": mbox,
                    "version": BRIDGE_VERSION, "caps": BRIDGE_CAPS,
                })
            except Exception as e:
                return self._send_json({"ok": False, "error": f"Outlook 연결 실패: {e}"}, 500)

        if path == "/open-email":
            if not self._check_token(qs):
                return self._send_json({"ok": False, "error": "unauthorized"}, 401)
            try:
                ok = outlook_ops.open_email(
                    qs.get("entry_id", [""])[0], qs.get("store_id", [""])[0])
                return self._send_json({"ok": bool(ok)})
            except Exception as e:
                _log(f"/open-email 오류: {e}")
                return self._send_json({"ok": False, "error": str(e)}, 500)

        if path == "/emails":
            if not self._check_token(qs):
                return self._send_json({"error": "unauthorized"}, 401)
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
        qs = parse_qs(parsed.query)
        if path == "/reply-draft":
            if not self._check_token(qs):
                return self._send_json({"ok": False, "error": "unauthorized"}, 401)
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
    _log(f"토큰 인증: {'사용' if TOKEN else '미사용'} · CORS 오리진: {ALLOW_ORIGIN}")
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
