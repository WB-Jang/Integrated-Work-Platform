"""
빌드타임 FAISS 인덱스 생성 스크립트.

Docker 빌드 단계에서 한 번 실행되어 legal_db/*_store.json → *_idx.index 를
미리 생성하고 이미지에 굽는다. 이렇게 하면 런타임(컨테이너 기동)에서
인덱스를 재구축할 필요가 없어지고, 재시작 루프가 사라진다.

- 모델: 빌드 시 download_models.py 가 받아둔 /app/models/bge-m3 사용
- 멱등(idempotent): 이미 .index 가 있으면 건너뜀
- 인덱스가 하나도 안 만들어져도 빌드를 실패시키지 않음(앱은 런타임 재구축으로 폴백)
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "src"))

LEGAL_DB_DIR = os.path.join(BASE_DIR, "legal_db")


def main() -> int:
    if not os.path.isdir(LEGAL_DB_DIR):
        print(f"[build-index] legal_db 디렉터리 없음, 건너뜀: {LEGAL_DB_DIR}")
        return 0

    from legal_db_builder import rebuild_index_from_store

    stores = sorted(
        f for f in os.listdir(LEGAL_DB_DIR) if f.endswith("_store.json")
    )
    if not stores:
        print("[build-index] *_store.json 없음, 건너뜀")
        return 0

    print(f"[build-index] 대상 store {len(stores)}개 발견")
    built, skipped, failed = 0, 0, 0

    for store_fn in stores:
        law_name = store_fn[: -len("_store.json")]
        store_path = os.path.join(LEGAL_DB_DIR, store_fn)
        index_path = os.path.join(LEGAL_DB_DIR, f"{law_name}_idx.index")

        if os.path.exists(index_path):
            print(f"[build-index] SKIP (이미 존재): {law_name}")
            skipped += 1
            continue

        print(f"[build-index] 빌드 시작: {law_name}")
        try:
            ok = rebuild_index_from_store(store_path, index_path)
        except Exception as e:  # noqa: BLE001 — 빌드는 실패시키지 않음
            print(f"[build-index] 오류 ({law_name}): {e}")
            failed += 1
            continue

        if ok:
            print(f"[build-index] 완료: {index_path}")
            built += 1
        else:
            print(f"[build-index] 실패(폴백 대상): {law_name}")
            failed += 1

    print(f"[build-index] 요약 — 생성 {built}, 건너뜀 {skipped}, 실패 {failed}")
    # 일부 실패해도 이미지 빌드는 계속 진행(런타임 폴백 존재)
    return 0


if __name__ == "__main__":
    sys.exit(main())
