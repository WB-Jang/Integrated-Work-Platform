"""
클라이언트(브라우저 연결) 생명주기에 결속된 ui.timer 래퍼.

배경 — ui.timer 는 페이지 element 트리에 속하기 때문에:
  1) 탭 닫기/새로고침 후 클라이언트가 삭제되면 타이머가 다음 틱에서
     'The parent slot of the element has been deleted.' RuntimeError
     트레이스백을 로그에 남기고,
  2) ui.run(reconnect_timeout=86400) 설정상 접속이 끊긴 '유령 클라이언트'가
     최대 24시간 유지되는 동안 그 페이지의 타이머가 계속 폴링하며,
  3) 웹소켓을 한 번도 연결하지 않는 접속(봇·헬스체크의 단순 GET)도 페이지
     빌드 시 타이머를 만들었다가 prune 시점에 같은 트레이스백을 남긴다.

해결 — 타이머를 connect 시점에 생성하고 disconnect 시 즉시 cancel,
재연결 시 재생성한다. 웹소켓이 연결되지 않는 접속은 타이머를 아예 만들지 않는다.
"""
from nicegui import ui

from logger import get_logger

log = get_logger("timer_utils")


class ClientBoundTimer:
    """클라이언트 연결 중에만 동작하는 ui.timer.

    사용법은 ui.timer 와 동일하게 생성하고, 영구 중지는 .cancel().

    - 생성 시점에 웹소켓이 이미 연결돼 있으면 즉시 시작 (버튼 클릭 핸들러 등)
    - 아직 연결 전이면(페이지 빌드 중) connect 이벤트에서 시작
    - disconnect 시 즉시 cancel → 고아 타이머 트레이스백·유령 폴링 방지
    - reconnect_timeout 내 재연결 시 자동 재생성
    - cancel() 호출 후에는 재연결돼도 다시 시작하지 않음
    """

    def __init__(self, interval: float, callback, *, host=None):
        self._interval = interval
        self._callback = callback
        self._timer = None
        self._dead = False

        # 재생성 시 슬롯 컨텍스트로 쓸 호스트 element (기본: 생성 시점의 부모)
        if host is None:
            try:
                from nicegui import context
                host = context.slot.parent
            except Exception:
                host = None
        self._host = host

        client = None
        try:
            from nicegui import context
            client = context.client
        except Exception:
            pass

        if client is None:
            # 클라이언트 컨텍스트 밖 — 기존 동작대로 즉시 시작
            self._start()
            return

        try:
            client.on_connect(lambda *_: self._start())
            client.on_disconnect(lambda *_: self._pause())
            if getattr(client, 'has_socket_connection', False):
                self._start()
        except Exception as e:
            log.debug("클라이언트 생명주기 연결 실패 — 즉시 시작으로 폴백: %s", e)
            self._start()

    def _start(self) -> None:
        if self._dead or self._timer is not None:
            return
        try:
            if self._host is not None:
                with self._host:
                    self._timer = ui.timer(self._interval, self._callback)
            else:
                self._timer = ui.timer(self._interval, self._callback)
        except Exception as e:
            log.debug("타이머 시작 실패: %s", e)

    def _pause(self) -> None:
        t, self._timer = self._timer, None
        if t is not None:
            try:
                t.cancel()
            except Exception:
                pass

    def cancel(self) -> None:
        """영구 중지 — 이후 재연결돼도 재시작하지 않는다."""
        self._dead = True
        self._pause()
