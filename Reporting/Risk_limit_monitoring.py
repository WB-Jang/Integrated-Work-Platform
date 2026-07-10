import pandas as pd
import numpy as np
import configs


def preprocessing(data, ksic, main_debt_group, total_ead):
    main_debt_group.drop_duplicates()
    main_debt_group = main_debt_group.dropna(subset=['SSN_CORP_NUM'])

    ksic[configs.COLUMN_NMS['RISK_LIMIT_ADD_COLS'][0]] = ksic[configs.COLUMN_NMS['RISK_LIMIT_ADD_COLS'][0]].astype('string').str.strip()
    cols = data.columns

    data[cols[0]] = data[cols[0]].astype('float')

    data[cols[3]].fillna('K64999', inplace=True)
    data[configs.COLUMN_NMS['RISK_LIMIT_ADD_COLS'][0]] = np.where((data[cols[0]].astype('string').str[:3] == '400') & (data[cols[0]].isnull()), np.nan, data[cols[3]].astype('string').str[:3])

    data[configs.COLUMN_NMS['RISK_LIMIT_ADD_COLS'][0]] = data[configs.COLUMN_NMS['RISK_LIMIT_ADD_COLS'][0]].astype('string')
    data = pd.merge(data, ksic, how='left', on=configs.COLUMN_NMS['RISK_LIMIT_ADD_COLS'][0])

    data = pd.merge(data, main_debt_group, how='left', on=cols[0])

    sum_ead = data[cols[4]].sum()
    data[configs.COLUMN_NMS['RISK_LIMIT_ADD_COLS'][3]] = (total_ead * (data[cols[4]] / sum_ead))
    return data


def generate_report(raw, ksic, main_debt_group, total_ead, yymm):
    """리스크 한도 모니터링.

    원시 데이터(raw)·KSIC 코드(ksic)·주채무그룹(main_debt_group) CSV 3종과
    Total EAD, 기준년월(YYMM)을 받아 전처리 결과 CSV를 저장한다.
    최종 결과 경로는 configs.PATH['RISK_LIMIT_RESULT'] 하드코딩 규칙을 따른다.
    """
    logs = []

    def _log(m):
        logs.append(str(m))

    def _fail(step, e):
        import traceback
        _log(f"[ERROR] '{step}' 단계에서 오류: {e}")
        _log(traceback.format_exc())
        return {'ok': False, 'log': "\n".join(logs), 'outfile': None}

    try:
        _log(f"[1/3] 원시/KSIC/주채무그룹 CSV 로드 중... (기준: {yymm})")
        total_ead = float(total_ead)
        yymm = str(yymm)
        raw_df = pd.read_csv(raw, sep=",", encoding='euc-kr')
        ksic_df = pd.read_csv(ksic, sep=",", encoding='utf-8-sig')
        main_debt_group_df = pd.read_csv(main_debt_group, sep=",", encoding='utf-8-sig')
        main_debt_group_df.drop_duplicates()
        main_debt_group_df = main_debt_group_df.dropna(subset=['SSN_CORP_NUM'])
    except Exception as e:
        return _fail("입력 CSV 로드", e)

    try:
        _log("[2/3] 전처리(업종매핑·주채무그룹 병합·EAD 배분) 중...")
        result = preprocessing(raw_df, ksic_df, main_debt_group_df, total_ead=total_ead)
    except Exception as e:
        return _fail("전처리", e)

    try:
        _log("[3/3] 결과 CSV 저장 중...")
        outfile = configs.PATH['RISK_LIMIT_RESULT'].format(yymm=yymm)
        result.to_csv(outfile, encoding='utf-8-sig', index=False)
    except Exception as e:
        return _fail("결과 저장", e)

    _log(f"[완료] 리스크 한도 모니터링 작성 완료: {outfile}")
    return {'ok': True, 'log': "\n".join(logs), 'outfile': outfile}
