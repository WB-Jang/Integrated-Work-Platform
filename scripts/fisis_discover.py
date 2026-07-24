"""
FISIS OpenAPI 코드 확정용 discovery 스크립트.

서버(FSS_API_KEY 설정 + fss.or.kr 접근 가능)에서 1회 실행해:
  1) 은행 목록(financeCd)
  2) 통계표 목록(listNo) — '핵심경영지표' 계열 후보
  3) 특정 통계표의 계정 목록(account_cd)
  4) 한 은행·통계표의 실제 수치 응답(필드 구조 확인)
을 출력/저장한다. 결과를 보고 src/fisis_client.py 의
BANK_FINANCE_CD / INDICATOR_SOURCE 를 채운다.

사용:
    export FSS_API_KEY=발급받은키
    python scripts/fisis_discover.py                 # 은행·통계표 목록
    python scripts/fisis_discover.py --list SA030    # 해당 통계표의 계정 목록
    python scripts/fisis_discover.py --info 0010927 SA030 Q 202403 202412
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import fisis_client as fc  # noqa: E402


def _dump(title, rows, limit=60):
    print(f"\n===== {title} ({len(rows)}건) =====")
    for r in rows[:limit]:
        print(json.dumps(r, ensure_ascii=False))
    if len(rows) > limit:
        print(f"... (+{len(rows) - limit}건 생략)")


def main():
    if not fc.has_api_key():
        print("FSS_API_KEY 미설정. export FSS_API_KEY=... 후 재실행하세요.")
        return

    args = sys.argv[1:]
    if args and args[0] == "--list" and len(args) >= 2:
        _dump(f"통계표 {args[1]} 계정 목록", fc.account_list(args[1]))
        return
    if args and args[0] == "--info" and len(args) >= 6:
        _, finance_cd, list_no, term, start_mm, end_mm = args[:6]
        rows = fc.statistics_info(finance_cd, list_no, term, start_mm, end_mm)
        _dump(f"수치 응답 {finance_cd}/{list_no}", rows)
        print("\n※ 각 row의 필드명(base_month/account_cd/값 필드)을 확인해 "
              "fisis_client._row_* 파서와 INDICATOR_SOURCE 를 맞추세요.")
        return

    # 기본: 은행 목록 + 통계표 목록
    banks = fc.company_search()
    _dump("금융회사 목록 (financeCd 후보)", banks)
    stats = fc.statistics_list()
    _dump("통계표 목록 (listNo 후보 — '핵심경영지표'/'건전성'/'수익성' 검색)", stats)
    print("\n다음 단계: python scripts/fisis_discover.py --list <listNo> 로 계정코드 확인,")
    print("          python scripts/fisis_discover.py --info <financeCd> <listNo> Q <start> <end> 로 수치 확인")


if __name__ == "__main__":
    main()
