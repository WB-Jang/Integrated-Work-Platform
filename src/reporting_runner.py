"""
보고서 작성 러너 모듈
각 보고서 스크립트의 설정 및 실행 로직을 관리합니다.
"""
import os
import sys
import uuid
import subprocess
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
REPORTING_DIR = (BASE_DIR / "Reporting").resolve()

REPORT_CONFIGS = {
    "bok_dlnq": {
        "name": "BOK 10일 연체 보고서",
        "description": "BOK 제출용 10일 기준 연체 현황 보고서",
        "icon": "📋",
        "files": [
            {"key": "bf_15", "label": "이전 기준일 15번쿼리 CSV", "hint": "인코딩: euc-kr"},
            {"key": "cur_15", "label": "이번 기준일 15번쿼리 CSV", "hint": "인코딩: euc-kr"},
            {"key": "cur_17", "label": "이번 기준일 17번쿼리 CSV", "hint": "인코딩: euc-kr"},
        ],
        "params": [
            {"key": "mortgage_loan", "label": "주택담보대출 금액 (억원, 예: 1234.56)", "type": "float"},
        ],
        "outputs": ["BOK_보고서1.csv", "BOK_보고서2.csv"],
        "runner": "bok_dlnq",
    },
    "fx5220_1st": {
        "name": "FX5220 보고서 (1차)",
        "description": "외화여신 FX5220 1차 - 신규 외화여신 현황",
        "icon": "💱",
        "files": [
            {"key": "current", "label": "이번 기준년월 CSV", "hint": "인코딩: euc-kr"},
            {"key": "previous", "label": "이전 기준년월 CSV", "hint": "인코딩: utf-8"},
        ],
        "params": [
            {"key": "dt", "label": "기준 날짜 (yyyymmdd, 예: 20260201)", "type": "str"},
        ],
        "outputs": ["FX5220_신규여신.csv"],
        "runner": "fx5220_1st",
    },
    "fx5220_2nd": {
        "name": "FX5220 보고서 (2차)",
        "description": "외화여신 FX5220 2차 - RM 정보 추가 및 피벗 테이블 작성",
        "icon": "💱",
        "files": [
            {"key": "current", "label": "이번 기준년월 CSV", "hint": "인코딩: utf-8"},
            {"key": "previous", "label": "이전 기준년월 CSV", "hint": "인코딩: utf-8"},
            {"key": "rm_response", "label": "신규 외화여신 RM 회신 CSV", "hint": "인코딩: utf-8"},
        ],
        "params": [
            {"key": "dt", "label": "기준 날짜 (yyyymmdd, 예: 20260201)", "type": "str"},
        ],
        "outputs": ["FX5220_rm_info.csv"],
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
        "description": "금융감독원 제출용 연체 현황 보고서",
        "icon": "📊",
        "files": [
            {"key": "file1", "label": "1번 쿼리 결과 CSV", "hint": "인코딩: euc-kr"},
            {"key": "file2", "label": "2번 쿼리 결과 CSV", "hint": "인코딩: euc-kr"},
        ],
        "params": [],
        "outputs": ["FSS_연체보고서1.csv", "FSS_연체보고서2.csv"],
        "runner": "fss_dlnq",
    },
    "corp_loan": {
        "name": "기업 여신 조사표",
        "description": "한국은행 기업 여신 현황 조사표 (FS_00401, FS_00409)",
        "icon": "🏢",
        "files": [
            {"key": "fs_00401", "label": "이번 기준년월 FS_00401 CSV", "hint": "인코딩: euc-kr"},
            {"key": "bf_fs_00401", "label": "이전 기준년월 FS_00401 CSV", "hint": "인코딩: euc-kr"},
            {"key": "fs_00409", "label": "이번 기준년월 FS_00409 CSV", "hint": "인코딩: euc-kr"},
        ],
        "params": [],
        "outputs": ["fs_00401_result.csv", "fs_00409_result.csv"],
        "runner": "corp_loan",
    },
    "bok_statistical": {
        "name": "BOK 통화금융통계 조사표",
        "description": "한국은행 통화금융통계 월여신 조사표",
        "icon": "📈",
        "files": [
            {"key": "monthly_loan", "label": "월여신 CSV (01_월여신_137,148)", "hint": "인코딩: euc-kr"},
            {"key": "seq", "label": "SEQ CSV (seq_137_148)", "hint": "인코딩: euc-kr"},
            {"key": "related", "label": "관계사 CSV (related_companies)", "hint": "인코딩: cp949"},
            {"key": "classification", "label": "분류 CSV (classification)", "hint": "인코딩: euc-kr"},
        ],
        "params": [
            {"key": "yymm", "label": "기준년월", "type": "yymm", "format": "YYMM"},
        ],
        "outputs": ["BOK_통계조사표_결과.csv"],
        "runner": "bok_statistical",
    },
    "local_rir": {
        "name": "Local RIR",
        "description": "내부 리스크 정보 보고서 (Local Risk Information Reporting)",
        "icon": "⚠️",
        "files": [
            {"key": "cg2_excl", "label": "CG2 제외 데이터 CSV", "hint": "인코딩: euc-kr"},
            {"key": "portfolio", "label": "포트폴리오 데이터 CSV", "hint": "인코딩: euc-kr"},
            {"key": "product_map", "label": "상품 매핑 CSV", "hint": "인코딩: utf-8-sig"},
            {"key": "product_bc_retail", "label": "Product BC Retail CSV", "hint": "인코딩: euc-kr"},
        ],
        "params": [
            {"key": "bfyymm", "label": "이전 기준년월", "type": "yymm", "format": "YYMM"},
            {"key": "yymm", "label": "이번 기준년월", "type": "yymm", "format": "YYMM"},
        ],
        "outputs": ["LocalRIR_결과.csv"],
        "runner": "local_rir",
    },
    "crir": {
        "name": "CRIR 보고서",
        "description": "거래상대방 리스크 정보 보고서 (raw 엑셀 다중시트 → 폼 템플릿 자동 기입)",
        "icon": "📋",
        "mode": "form_fill",
        "files": [
            {"key": "raw_data", "label": "CRIR raw_data.xlsx (다중 시트)", "hint": "시트: Sheet2 등"},
            {"key": "form", "label": "보고서 폼 템플릿 .xlsx", "hint": "결과가 채워질 양식 (워크시트 'new')"},
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
        "outputs": ["CRIR_보고서_filled.xlsx"],
        "runner": "crir",
    },
    "risk_limit": {
        "name": "리스크 한도 모니터링",
        "description": "리스크 한도 준수 현황 모니터링 보고서",
        "icon": "🎯",
        "files": [
            {"key": "raw_data", "label": "원시 데이터 CSV", "hint": "인코딩: euc-kr"},
            {"key": "ksic", "label": "KSIC 코드 CSV", "hint": "인코딩: utf-8-sig"},
            {"key": "main_debt_group", "label": "주채무그룹 CSV", "hint": "인코딩: utf-8-sig"},
        ],
        "params": [
            {"key": "yymm", "label": "기준년월", "type": "yymm", "format": "YYMM"},
            {"key": "total_ead", "label": "Total EAD (예: 17687118)", "type": "float"},
        ],
        "outputs": ["RiskLimit_결과.csv"],
        "runner": "risk_limit",
    },
}


def get_upload_dir(report_key: str) -> Path:
    upload_base = BASE_DIR / "uploads" / "reports"
    run_id = uuid.uuid4().hex[:8]
    d = upload_base / f"{report_key}_{run_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _build_stdin(lines: list) -> str:
    return "\n".join(str(line) for line in lines) + "\n"


def _subprocess_env() -> dict:
    """자식 프로세스가 UTF-8로 stdin/stdout을 처리하도록 환경변수를 설정합니다."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def run_subprocess_script(script_path: Path, stdin_lines: list, log_callback=None) -> tuple[bool, str]:
    """
    지정된 스크립트를 subprocess로 실행합니다.
    Returns: (success, output_log)
    """
    stdin_text = _build_stdin(stdin_lines)
    try:
        result = subprocess.run(
            [sys.executable, "-u", str(script_path)],
            input=stdin_text,
            capture_output=True,
            text=True,
            cwd=str(REPORTING_DIR),
            timeout=300,
            encoding="utf-8",
            errors="replace",
            env=_subprocess_env(),
        )
        log = result.stdout
        if result.returncode != 0:
            log += f"\n[ERROR]\n{result.stderr}"
            return False, log
        return True, log
    except subprocess.TimeoutExpired:
        return False, "[ERROR] 실행 시간 초과 (300초)"
    except Exception as e:
        return False, f"[ERROR] 실행 실패: {e}"


def run_report(report_key: str, file_paths: dict, params: dict, log_callback=None) -> tuple[bool, str, list]:
    """
    보고서를 실행합니다.

    Args:
        report_key: REPORT_CONFIGS의 키
        file_paths: {"file_key": "/path/to/uploaded/file.csv", ...}
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
    }
    runner = runner_map.get(report_key)
    if not runner:
        return False, f"[ERROR] 알 수 없는 보고서: {report_key}", []
    try:
        return runner(file_paths, params, log_callback)
    except Exception as e:
        import traceback
        return False, f"[ERROR] 예외 발생:\n{traceback.format_exc()}", []


# ─── 개별 러너 함수들 ─────────────────────────────────────────

def _run_bok_dlnq(file_paths, params, log_callback):
    upload_dir = Path(file_paths["bf_15"]).parent
    bf_15 = Path(file_paths["bf_15"])
    cur_15 = Path(file_paths["cur_15"])
    cur_17 = Path(file_paths["cur_17"])
    mortgage_loan = params["mortgage_loan"]
    out1 = "BOK_보고서1.csv"
    out2 = "BOK_보고서2.csv"
    stdin_lines = [
        str(mortgage_loan),
        str(upload_dir),
        f"/{bf_15.name}",
        str(upload_dir),
        f"/{cur_15.name}",
        f"/{cur_17.name}",
        f"/{out1}",
        f"/{out2}",
    ]
    script = REPORTING_DIR / "BOK_DLNQ_10days_make.py"
    ok, log = run_subprocess_script(script, stdin_lines, log_callback)
    outputs = [str(upload_dir / out1), str(upload_dir / out2)] if ok else []
    return ok, log, outputs


def _run_fx5220_1st(file_paths, params, log_callback):
    upload_dir = Path(file_paths["current"]).parent
    current = Path(file_paths["current"])
    previous = Path(file_paths["previous"])
    dt = params["dt"]
    out_file = "FX5220_신규여신.csv"
    stdin_lines = [
        str(dt),
        str(upload_dir),
        f"/{current.name}",
        str(upload_dir),
        f"/{previous.name}",
        str(upload_dir),
        f"/{out_file}",
    ]
    script = REPORTING_DIR / "FX5220_make_1st.py"
    ok, log = run_subprocess_script(script, stdin_lines, log_callback)
    outputs = [str(upload_dir / out_file)] if ok else []
    return ok, log, outputs


def _run_fx5220_2nd(file_paths, params, log_callback):
    upload_dir = Path(file_paths["current"]).parent
    current = Path(file_paths["current"])
    previous = Path(file_paths["previous"])
    rm_response = Path(file_paths["rm_response"])
    dt = params["dt"]
    out_file = "FX5220_rm_info.csv"
    stdin_lines = [
        str(dt),
        str(upload_dir),
        f"/{current.name}",
        str(upload_dir),
        f"/{previous.name}",
        str(upload_dir),
        f"/{rm_response.name}",
        str(upload_dir),
        f"/{out_file}",
    ]
    script = REPORTING_DIR / "FX5220_make_2nd.py"
    ok, log = run_subprocess_script(script, stdin_lines, log_callback)
    outputs = [str(upload_dir / out_file)] if ok else []
    return ok, log, outputs


def _run_fx5260(file_paths, params, log_callback):
    """FX5260 - 변동금리 계좌 처리가 필요한 복잡 스크립트"""
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


def _run_fss_dlnq(file_paths, params, log_callback):
    upload_dir = Path(file_paths["file1"]).parent
    file1 = Path(file_paths["file1"])
    file2 = Path(file_paths["file2"])
    out1 = "FSS_연체보고서1.csv"
    out2 = "FSS_연체보고서2.csv"
    stdin_lines = [
        str(upload_dir),
        f"/{file1.name}",
        f"/{file2.name}",
        str(upload_dir),
        f"/{out1}",
        f"/{out2}",
    ]
    script = REPORTING_DIR / "FSS_dlnq_report_make.py"
    ok, log = run_subprocess_script(script, stdin_lines, log_callback)
    outputs = [str(upload_dir / out1), str(upload_dir / out2)] if ok else []
    return ok, log, outputs


def _run_corp_loan(file_paths, params, log_callback):
    upload_dir = Path(file_paths["fs_00401"]).parent
    fs_00401 = Path(file_paths["fs_00401"])
    bf_fs_00401 = Path(file_paths["bf_fs_00401"])
    fs_00409 = Path(file_paths["fs_00409"])
    stdin_lines = [
        str(upload_dir),
        f"/{fs_00401.name}",
        f"/{bf_fs_00401.name}",
        f"/{fs_00409.name}",
    ]
    cmd = (
        f"import sys; sys.path.insert(0, r'{REPORTING_DIR}'); "
        f"from CORP_LOAN import generate_report; generate_report()"
    )
    stdin_text = _build_stdin(stdin_lines)
    try:
        result = subprocess.run(
            [sys.executable, "-u", "-c", cmd],
            input=stdin_text,
            capture_output=True,
            text=True,
            cwd=str(REPORTING_DIR),
            timeout=300,
            encoding="utf-8",
            errors="replace",
            env=_subprocess_env(),
        )
        log = result.stdout
        if result.returncode != 0:
            log += f"\n[ERROR]\n{result.stderr}"
            return False, log, []
        out1 = str(upload_dir / "fs_00401_result.csv")
        out2 = str(upload_dir / "fs_00409_result.csv")
        return True, log, [out1, out2]
    except Exception as e:
        return False, f"[ERROR] 실행 실패: {e}", []


def _run_bok_statistical(file_paths, params, log_callback):
    """BOK 통화금융통계 조사표 - 파일 업로드 기반으로 실행"""
    import pandas as pd

    upload_dir = Path(file_paths["monthly_loan"]).parent
    yymm = params["yymm"]
    log = f"[INFO] BOK 통화금융통계 조사표 작성 시작 (기준: {yymm})\n"

    try:
        cols = ["기준년월", "계좌번호", "계정과목코드", "주민법인번호",
                "원화환산잔액", "대출평균잔액", "법인구분코드", "기업규모코드"]
        seq_cols_def = [["계좌번호", "계좌SEQ번호", 5, 6], ["주민법인번호", "주민법인SEQ번호", 6, 7]]

        tmp_137_148 = pd.read_csv(file_paths["monthly_loan"], encoding="euc-kr")
        seq_137_148 = pd.read_csv(file_paths["seq"], encoding="euc-kr")
        rel = pd.read_csv(file_paths["related"], encoding="cp949")
        cls = pd.read_csv(file_paths["classification"], encoding="euc-kr")

        raw_137_148 = pd.concat([tmp_137_148, seq_137_148], axis=1)

        for sq in seq_cols_def:
            s, q, i, j = sq
            if s in raw_137_148.columns and q in raw_137_148.columns:
                raw_137_148[s] = (
                    raw_137_148[s].astype("string").str[:i]
                    + raw_137_148[q].astype("string").str.zfill(j)
                )

        available_cols = [c for c in cols if c in raw_137_148.columns]
        result = raw_137_148[available_cols]

        out_path = upload_dir / "BOK_통계조사표_결과.csv"
        result.to_csv(str(out_path), encoding="utf-8-sig", index=False)
        log += f"[INFO] 기본 처리 완료. 결과 저장: {out_path.name}\n"
        log += "[INFO] 관계사/분류 데이터 로드 완료. 추가 처리가 필요한 경우 원본 스크립트를 참조하세요.\n"
        return True, log, [str(out_path)]

    except Exception as e:
        import traceback
        return False, f"[ERROR] 처리 중 오류:\n{traceback.format_exc()}", []


def _run_local_rir(file_paths, params, log_callback):
    """Local RIR - 클래스 기반 처리"""
    import pandas as pd
    from pandas.api.types import CategoricalDtype

    upload_dir = Path(file_paths["cg2_excl"]).parent
    bfyymm = params["bfyymm"]
    yymm = params["yymm"]
    log = f"[INFO] Local RIR 작성 시작 (기준: {yymm}, 이전: {bfyymm})\n"

    try:
        raw_cg2_excl = pd.read_csv(file_paths["cg2_excl"], sep=",", encoding="euc-kr")
        portfolio_data = pd.read_csv(file_paths["portfolio"], sep=",", encoding="euc-kr")
        product_map = pd.read_csv(file_paths["product_map"], sep=",", encoding="utf-8-sig")
        product_bc_retail = pd.read_csv(file_paths["product_bc_retail"], sep=",", encoding="euc-kr")

        raw_cg2_excl["base_dt"] = yymm

        cgs = [["01","02","03","04","05"],["06","07","08"],["09","10","11"],["12"],["13","14"]]
        cg_nms = ["1~5","6~8","9~11","12","13~14"]

        for idx in range(len(raw_cg2_excl)):
            for i, cg in enumerate(cgs):
                if str(raw_cg2_excl.loc[idx, "cg"]) in cg:
                    raw_cg2_excl.loc[idx, "cg_group"] = cg_nms[i]

        raw_cg2_excl["cg_group"] = raw_cg2_excl["cg_group"].fillna("SA, Default(RB)")

        out_path = upload_dir / "LocalRIR_결과.csv"
        raw_cg2_excl.to_csv(str(out_path), encoding="utf-8-sig", index=False)
        log += f"[INFO] 기본 처리 완료. 결과 저장: {out_path.name}\n"
        log += "[INFO] 추가 피벗/집계가 필요한 경우 원본 스크립트를 참조하세요.\n"
        return True, log, [str(out_path)]

    except Exception as e:
        import traceback
        return False, f"[ERROR] 처리 중 오류:\n{traceback.format_exc()}", []


def _run_crir(file_paths, params, log_callback):
    """CRIR - raw 엑셀(다중 시트)을 집계하여 폼 템플릿 셀에 직접 기입 (form_fill 패턴).

    Reporting/CRIR.py 의 generate_crir() 를 호출한다. 다른 보고서도 동일하게
    '원시 엑셀 + 폼 템플릿 업로드 → 폼을 채워 다운로드' 구조로 확장할 수 있다.
    """
    upload_dir = Path(file_paths["raw_data"]).parent
    raw_path = file_paths["raw_data"]
    form_path = file_paths.get("form")
    if not form_path:
        return False, "[ERROR] 폼 템플릿(.xlsx) 파일을 업로드하세요.", []

    base_ym = (params.get("base_ym") or "").strip()
    dates = [d.strip() for d in (params.get("dates") or "").split(",") if d.strip()]
    if len(dates) != 4:
        return False, (
            f"[ERROR] 기간 라벨은 4개여야 합니다 (입력: {len(dates)}개). "
            "예: Apr25,Jan26,Mar26,Apr26"
        ), []

    def _parse_ea(s):
        s = (s or "").strip()
        if not s:
            return [0, 0, 0, 0]
        vals = list(map(int, s.split()))
        return (vals + [0, 0, 0, 0])[:4]

    try:
        ea_purely = _parse_ea(params.get("ea_purely"))
        ea_non_purely = _parse_ea(params.get("ea_non_purely"))
    except ValueError:
        return False, "[ERROR] Early Alerts 값은 공백으로 구분된 정수여야 합니다.", []

    logs = [f"[INFO] CRIR 보고서 작성 시작 (기준: {base_ym}, 기간: {', '.join(dates)})"]

    def _log(msg):
        logs.append(str(msg))
        if log_callback:
            try:
                log_callback(str(msg))
            except Exception:
                pass

    out_path = upload_dir / "CRIR_보고서_filled.xlsx"
    try:
        if str(REPORTING_DIR) not in sys.path:
            sys.path.insert(0, str(REPORTING_DIR))
        import importlib
        import CRIR
        importlib.reload(CRIR)
        CRIR.generate_crir(
            raw_path=raw_path, form_path=form_path, output_path=str(out_path),
            dates=dates, ea_purely=ea_purely, ea_non_purely=ea_non_purely,
            base_ym=base_ym, log_fn=_log,
        )
        return True, "\n".join(logs), [str(out_path)]
    except Exception:
        import traceback
        return False, "\n".join(logs) + f"\n[ERROR] 처리 중 오류:\n{traceback.format_exc()}", []


def _run_risk_limit(file_paths, params, log_callback):
    """리스크 한도 모니터링 - preprocessing 함수 직접 호출"""
    import pandas as pd
    import numpy as np
    from pandas.api.types import CategoricalDtype

    upload_dir = Path(file_paths["raw_data"]).parent
    yymm = params["yymm"]
    total_ead = float(params["total_ead"])
    log = f"[INFO] 리스크 한도 모니터링 작성 시작 (기준: {yymm}, Total EAD: {total_ead})\n"

    # configs 상수 (인라인)
    add_cols = ["industry1", "industry2", "group_nm", "final_ead"]

    try:
        raw = pd.read_csv(file_paths["raw_data"], sep=",", encoding="euc-kr")
        ksic = pd.read_csv(file_paths["ksic"], sep=",", encoding="utf-8-sig")
        main_debt_group = pd.read_csv(file_paths["main_debt_group"], sep=",", encoding="utf-8-sig")

        main_debt_group = main_debt_group.drop_duplicates()
        main_debt_group = main_debt_group.dropna(subset=["SSN_CORP_NUM"])
        cols = raw.columns

        if add_cols[0] in ksic.columns:
            ksic[add_cols[0]] = ksic[add_cols[0]].astype("string").str.strip()

        raw[cols[0]] = raw[cols[0]].astype("float")
        raw[cols[3]] = raw[cols[3]].fillna("K64999")
        raw[add_cols[0]] = np.where(
            (raw[cols[0]].astype("string").str[:3] == "400") & (raw[cols[0]].isnull()),
            np.nan,
            raw[cols[3]].astype("string").str[:3],
        )
        raw[add_cols[0]] = raw[add_cols[0]].astype("string")
        raw = pd.merge(raw, ksic, how="left", on=add_cols[0])
        raw = pd.merge(raw, main_debt_group, how="left", on=cols[0])
        sum_ead = raw[cols[4]].sum()
        raw[add_cols[3]] = total_ead * (raw[cols[4]] / sum_ead)

        out_path = upload_dir / "RiskLimit_결과.csv"
        raw.to_csv(str(out_path), encoding="utf-8-sig", index=False)
        log += f"[INFO] 처리 완료. 결과 저장: {out_path.name}\n"
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
