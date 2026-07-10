"""
보고서 작성 러너 모듈
각 보고서 스크립트의 설정 및 실행 로직을 관리합니다.

모든 보고서는 Reporting/ 하위의 최상위 ``generate_report(...)`` 를 in-process 로
호출하며, 각 함수는 ``{'ok': bool, 'log': str, 'outfile': path[, 'outfiles': list]}``
형태의 dict 를 반환한다. (FX5260 은 변동금리 대화형 처리 특성상 러너 내부에서
직접 처리한다.)
"""
import os
import sys
import uuid
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
REPORTING_DIR = (BASE_DIR / "Reporting").resolve()

# Reporting/ 를 sys.path 에 추가해 각 러너에서 `from <스크립트> import generate_report`
# 형태로 in-process 호출할 수 있게 한다. (실제 import 는 각 러너 함수 내부에서 지연 수행)
if str(REPORTING_DIR) not in sys.path:
    sys.path.insert(0, str(REPORTING_DIR))

REPORT_CONFIGS = {
    "bok_dlnq": {
        "name": "BOK 10일 연체 보고서",
        "description": "통합 raw + 양식(format)을 받아 '보고서1'/'보고서2' 시트를 채워 저장",
        "icon": "📋",
        "files": [
            {"key": "raw", "label": "통합 raw.xlsx (시트: bf_15/cur_15/cur_17)", "hint": "복호화 필수"},
            {"key": "format", "label": "양식 format.xlsx (보고서1/보고서2)", "hint": "복호화 필수"},
        ],
        "params": [
            {"key": "base_yymmdd", "label": "작성기준일 (yymmdd, 예: 260430)", "type": "str"},
            {"key": "mortgage_loan", "label": "주택담보대출 금액 (억원, 예: 1234.56)", "type": "float"},
        ],
        "runner": "bok_dlnq",
    },
    "fx5220_1st": {
        "name": "FX5220 보고서 (1차)",
        "description": "외화여신 FX5220 1차 - 신규 외화여신 현황 (Outlook 자료요청 메일 포함)",
        "icon": "💱",
        "files": [
            {"key": "raw", "label": "통합 raw.xlsx (시트: cur_raw/bf_rm_info)", "hint": "복호화 필수"},
        ],
        "params": [
            {"key": "dt", "label": "기준 날짜 (yyyymmdd, 예: 20260201)", "type": "str"},
        ],
        "runner": "fx5220_1st",
    },
    "fx5220_2nd": {
        "name": "FX5220 보고서 (2차)",
        "description": "외화여신 FX5220 2차 - RM 정보 추가 및 양식 '입력표' 피벗 기입",
        "icon": "💱",
        "files": [
            {"key": "raw", "label": "통합 raw.xlsx (cur_raw/bf_rm_info/cur_response)", "hint": "복호화 필수"},
            {"key": "format", "label": "양식 format.xlsx (입력표)", "hint": "복호화 필수"},
        ],
        "params": [
            {"key": "dt", "label": "기준 날짜 (yyyymmdd, 예: 20260201)", "type": "str"},
        ],
        "runner": "fx5220_2nd",
    },
    "fx5260": {
        "name": "FX5260 보고서",
        "description": "외화대출 상세 보고서 (변동금리 계좌 금리 입력 필요)",
        "icon": "💰",
        "files": [
            {"key": "sql_result", "label": "FX5260 쿼리 결과 CSV", "hint": "인코딩: euc-kr"},
            {"key": "crms", "label": "CRMS 외화대출 CSV", "hint": "인코딩: euc-kr"},
            {"key": "seq", "label": "외화대출 SEQ CSV", "hint": "인코딩: utf-8-sig"},
        ],
        "wizard": True,
        "params": [
            {"key": "base_yymm", "label": "기준년월", "type": "yymm", "format": "YYYYMM"},
            {"key": "writer_title", "label": "작성자 직책 (예: 팀장)", "type": "str"},
            {"key": "writer_name", "label": "작성자 성명", "type": "str"},
            {"key": "writer_phone", "label": "작성자 전화번호 (- 없이, 예: 0212345678)", "type": "str"},
            {
                "key": "var_rates_json",
                "label": "변동금리 계좌 금리 JSON (파일 업로드 후 자동 분석 - 없으면 비워두세요)",
                "type": "str",
                "optional": True,
                "hint": '예: {"계좌번호1": 3.5, "계좌번호2": 4.0}',
            },
        ],
        "outputs": ["FX5260_최종보고서.csv"],
        "runner": "fx5260",
    },
    "fss_dlnq": {
        "name": "FSS 연체 보고서",
        "description": "통합 raw + 양식(format)을 받아 '(붙임1) 요약'·'(붙임2) 업종별 현황' 기입",
        "icon": "📊",
        "files": [
            {"key": "raw", "label": "통합 raw.xlsx (dlnq_sts_dtl_1/2)", "hint": "복호화 필수"},
            {"key": "format", "label": "양식 format.xlsx (붙임1/붙임2)", "hint": "복호화 필수"},
        ],
        "params": [
            {"key": "yymmdd", "label": "기준 날짜 (yymmdd, 예: 260210)", "type": "str"},
        ],
        "runner": "fss_dlnq",
    },
    "corp_loan": {
        "name": "기업 여신 조사표",
        "description": "통합 raw + 양식(format)을 받아 FS00401/00402/00409/00410 시트 기입",
        "icon": "🏢",
        "files": [
            {"key": "raw", "label": "통합 raw.xlsx (fs_00401/409/410 + 원화대출금_FS00402)", "hint": "복호화 필수"},
            {"key": "format", "label": "양식 format.xlsx (FS00401~00410)", "hint": "복호화 필수"},
        ],
        "params": [
            {"key": "dt", "label": "기준년월", "type": "yymm", "format": "YYYYMM"},
        ],
        "runner": "corp_loan",
    },
    "bok_statistical": {
        "name": "BOK 통화금융통계 조사표",
        "description": "한국은행 통화금융통계 월여신 조사표 (그룹별 결과 CSV 저장)",
        "icon": "📈",
        "files": [
            {"key": "raw", "label": "통합 raw.xlsx (월여신 다중 시트)", "hint": "시트: 01_월여신_*"},
        ],
        "params": [
            {"key": "yyyymm", "label": "기준년월", "type": "yymm", "format": "YYYYMM"},
        ],
        "runner": "bok_statistical",
    },
    "local_rir": {
        "name": "Local RIR",
        "description": "내부 리스크 정보 보고서 - 결과 6종을 단일 integrated_result.xlsx 로 저장",
        "icon": "⚠️",
        "files": [
            {"key": "raw", "label": "통합 raw.xlsx (LRIR 다중 시트)", "hint": "복호화 필수"},
        ],
        "params": [
            {"key": "yyyymm", "label": "기준년월", "type": "yymm", "format": "YYYYMM"},
        ],
        "runner": "local_rir",
    },
    "crir": {
        "name": "CRIR 보고서",
        "description": "거래상대방 리스크 정보 보고서 (raw 엑셀 다중시트 → 양식 'new' 자동 기입)",
        "icon": "📋",
        "mode": "form_fill",
        "files": [
            {"key": "raw", "label": "CRIR raw_data.xlsx (다중 시트)", "hint": "시트: Sheet2 등"},
            {"key": "format", "label": "양식 format.xlsx (워크시트 'new')", "hint": "결과가 채워질 양식"},
        ],
        "params": [
            {"key": "base_ym", "label": "기준년월", "type": "yymm", "format": "YYYY-MM"},
            {"key": "dates", "label": "기간 라벨 4개 (쉼표, 예: Apr25,Jan26,Mar26,Apr26)", "type": "str"},
            {"key": "ea_purely",
             "label": "Early Alerts USDm 4개 (공백, 예: 100 200 300 400)",
             "type": "str", "optional": True, "hint": "CRC 전달값, 공백 구분 정수 4개"},
            {"key": "ea_non_purely",
             "label": "EA non-purely USDm 4개 (공백)",
             "type": "str", "optional": True, "hint": "CRC 전달값, 공백 구분 정수 4개"},
        ],
        "runner": "crir",
    },
    "risk_limit": {
        "name": "리스크 한도 모니터링",
        "description": "원시/KSIC/주채무그룹 CSV + Total EAD 로 EAD 배분 결과 CSV 저장",
        "icon": "🎯",
        "files": [
            {"key": "raw", "label": "원시 데이터 CSV", "hint": "인코딩: euc-kr"},
            {"key": "ksic", "label": "KSIC 코드 CSV", "hint": "인코딩: utf-8-sig"},
            {"key": "main_debt_group", "label": "주채무그룹 CSV", "hint": "인코딩: utf-8-sig"},
        ],
        "params": [
            {"key": "yymm", "label": "기준년월", "type": "yymm", "format": "YYMM"},
            {"key": "total_ead", "label": "Total EAD (예: 17687118)", "type": "float"},
        ],
        "runner": "risk_limit",
    },
    "b2419": {
        "name": "거액 신규 여신 보고서",
        "description": "거액 신규 여신 보고서(건당 50억 이상 신규분, Outlook 회신요청/전결권자 확인 메일 포함)",
        "icon": "🎯",
        "files": [
            {"key": "raw", "label": "통합 raw.xlsx (B2419result/report_seq)", "hint": "List + Seq"},
        ],
        "params": [
            {"key": "yyyymm", "label": "기준년월", "type": "yymm", "format": "YYYYMM"},
            {"key": "end_dt", "label": "기한 (예: 5/14(목))", "type": "str"},
        ],
        "runner": "b2419",
    },
}


def get_upload_dir(report_key: str) -> Path:
    upload_base = BASE_DIR / "uploads" / "reports"
    run_id = uuid.uuid4().hex[:8]
    d = upload_base / f"{report_key}_{run_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _unwrap(result: dict):
    """generate_report 반환 dict → (ok, log_text, output_file_paths) 로 변환.

    반환 dict 은 항상 'ok'/'log' 를 가지며, 'outfiles'(list) 또는 'outfile'(단일)로
    산출물을 전달한다. log 가 예외 객체 등 비문자열이어도 안전하게 문자열화한다.
    """
    ok = bool(result.get('ok', False))
    log = result.get('log', '')
    if not isinstance(log, str):
        log = str(log)
    outputs = result.get('outfiles')
    if not outputs:
        single = result.get('outfile')
        outputs = [single] if single else []
    outputs = [str(p) for p in outputs if p]
    return ok, log, outputs


def run_report(report_key: str, file_paths: dict, params: dict, log_callback=None) -> tuple:
    """
    보고서를 실행합니다.

    Args:
        report_key: REPORT_CONFIGS의 키
        file_paths: {"file_key": "/path/to/uploaded/file", ...}
        params: {"param_key": value, ...}
        log_callback: 로그 메시지 콜백 (선택)

    Returns:
        (success, log_text, output_file_paths)
    """
    runner_map = {
        "bok_dlnq": _run_bok_dlnq,
        "fx5220_1st": _run_fx5220_1st,
        "fx5220_2nd": _run_fx5220_2nd,
        "fx5260": _run_fx5260,
        "fss_dlnq": _run_fss_dlnq,
        "corp_loan": _run_corp_loan,
        "bok_statistical": _run_bok_statistical,
        "local_rir": _run_local_rir,
        "crir": _run_crir,
        "risk_limit": _run_risk_limit,
        "b2419": _run_b2419,
    }
    runner = runner_map.get(report_key)
    if not runner:
        return False, f"[ERROR] 알 수 없는 보고서: {report_key}", []
    try:
        return runner(file_paths, params, log_callback)
    except Exception:
        import traceback
        return False, f"[ERROR] 러너 예외 발생:\n{traceback.format_exc()}", []


# ─── 개별 러너 함수들 (모두 Reporting/ 의 generate_report 를 in-process 호출) ───

def _run_bok_dlnq(file_paths, params, log_callback):
    from BOK_DLNQ_10days_make import generate_report
    return _unwrap(generate_report(
        file_paths["raw"], file_paths["format"],
        params["base_yymmdd"], params["mortgage_loan"],
    ))


def _run_fx5220_1st(file_paths, params, log_callback):
    from FX5220_make_1st import generate_report
    return _unwrap(generate_report(file_paths["raw"], params["dt"]))


def _run_fx5220_2nd(file_paths, params, log_callback):
    from FX5220_make_2nd import generate_report
    return _unwrap(generate_report(file_paths["raw"], file_paths["format"], params["dt"]))


def _run_fss_dlnq(file_paths, params, log_callback):
    from FSS_dlnq_report_make import generate_report
    return _unwrap(generate_report(file_paths["raw"], file_paths["format"], params["yymmdd"]))


def _run_corp_loan(file_paths, params, log_callback):
    from CORP_LOAN import generate_report
    return _unwrap(generate_report(file_paths["raw"], file_paths["format"], params["dt"]))


def _run_bok_statistical(file_paths, params, log_callback):
    from bok_statistical_report import generate_report
    return _unwrap(generate_report(file_paths["raw"], params["yyyymm"]))


def _run_local_rir(file_paths, params, log_callback):
    from Local_RIR import generate_report
    return _unwrap(generate_report(file_paths["raw"], params["yyyymm"]))


def _run_b2419(file_paths, params, log_callback):
    from B2419_make import generate_report
    return _unwrap(generate_report(file_paths["raw"], params["yyyymm"], params["end_dt"]))


def _run_risk_limit(file_paths, params, log_callback):
    from Risk_limit_monitoring import generate_report
    return _unwrap(generate_report(
        file_paths["raw"], file_paths["ksic"], file_paths["main_debt_group"],
        params["total_ead"], params["yymm"],
    ))


def _parse_ea(s):
    """Early Alerts 문자열(공백 구분 정수 4개) → 정수 리스트 4개."""
    s = (s or "").strip()
    if not s:
        return [0, 0, 0, 0]
    vals = list(map(int, s.split()))
    return (vals + [0, 0, 0, 0])[:4]


def _run_crir(file_paths, params, log_callback):
    from CRIR import generate_report

    base_ym = (params.get("base_ym") or "").strip()
    dates = [d.strip() for d in (params.get("dates") or "").split(",") if d.strip()]
    if len(dates) != 4:
        return False, (
            f"[ERROR] 기간 라벨은 4개여야 합니다 (입력: {len(dates)}개). "
            "예: Apr25,Jan26,Mar26,Apr26"
        ), []
    try:
        ea_purely = _parse_ea(params.get("ea_purely"))
        ea_non_purely = _parse_ea(params.get("ea_non_purely"))
    except ValueError:
        return False, "[ERROR] Early Alerts 값은 공백으로 구분된 정수여야 합니다.", []

    return _unwrap(generate_report(
        file_paths["raw"], file_paths["format"], base_ym,
        dates, ea_purely, ea_non_purely,
    ))


def _run_fx5260(file_paths, params, log_callback):
    """FX5260 - 변동금리 계좌 처리가 필요한 복잡 스크립트 (러너 내부에서 직접 처리).

    (변동금리 금리를 var_rates_json 파라미터로 비대화형 처리하기 위해 다른 보고서와
    달리 러너 내부에 인라인 구현을 유지한다.)
    """
    import pandas as pd
    from datetime import datetime

    upload_dir = Path(file_paths["sql_result"]).parent
    base_yymm = int(params["base_yymm"])
    writer_title = params["writer_title"]
    writer_name = params["writer_name"]
    writer_phone = params["writer_phone"]
    var_rates_json = params.get("var_rates_json", "").strip()

    var_rates = {}
    if var_rates_json:
        try:
            var_rates = json.loads(var_rates_json)
        except Exception:
            return False, "[ERROR] 변동금리 JSON 파싱 실패. 형식을 확인해주세요.", []

    try:
        raw = pd.read_csv(file_paths["sql_result"], sep=",", encoding="euc-kr")
        raw_crms = pd.read_csv(file_paths["crms"], sep=",", encoding="euc-kr")
        raw_seq = pd.read_csv(file_paths["seq"], sep=",", encoding="utf-8-sig")
    except Exception as e:
        return False, f"[ERROR] 파일 읽기 실패: {e}", []

    log = "[INFO] 파일 로드 완료\n"

    try:
        raw_copied = raw.copy()
        object_list = raw_copied.select_dtypes(include="object").columns.tolist()
        for col in object_list:
            raw_copied[col] = raw_copied[col].astype("string")
        for col in raw_copied.columns.tolist():
            if col[2:] == "dt":
                raw_copied[col] = pd.to_datetime(raw_copied[col], format="%d%b%Y", errors="coerce")
                raw_copied[col] = raw_copied[col].dt.strftime("%Y-%m-%d")
        raw_copied["ssn_corpno"] = raw_copied["ssn_corpno"].astype("string")

        raw_merged = raw_crms.merge(raw_seq, how="left", left_index=True, right_index=True)
        raw_merged["주민법인번호"] = raw_merged["주민법인번호"].str[:6]
        raw_merged["ssn_corpno"] = raw_merged["주민법인번호"] + raw_merged["주민법인SEQ번호"]
        raw_merged["acct_no"] = raw_merged["계좌번호"].str[:5] + raw_merged["계좌SEQ번호"]
        raw_merged["고객명"] = raw_merged["고객명"].str[:2]
        raw_merged["client_nm"] = raw_merged["고객명"] + raw_merged["고객SEQ명"]
        raw_merged["취급년월일"] = raw_merged["취급년월일"].str.replace("-", "").str[:6].astype("string")
        raw_merged["취급년월일"] = raw_merged["취급년월일"].replace("", "999999").astype("int")

        fix_int_cd = [748, 780]
        raw_crms_filtered = raw_merged[raw_merged["계정과목코드"].isin([746, 747, 748, 768, 780])]
        raw_crms_filtered = raw_crms_filtered[raw_crms_filtered["취급년월일"] == base_yymm]
        raw_crms_filtered = raw_crms_filtered[raw_crms_filtered["약정계정구분_x"] == "-"]
        raw_crms_filtered = raw_crms_filtered.reset_index()

        var_accounts = []
        for idx in range(len(raw_crms_filtered)):
            if raw_crms_filtered.loc[idx, "계정과목코드"] in fix_int_cd:
                raw_crms_filtered.loc[idx, "int_type"] = "fix"
                raw_crms_filtered.loc[idx, "interest_amt_fix"] = (
                    raw_crms_filtered.loc[idx, "미화환산잔액"]
                    * (raw_crms_filtered.loc[idx, "대출이율"] / 100)
                )
            else:
                acct = str(raw_crms_filtered.loc[idx, "acct_no"])
                raw_crms_filtered.loc[idx, "int_type"] = "var"
                if acct in var_rates:
                    rate = float(var_rates[acct])
                else:
                    var_accounts.append(acct)
                    rate = 0.0
                raw_crms_filtered.loc[idx, "new_interest_var"] = rate
                raw_crms_filtered.loc[idx, "interest_amt_var"] = (
                    raw_crms_filtered.loc[idx, "미화환산잔액"] * (rate / 100)
                )

        if var_accounts:
            log += f"[주의] 다음 변동금리 계좌의 금리가 입력되지 않았습니다 (0%로 처리됨):\n"
            for a in var_accounts:
                log += f"  - {a}\n"
            log += "채팅창에 JSON 형식으로 금리를 입력한 후 재실행해주세요.\n"

        import numpy as np
        ntnl_cd_map = {100: "KR", 193: "CN", 131: "TH", 621: "EG"}
        merged_v2 = raw_copied.merge(raw_crms_filtered, how="left", on="ssn_corpno")
        merged_v2["corp_bond_nice_crdt_grade"] = merged_v2["corp_bond_nice_crdt_grade"].fillna("BB")
        invst_grade = ["AAA+", "AAA", "AAA-", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-"]
        merged_v2["투자투기등급구분코드"] = merged_v2["corp_bond_nice_crdt_grade"].apply(
            lambda x: 1 if x in invst_grade else 2
        )
        merged_v2["차주국가코드"] = merged_v2["ntnl_cd1"].map(ntnl_cd_map).fillna("N/A").astype("string")
        merged_v2["차주소재지국가코드"] = merged_v2["ntnl_cd2"].map(ntnl_cd_map).fillna("N/A").astype("string")
        merged_v2["취급점포코드"] = "023"
        merged_v2["부점명"] = "리스크관리부"
        merged_v2["취급점포소재지식별번호"] = "03160"
        merged_v2["전송구분코드"] = "1"
        merged_v2["관리번호"] = ""
        merged_v2["취급일자"] = merged_v2["i_dt"].str.replace("-", "")
        merged_v2["차주명"] = merged_v2["client_nm"].str[:10]
        merged_v2["만기일자"] = merged_v2["e_dt"].str.replace("-", "")
        merged_v2["대출유형코드"] = merged_v2["<CASE  expression>"].astype("string").str.zfill(2)
        merged_v2["interest_amt_fix"] = merged_v2["interest_amt_fix"].fillna(0)
        merged_v2["interest_amt_var"] = merged_v2["interest_amt_var"].fillna(0)
        merged_v2["고정금리"] = ((merged_v2["interest_amt_fix"] / merged_v2["미화환산잔액"]) * 100).round(2)
        merged_v2["변동금리"] = ((merged_v2["interest_amt_var"] / merged_v2["미화환산잔액"]) * 100).round(2)
        merged_v2["금액"] = (merged_v2["미화환산잔액"] / 1000).round(0)
        merged_v2["작성자직책명"] = writer_title
        merged_v2["작성자명"] = writer_name
        merged_v2["작성자전화번호"] = writer_phone

        cols_for_report = [
            "취급점포코드", "부점명", "취급점포소재지식별번호", "전송구분코드", "관리번호",
            "취급일자", "차주명", "차주국가코드", "차주소재지국가코드", "투자투기등급구분코드",
            "만기일자", "대출유형코드", "고정금리", "변동금리", "금액",
            "작성자직책명", "작성자명", "작성자전화번호",
        ]
        final_report = merged_v2[[c for c in cols_for_report if c in merged_v2.columns]]

        out_path = upload_dir / "FX5260_최종보고서.csv"
        final_report.to_csv(str(out_path), encoding="utf-8-sig", quoting=1, index=False)
        log += f"[INFO] 보고서 저장 완료: {out_path.name}\n"
        return True, log, [str(out_path)]

    except Exception as e:
        import traceback
        return False, f"[ERROR] 처리 중 오류:\n{traceback.format_exc()}", []


def analyze_fx5260_var_accounts(file_paths: dict, base_yymm: int) -> list:
    """FX5260 실행 전 변동금리 계좌 목록 반환"""
    import pandas as pd

    try:
        raw_crms = pd.read_csv(file_paths["crms"], sep=",", encoding="euc-kr")
        raw_seq = pd.read_csv(file_paths["seq"], sep=",", encoding="utf-8-sig")
        fix_int_cd = [748, 780]
        raw_merged = raw_crms.merge(raw_seq, how="left", left_index=True, right_index=True)
        raw_merged["취급년월일"] = raw_merged["취급년월일"].str.replace("-", "").str[:6].astype("string")
        raw_merged["취급년월일"] = raw_merged["취급년월일"].replace("", "999999").astype("int")
        raw_merged["acct_no"] = raw_merged["계좌번호"].str[:5] + raw_merged["계좌SEQ번호"]
        filtered = raw_merged[raw_merged["계정과목코드"].isin([746, 747, 748, 768, 780])]
        filtered = filtered[filtered["취급년월일"] == base_yymm]
        filtered = filtered[filtered["약정계정구분_x"] == "-"]
        var_accounts = filtered[~filtered["계정과목코드"].isin(fix_int_cd)]["acct_no"].tolist()
        return var_accounts
    except Exception:
        return []
