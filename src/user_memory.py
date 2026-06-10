"""
유저(IP)별 인메모리 저장소.

사내망은 유저별 고정 IP 를 사용하므로 접속 IP 를 유저 식별자로 삼는다.
세션(브라우저 연결)별이 아니라 유저별로 대화 메모리를 유지하기 위한 모듈로,
브라우저를 닫았다 다시 접속해도 같은 IP 면 동일한 저장소를 돌려받는다.

저장 항목 예:
  - 'home_history'  : 홈 채팅 대화 히스토리 (list[dict])
  - 'qa_chat'       : 문서 질의응답 대화 히스토리 (list[dict])
  - 'legal_agent'   : LegalSearchAgent 인스턴스 (대화 메모리 포함)

주의: 프로세스 재시작(HF Space 재배포 등) 시 초기화된다.
"""
import threading

_lock = threading.Lock()
_stores: dict[str, dict] = {}


def _norm_key(user_key: str) -> str:
    return (user_key or "").strip() or "anon"


def get_user_data(user_key: str) -> dict:
    """유저 키(접속 IP)에 해당하는 영속 dict 를 반환한다 (없으면 생성).

    반환된 dict 는 동일 키로 재호출 시 같은 객체이므로, 리스트 등을
    setdefault 로 꺼내 in-place 로 수정하면 유저별 메모리가 유지된다.
    """
    key = _norm_key(user_key)
    with _lock:
        return _stores.setdefault(key, {})


def all_user_data() -> list[dict]:
    """모든 유저 저장소 목록 (DB 리로드 등 일괄 작업용)."""
    with _lock:
        return list(_stores.values())


def clear_user_data(user_key: str) -> None:
    with _lock:
        _stores.pop(_norm_key(user_key), None)
