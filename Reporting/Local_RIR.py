import pandas as pd
import numpy as np

from pandas.api.types import CategoricalDtype


class local_RIR():
    def __init__(self, raw, yyyymm):
        yyyymm = str(yyyymm)
        self.yymm = yyyymm
        self.raw = pd.read_excel(raw, sheet_name=['industry_mapping', 'product_mapping', f'product_bc_retail_{yyyymm[2:]}', f'industry_{yyyymm[2:]}', f'portfolio_data_{yyyymm[2:]}', f'cg2_excl_{yyyymm[2:]}', f'scorecard_{yyyymm[2:]}'])

        self.map = self.raw['product_mapping']
        self.map_indu = self.raw['industry_mapping']

        self.cols = ['balance', 'rwa']

    def portfolio_data(self):
        raw = self.raw[f'portfolio_data_{self.yymm[2:]}']
        contitions = [(raw['cust_seg2'] == 'XXX') & (raw['COUNTERPARTY_NEW'] == '토스뱅크주식회사'), (raw['cust_seg2'] == 'XXX') & (raw['COUNTERPARTY_NEW'] == 'BOND MARKET STABILIZATION FUND')]

        results = []
        for c in contitions:
            amt = raw[c][['sum_bal', 'sum_RWA']]
            results.append(amt)

        self.amt_toss, self.amt_bond = results

    def cg2_excl(self):
        try:
            df = self.raw[f'cg2_excl_{self.yymm[2:]}']
            df['cg'] = df['cg'].astype('string').str.zfill(2)
            conditions = [(df['cg'].isin(['01', '02', '03', '04', '05'])), (df['cg'].isin(['06', '07', '08'])),
                          (df['cg'].isin(['09', '10', '11'])), (df['cg'].isin(['12'])), (df['cg'].isin(['13', '14']))]
            choices = list(['1~5', '6~8', '9~11', '12', '13~14'])

            df['cg_group'] = np.select(conditions, choices, default='SA, Default(RB)')
            for col in self.cols:
                df[col] = df[col].astype(str).replace(',', '').astype('float64')

        except Exception as e:
            print(f'cg 데이터 전처리 에러 발생 : {e}')

        try:
            condition = (df['cust_seg'] == 'XXX') & (df['METHOD_NEW'] == 'STD') & (df['EXPOSURE_ATTRIBUTE_3'].isnull())
            new = df[condition]
            for idx, col in enumerate(self.cols):
                new[col] = new[col] - self.amt_toss.iloc[0, idx] - self.amt_bond.iloc[0, idx]

            base = df[~condition]
            base['cust_seg'] = base.apply(
                lambda row: 'WRB' if row['cust_seg'] in ['XXX', 'Business Clients'] else 'CCIB', axis=1
            )

            final_raw = pd.concat([base, new], ignore_index=True)

            final_raw['cust_seg'] = final_raw.apply(
                lambda row: 'CCIB' if row['cust_seg'] in ['XXX'] else row['cust_seg'], axis=1
            )
            cg_order = ['01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12', '13-14', 'ST', 'DE']
            final_raw['cg'] = final_raw['cg'].astype(CategoricalDtype(categories=cg_order, ordered=True))
            cg_group_order = ['1~5', '6~8', '9~11', '12', '13~14', 'SA, Default(RB)']
            final_raw['cg_group'] = final_raw['cg_group'].astype(CategoricalDtype(categories=cg_group_order, ordered=True))

            for col in self.cols:
                final_raw[col] = final_raw[col] / 1000
        except Exception as e:
            print(f'Final Table 작성 중 에러 발생 : {e}')

        self.cg_table1 = pd.pivot_table(
            final_raw,
            values=self.cols,
            index='cg',
            aggfunc='sum',
            fill_value=0
        )

        self.cg_table2 = pd.pivot_table(
            final_raw,
            values=self.cols,
            index=['cg_group', 'cust_seg'],
            aggfunc='sum',
            fill_value=0
        )

    def Product_BC_retail(self):
        try:
            raw_Product_BC_retail = self.raw[f'product_bc_retail_{self.yymm[2:]}']
            segs = ['XXX', 'Commercial Clients', 'Corporate & Institutional Clients', 'Own Account']
            seg = ['Business Clients']
            map = self.map

            raw_Product_BC_retail.loc[(raw_Product_BC_retail['cust_seg'] == 'XXX') & (raw_Product_BC_retail['Product_Desc'].isnull()), 'cust_seg'] = 'Business Clients'
            Product_Desc_order = ['Cash Management', 'Global Markets', 'Trades', 'Loans']
            raw_Product_BC_retail['Product_Desc'] = raw_Product_BC_retail['Product_Desc'].astype(CategoricalDtype(categories=Product_Desc_order, ordered=True))

            for idx, col in enumerate(self.cols):
                raw_Product_BC_retail.loc[(raw_Product_BC_retail['cust_seg'] == 'XXX') & (raw_Product_BC_retail['PSGL_PRDCT_CD'] == 731), col] = raw_Product_BC_retail.loc[(raw_Product_BC_retail['cust_seg'] == 'XXX') & (raw_Product_BC_retail['PSGL_PRDCT_CD'] == 731), col] - self.amt_bond.iloc[0, idx]
            for idx, col in enumerate(self.cols):
                raw_Product_BC_retail.loc[(raw_Product_BC_retail['cust_seg'] == 'XXX') & (raw_Product_BC_retail['PSGL_PRDCT_CD'] == 740), col] = raw_Product_BC_retail.loc[(raw_Product_BC_retail['cust_seg'] == 'XXX') & (raw_Product_BC_retail['PSGL_PRDCT_CD'] == 740), col] - self.amt_toss.iloc[0, idx]

            for col in self.cols:
                raw_Product_BC_retail[col] = raw_Product_BC_retail[col] / 1000
            merged_raw = raw_Product_BC_retail.merge(map, how='left', on='oltp_acct_sbjct_cd')

        except Exception as e:
            print(f'raw 데이터 작성 중 에러 발생 : {e}')

        try:
            merged_raw.loc[(merged_raw['cust_seg'].isin(seg)) & (merged_raw['RB_prod'].isnull()), 'RB_prod'] = merged_raw.loc[(merged_raw['cust_seg'].isin(seg)) & (merged_raw['RB_prod'].isnull()), 'RB_prod_new']
            merged_raw.drop_duplicates(inplace=True)
            prod_list = [['Drim', '분할상환대출'], ['Sele', '리볼빙대출'], ['Cred', '신용카드'], ['O_Un', '신용여신기타'], ['FHL', '퍼스트홈론'],
                         ['WML', '퍼스트홈론잔금'], ['KFHL', '공사모기지론'], ['O_Se', '담보여신기타'],
                         ['BIL', '중소기업분할상환대출'], ['Mort', 'SME비즈니스모기지'], ['GIL', '보증서담보대출'], ['XX', '무역및운전자금대출']]

            for l in prod_list:
                e, k = l

                merged_raw['RB_prod'] = merged_raw.apply(
                    lambda row: k if (row['RB_prod'] in [e]) else row['RB_prod'], axis=1
                )

            RB_prod_order = ['분할상환대출', '리볼빙대출', '신용카드', '신용여신기타', '퍼스트홈론', '퍼스트홈론잔금', '공사모기지론', '담보여신기타', '중소기업분할상환대출', 'SME비즈니스모기지', '보증서담보대출', '무역및운전자금대출']
            merged_raw['RB_prod'] = merged_raw['RB_prod'].astype(CategoricalDtype(categories=RB_prod_order, ordered=True))

        except Exception as e:
            print(f'raw 데이터 전처리 중 에러 발생 : {e}')

        self.ccib_prod = pd.pivot_table(
            raw_Product_BC_retail[raw_Product_BC_retail['cust_seg'].isin(segs)],
            values=self.cols,
            index='Product_Desc',
            aggfunc='sum', fill_value=0
        )
        self.wrb_prod = pd.pivot_table(
            merged_raw[merged_raw['cust_seg'].isin(seg)],
            values=self.cols,
            index='RB_prod',
            aggfunc='sum', fill_value=0
        )

    def industry(self):
        raw_indu = self.raw[f'industry_{self.yymm[2:]}']
        raw_indu['cust_seg'] = raw_indu['cust_seg'].astype('string')
        raw_indu.info()
        raw_indu['cust_seg'] = raw_indu.apply(
            lambda row: 'Retail Client' if row['COUNTERPARTY_NEW_ISIC'] == 9000 else row['cust_seg'], axis=1
        )
        raw_indu['cust_seg'] = raw_indu.apply(
            lambda row: 'Business Clients' if row['COUNTERPARTY_NEW_ISIC'] == 9113 else row['cust_seg'], axis=1
        )
        condition = ((raw_indu['cust_seg'] == 'Business Clients') & (raw_indu['COUNTERPARTY_ORIGINAL_ISIC'] == 9000))
        raw_indu = raw_indu[~condition]

        raw_indu['balance'] = raw_indu.apply(
            lambda row: 0 if (row['cust_seg'] == 'XXX') & (row['COUNTERPARTY_ORIGINAL_ISIC'] == 8123) else row['balance'], axis=1
        )
        raw_indu['rwa'] = raw_indu.apply(
            lambda row: 0 if (row['cust_seg'] == 'XXX') & (row['COUNTERPARTY_ORIGINAL_ISIC'] == 8123) else row['rwa'], axis=1
        )
        raw_indu['balance'] = raw_indu.apply(
            lambda row: 0 if (row['cust_seg'] == 'XXX') & (row['COUNTERPARTY_ORIGINAL_ISIC'] == 8185) else row['balance'], axis=1
        )
        raw_indu['rwa'] = raw_indu.apply(
            lambda row: 0 if (row['cust_seg'] == 'XXX') & (row['COUNTERPARTY_ORIGINAL_ISIC'] == 8185) else row['rwa'], axis=1
        )
        raw_indu = raw_indu.merge(self.map_indu, how='left', on='COUNTERPARTY_ORIGINAL_ISIC')
        for col in self.cols:
            raw_indu[col] = raw_indu[col] / 1000

        cond = raw_indu['cust_seg'].isin(['Business Clients'])
        self.industry_table = pd.pivot_table(
            raw_indu[cond],
            values=self.cols,
            index='ISIC_mapping',
            aggfunc='sum', fill_value=0
        )

    def scorecard(self):
        raw_scorecard = self.raw[f'scorecard_{self.yymm[2:]}']
        raw_scorecard['cust_seg'] = raw_scorecard.apply(
            lambda row: 'Business Clients' if (row['cust_seg'] == 'XXX') & (pd.isna(row['SCORECARD'])) else row['cust_seg'], axis=1
        )
        raw_scorecard['balance'] = raw_scorecard.apply(
            lambda row: 0 if (row['cust_seg'] == 'XXX') & (row['SCORECARD'] == 'Bank') & (row['EXPOSURE_ATTRIBUTE_1'] == 'A') else row['balance'], axis=1
        )
        raw_scorecard['rwa'] = raw_scorecard.apply(
            lambda row: 0 if (row['cust_seg'] == 'XXX') & (row['SCORECARD'] == 'Bank') & (row['EXPOSURE_ATTRIBUTE_1'] == 'A') else row['rwa'], axis=1
        )

        raw_scorecard['balance'] = raw_scorecard.apply(
            lambda row: 0 if (row['cust_seg'] == 'XXX') & (row['SCORECARD'] == 'Funds') & (row['EXPOSURE_ATTRIBUTE_1'] == 'A') else row['balance'], axis=1
        )
        raw_scorecard['rwa'] = raw_scorecard.apply(
            lambda row: 0 if (row['cust_seg'] == 'XXX') & (row['SCORECARD'] == 'Funds') & (row['EXPOSURE_ATTRIBUTE_1'] == 'A') else row['rwa'], axis=1
        )
        raw_scorecard['balance'] = raw_scorecard.apply(
            lambda row: 0 if (row['EXPOSURE_ATTRIBUTE_1'] in ['CI-CCFCL_-KR', 'CI-CC____-KR']) else row['balance'], axis=1
        )
        raw_scorecard['rwa'] = raw_scorecard.apply(
            lambda row: 0 if (row['EXPOSURE_ATTRIBUTE_1'] in ['CI-CCFCL_-KR', 'CI-CC____-KR']) else row['rwa'], axis=1
        )

        raw_scorecard['SCORECARD'] = raw_scorecard.apply(
            lambda row: 'CORP' if (row['SCORECARD'] in ['Large Corporate', 'Middle Market', 'ME Corporate', 'SB/MB Corporate', 'CRE Investment Loans', 'Project Finance', 'Shipping Finance', 'Sole Proprietors Commercial', 'Other Corporate']) else row['SCORECARD'], axis=1
        )
        raw_scorecard['SCORECARD'] = raw_scorecard.apply(
            lambda row: 'NBFI' if (row['SCORECARD'] in ['Broker Dealer', 'Finance and Leasing', 'Fund Managers', 'Funds', 'Life Insurance', 'Non-Life Insurance']) else row['SCORECARD'], axis=1
        )
        raw_scorecard['SCORECARD'].fillna('CORP', inplace=True)
        cond = raw_scorecard['cust_seg'].isin(['Business Clients'])
        for col in self.cols:
            raw_scorecard[col] = raw_scorecard[col] / 1000

        self.scorecard_table = pd.pivot_table(
            raw_scorecard[~cond],
            values=self.cols,
            index='SCORECARD',
            aggfunc='sum', fill_value=0
        )


def generate_report(raw, yyyymm):
    """Local RIR (내부 리스크 정보 보고서).

    통합 raw(.xlsx, 다중 시트)와 기준년월(YYYYMM)을 받아 6개 결과 테이블을
    산출하여 단일 integrated_result.xlsx(다중 시트)로 저장한다.
    최종 파일명/경로는 기존 하드코딩 규칙을 그대로 따른다.
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
        _log("[1/7] 통합 raw 로드 중...")
        lrir = local_RIR(raw, yyyymm)
    except Exception as e:
        return _fail("통합 raw 로드", e)

    try:
        _log("[2/7] 포트폴리오(토스/BOND) 조정액 산출 중...")
        lrir.portfolio_data()
    except Exception as e:
        return _fail("포트폴리오 조정액 산출", e)

    try:
        _log("[3/7] CG 등급별 테이블 작성 중...")
        lrir.cg2_excl()
    except Exception as e:
        return _fail("CG 등급별 테이블", e)

    try:
        _log("[4/7] Product(BC/Retail) 테이블 작성 중...")
        lrir.Product_BC_retail()
    except Exception as e:
        return _fail("Product BC/Retail 테이블", e)

    try:
        _log("[5/7] 업종별 테이블 작성 중...")
        lrir.industry()
    except Exception as e:
        return _fail("업종별 테이블", e)

    try:
        _log("[6/7] 스코어카드 테이블 작성 중...")
        lrir.scorecard()
    except Exception as e:
        return _fail("스코어카드 테이블", e)

    try:
        _log("[7/7] 결과 저장 중...")
        outfile = f'C:/Users/1598505/OneDrive - Standard Chartered Bank/1.보고서(WB)/3.Internal/1.Local RIR/{lrir.yymm[2:]}/기초데이터/integrated_result.xlsx'

        with pd.ExcelWriter(outfile, engine='openpyxl') as writer:
            if lrir.cg_table1 is not None:
                lrir.cg_table1.to_excel(writer, sheet_name='cg_table1', index=True)
            if lrir.cg_table2 is not None:
                lrir.cg_table2.to_excel(writer, sheet_name='cg_table2', index=True)
            if lrir.ccib_prod is not None:
                lrir.ccib_prod.to_excel(writer, sheet_name='ccib_prod', index=True)
            if lrir.wrb_prod is not None:
                lrir.wrb_prod.to_excel(writer, sheet_name='wrb_prod', index=True)
            if lrir.industry_table is not None:
                lrir.industry_table.to_excel(writer, sheet_name='industry_table', index=True)
            if lrir.scorecard_table is not None:
                lrir.scorecard_table.to_excel(writer, sheet_name='scorecard_table', index=True)
    except Exception as e:
        return _fail("결과 저장", e)

    _log(f"[완료] Local RIR 작성 완료: {outfile}")
    return {'ok': True, 'log': "\n".join(logs), 'outfile': outfile}
