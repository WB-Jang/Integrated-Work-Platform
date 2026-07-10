import pandas as pd
import numpy as np
import openpyxl

from openpyxl import load_workbook


def _preprocessing(file, f_nm, yyyymm):
    yyyymm = str(yyyymm)
    cols = ['기준년월', '계좌번호', '계정과목코드', '주민법인번호', '원화환산잔액', '대출평균잔액', '법인구분코드', '기업규모코드', '소분류[25]', '비고', '대분류', '중분류', '소분류 1', '소분류 2 (참고용)']
    seq_cols = [['계좌번호', '계좌SEQ번호', 5, 6], ['주민법인번호', '주민법인SEQ번호', 6, 7]]

    raw_file = pd.read_excel(file, sheet_name=[f'01_월여신_{f_nm}_{yyyymm}'], header=1)

    raw_file = raw_file[f'01_월여신_{f_nm}_{yyyymm}']
    try:
        seq_file = pd.read_excel(file, sheet_name=[f'01_월여신_{f_nm}_{yyyymm}_seq'])
        seq_file = seq_file[f'01_월여신_{f_nm}_{yyyymm}_seq']
    except Exception:
        seq_file = pd.read_excel(file, sheet_name=[f'01_월여신_137_148_{yyyymm}_seq'])
        seq_file = seq_file[f'01_월여신_137_148_{yyyymm}_seq']

    raw = pd.concat([raw_file, seq_file[['계좌SEQ번호', '주민법인SEQ번호']]], axis=1)

    for sq in seq_cols:
        s, q, i, j = sq
        raw[s] = raw[s].astype('string').str[:i] + raw[q].astype('string').str.zfill(j)

    rel_file = pd.read_excel(file, sheet_name=['related_companies'])
    rel_file = rel_file['related_companies']
    rel_file['주민법인번호'] = rel_file['주민법인번호'].astype('string')

    cls_file = pd.read_excel(file, sheet_name=['classification'])
    cls_file = cls_file['classification']
    cls_file['주민법인번호'] = cls_file['주민법인번호'].astype('string')

    raw = raw.merge(rel_file, how='left', on='주민법인번호')
    raw = raw.merge(cls_file, how='left', on='주민법인번호')
    raw['비고'] = raw['비고'].replace(r'^\s*$', np.nan, regex=True)

    raw['법인구분코드'] = raw['법인구분코드'].astype('string')
    raw['기업규모코드'] = raw['기업규모코드'].astype('string')

    conditions = [((raw['법인구분코드'] == '-') & (raw['기업규모코드'] == '-')),
                  ((raw['법인구분코드'] != '-') & (raw['기업규모코드'].isin(['2', '3']))),
                  ((raw['법인구분코드'] == '-') & (raw['기업규모코드'].isin(['2', '3']))),
                  ((~raw['법인구분코드'].isnull()) & (raw['기업규모코드'].isin(['1']))),
                  ]
    choices = ['소분류', '3.4.1. 법인중소', '3.4.2. 준법인기업', '3.2.1. 대기업']
    raw['소분류[25]'] = np.select(conditions, choices, default='Unknown')

    raw['비고'] = raw['비고'].fillna('해당무')
    raw['대분류'] = raw['대분류'].fillna('기업부문')
    raw['중분류'] = raw['중분류'].fillna('L. 기업부문')
    raw['소분류 1'] = raw['소분류 1'].fillna('L-2. 민간기업')
    raw['소분류 2 (참고용)'] = raw['소분류 2 (참고용)'].fillna('민간기업')
    raw = raw[cols]

    return raw


def generate_report(raw, yyyymm):
    """BOK 통화금융통계 월여신 조사표.

    통합 raw(.xlsx, 다중 시트)와 기준년월(YYYYMM)을 받아 그룹별 결과 CSV를
    저장한다. 최종 파일명/경로는 기존 하드코딩 규칙을 그대로 따른다.
    """
    logs = []
    outfiles = []

    def _log(m):
        logs.append(str(m))

    def _fail(step, e):
        import traceback
        _log(f"[ERROR] '{step}' 단계에서 오류: {e}")
        _log(traceback.format_exc())
        return {'ok': False, 'log': "\n".join(logs), 'outfile': None}

    try:
        _log(f"[1/2] 입력값 확인 중... (기준: {yyyymm})")
        yyyymm = str(yyyymm)
        file_list = [['원화대출금', '137,148'], ['기타']]
    except Exception as e:
        return _fail("입력값 확인", e)

    for i, f_nm in enumerate(file_list):
        try:
            _log(f"[2/2] 그룹 {i + 1}/{len(file_list)} 처리 중: {f_nm}")
            results = []
            for f in f_nm:
                results.append(_preprocessing(raw, f, yyyymm))
            raw_concat = pd.concat(results, axis=0)
            outfile = f"C:/Users/1598505/OneDrive - Standard Chartered Bank/1.보고서(WB)/2.BOK/2.월/통화금융통계조사표/{yyyymm[:4]}년도/{yyyymm[2:6]}/result_{f_nm}_({yyyymm[2:6]}기준).csv"
            raw_concat.to_csv(outfile, index=False, encoding='utf-8-sig')
            outfiles.append(outfile)
        except Exception as e:
            return _fail(f"그룹 처리({f_nm})", e)

    _log(f"[완료] BOK 통화금융통계 조사표 작성 완료: {len(outfiles)}개 파일")
    return {'ok': True, 'log': "\n".join(logs), 'outfile': outfiles[0] if outfiles else None, 'outfiles': outfiles}
