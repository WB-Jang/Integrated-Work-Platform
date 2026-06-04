import pandas as pd

from pandas.api.types import CategoricalDtype

class local_RIR():
    def __init__(self):
        self.bfyymm = input('지난 기준년월을 ' \
        'YYMM 형식으로 입력하세요 : ')
        self.yymm = input('이번 기준년월을 YYMM 형식으로 입력하세요 : ')
        raw_cg2_excl = pd.read_csv(f"C:/Users/1598505/OneDrive - Standard Chartered Bank/1.보고서(WB)/3.Internal/1.Local RIR/{self.yymm}/기초데이터/data/cg2_excl_{self.yymm}.csv",sep=',',encoding='euc-kr')
        self.raw_portfolio_data = pd.read_csv(f"C:/Users/1598505/OneDrive - Standard Chartered Bank/1.보고서(WB)/3.Internal/1.Local RIR/{self.yymm}/기초데이터/data/portfolio_data_{self.yymm}.csv",sep=',',encoding='euc-kr')
        self.map = pd.read_csv(f"C:/Users/1598505/OneDrive - Standard Chartered Bank/1.보고서(WB)/3.Internal/1.Local RIR/{self.yymm}/기초데이터/data/product_mapping.csv",sep=',',encoding='utf-8-sig')
        raw_cg2_excl['base_dt']=self.yymm
        self.raw_Product_BC_retail = pd.read_csv(f"C:/Users/1598505/OneDrive - Standard Chartered Bank/1.보고서(WB)/3.Internal/1.Local RIR/{self.yymm}/기초데이터/data/product_bc_retail_{self.yymm}.csv",sep=',',encoding='euc-kr')
        
        
        print(raw_cg2_excl[raw_cg2_excl['cg']=='02'])
        print(raw_cg2_excl['cg'][30:60])
        self.df = raw_cg2_excl
        self.cgs = [['01','02','03','04','05'], ['06','07','08'], ['09','10','11'], ['12'], ['13','14']]
        self.cg_nms = ['1~5','6~8','9~11','12','13~14']
        for idx in range(len(self.df['cg'])):
            for i, cg in enumerate(self.cgs):
                
                if self.df.loc[idx,'cg'] in cg:
                    self.df.loc[idx,'cg_group'] = self.cg_nms[i]
                    
                 
        self.df['cg_group'].fillna('SA, Default(RB)', inplace=True)
        self.cols = ['balance','rwa']
        self.condition = (self.df['cust_seg']=='XXX')&(self.df['METHOD_NEW']=='STD')&(self.df['EXPOSURE_ATTRIBUTE_3'].isnull())
        

        

    # def configs(self):
        
    def portfolio_data(self):
        raw_portfolio_data = self.raw_portfolio_data
        raw_filtered1 = raw_portfolio_data[(raw_portfolio_data['cust_seg2']=='XXX')&(raw_portfolio_data['COUNTERPARTY_NEW']=='토스뱅크주식회사')]
        raw_filtered2 = raw_portfolio_data[(raw_portfolio_data['cust_seg2']=='XXX')&(raw_portfolio_data['COUNTERPARTY_NEW']=='BOND MARKET STABILIZATION FUND')]
        amt_toss =raw_filtered1[['sum_bal','sum_RWA']]
        amt_bond =raw_filtered2[['sum_bal','sum_RWA']]
        return amt_toss, amt_bond
    
    
    def cg2_excl(self):        
    
        amt_toss, amt_bond = self.portfolio_data()
        df = self.df
      
        for col in self.cols:
            df[col] = df[col].astype(str).replace(',','').astype('float64')
            
        new = df[self.condition]
        

        for idx,col in enumerate(self.cols):
            new[col] = new[col]-amt_toss.iloc[0,idx]-amt_bond.iloc[0,idx]
        
        
        
        base = df[~self.condition]
        
        base['cust_seg'] = base.apply(
            lambda row: 'WRB' if row['cust_seg'] in ['XXX','Business Clients'] else 'CCIB', axis=1 # 여기서 row는 row 단위로 작동한다는 의미
            )
        # base['cust_seg'] = base['cust_seg'].replace('XXX', 'Business Clients')

        final_raw = pd.concat([base,new], ignore_index=True)
        

        final_raw['cust_seg'] = final_raw.apply(
            lambda row: 'CCIB' if row['cust_seg'] in ['XXX'] else row['cust_seg'], axis=1 # 여기서 row는 row 단위로 작동한다는 의미
            )
        cg_order = ['01','02','03','04','05','06','07','08','09','10','11','12','13-14','ST','DE']
        final_raw['cg'] = final_raw['cg'].astype(CategoricalDtype(categories=cg_order, ordered=True))
        cg_group_order = ['1~5','6~8','9~11','12','13~14','SA, Default(RB)']
        final_raw['cg_group'] = final_raw['cg_group'].astype(CategoricalDtype(categories=cg_group_order, ordered=True))

        final_table = pd.pivot_table(
        final_raw
        ,values = self.cols
        ,index = 'cg'
        ,aggfunc='sum'
        ,fill_value=0)
        

        final_table2 = pd.pivot_table(
        final_raw
        ,values = self.cols
        ,index = ['cg_group','cust_seg']
        ,aggfunc='sum'
        ,fill_value=0)
        
        for col in self.cols:
            final_table[col]=final_table[col]/1000
        for col in self.cols:
            final_table2[col]=final_table2[col]/1000
    

        
        final_table.to_csv(f'C:/Users/1598505/OneDrive - Standard Chartered Bank/1.보고서(WB)/3.Internal/1.Local RIR/{self.yymm}/기초데이터/result/CG_result1.csv', index=True, encoding='utf-8-sig')
        final_table2.to_csv(f'C:/Users/1598505/OneDrive - Standard Chartered Bank/1.보고서(WB)/3.Internal/1.Local RIR/{self.yymm}/기초데이터/result/CG_result2.csv', index=True, encoding='utf-8-sig')
      
        return final_table
    

    
    
    def Product_BC_retail(self):
        segs = ['XXX','Commercial Clients','Corporate & Institutional Clients','Own Account']
        seg = ['Business Clients']
        map = self.map
        raw_Product_BC_retail = self.raw_Product_BC_retail
        raw_Product_BC_retail['base_dt']=self.yymm
        raw_Product_BC_retail.loc[(raw_Product_BC_retail['cust_seg']=='XXX')&(raw_Product_BC_retail['Product_Desc'].isnull()),'cust_seg']='Business Clients'
        
        amt_toss, amt_bond = self.portfolio_data()
        
        for idx,col in enumerate(self.cols):
            raw_Product_BC_retail.loc[(raw_Product_BC_retail['cust_seg']=='XXX')&(raw_Product_BC_retail['PSGL_PRDCT_CD']==731),col]=raw_Product_BC_retail.loc[(raw_Product_BC_retail['cust_seg']=='XXX')&(raw_Product_BC_retail['PSGL_PRDCT_CD']==731),col]-amt_bond.iloc[0,idx]
        for idx,col in enumerate(self.cols):
            raw_Product_BC_retail.loc[(raw_Product_BC_retail['cust_seg']=='XXX')&(raw_Product_BC_retail['PSGL_PRDCT_CD']==740),col]=raw_Product_BC_retail.loc[(raw_Product_BC_retail['cust_seg']=='XXX')&(raw_Product_BC_retail['PSGL_PRDCT_CD']==740),col]-amt_toss.iloc[0,idx]
        merged_raw = raw_Product_BC_retail.merge(map, how='left', on='oltp_acct_sbjct_cd')
        
        merged_raw.loc[(merged_raw['cust_seg'].isin(seg))&(merged_raw['RB_prod'].isnull()),'RB_prod'] = merged_raw.loc[(merged_raw['cust_seg'].isin(seg))&(merged_raw['RB_prod'].isnull()),'RB_prod_new']
        merged_raw.drop_duplicates(inplace=True)
        prod_list = [['Drim','분할상환대출'],['Sele','리볼빙대출'],['Cred','신용카드'],['O_Un','신용여신기타'],['FHL','퍼스트홈론'],\
                     ['WML','퍼스트홈론잔금'],['KFHL','공사모기지론'],['O_Se','담보여신기타'],\
                     ['BIL','중소기업분할상환대출'],['Mort','SME비즈니스모기지'],['GIL','보증서담보대출'],['XX','무역및운전자금대출']]
        
        for l in prod_list:
            e, k = l
            print(e,k)
            merged_raw['RB_prod'] = merged_raw.apply(
            lambda row: k if (row['RB_prod'] in [e]) else row['RB_prod'], axis=1 # 여기서 row는 row 단위로 작동한다는 의미
            )
        
        final_table = pd.pivot_table(
            raw_Product_BC_retail[raw_Product_BC_retail['cust_seg'].isin(segs)]
            ,values=self.cols
            ,index='Product_Desc',columns='base_dt'
            ,aggfunc='sum',fill_value=0
        )
        final_table2 = pd.pivot_table(
            merged_raw[merged_raw['cust_seg'].isin(seg)]
            ,values=self.cols
            ,index='RB_prod',columns='base_dt'
            ,aggfunc='sum',fill_value=0
        )
        for col in self.cols:
            final_table[col]=final_table[col]/1000
        for col in self.cols:
            final_table2[col]=final_table2[col]/1000

        final_table.to_csv(f'C:/Users/1598505/OneDrive - Standard Chartered Bank/1.보고서(WB)/3.Internal/1.Local RIR/{self.yymm}/기초데이터/result/CIB_prod_result.csv', index=True, encoding='utf-8-sig')
        final_table2.to_csv(f'C:/Users/1598505/OneDrive - Standard Chartered Bank/1.보고서(WB)/3.Internal/1.Local RIR/{self.yymm}/기초데이터/result/SME_prod_result.csv', index=True, encoding='utf-8-sig')
        
        
    
        return raw_Product_BC_retail
        
    
    def industry(self):
        raw_indu = pd.read_csv(f"C:/Users/1598505/OneDrive - Standard Chartered Bank/1.보고서(WB)/3.Internal/1.Local RIR/{self.yymm}/기초데이터/data/industry_{self.yymm}.csv",sep=',',encoding='euc-kr')
        raw_indu['cust_seg'] = raw_indu['cust_seg'].astype('string')
        print(raw_indu.info())
        raw_indu['cust_seg'] = raw_indu.apply(
            lambda row: 'Retail Client' if row['COUNTERPARTY_NEW_ISIC']==9000 else row['cust_seg'], axis=1 # 여기서 row는 row 단위로 작동한다는 의미
            )
        raw_indu['cust_seg'] = raw_indu.apply(
            lambda row: 'Business Clients' if row['COUNTERPARTY_NEW_ISIC']==9113 else row['cust_seg'], axis=1 # 여기서 row는 row 단위로 작동한다는 의미
            )
        condition = ((raw_indu['cust_seg']=='Business Clients')&(raw_indu['COUNTERPARTY_ORIGINAL_ISIC']==9000))
        raw_indu = raw_indu[~condition]
        amt_toss, amt_bond = self.portfolio_data()
        print(amt_toss)
        print(type(amt_toss))
        print(amt_toss['sum_bal'])
        print(type(amt_toss['sum_bal']))
        print(amt_toss['sum_bal'].astype('float')) # 타입만 바꿔주지 여전히 시리즈임
        print(type(amt_toss['sum_bal'].astype('float')))
        print(float(amt_toss['sum_bal'].item())) # item()을 사용하면, 시리즈 내의 1개의 원소만 있을 경우 밖으로 빼내어서 스칼라로 변경해줌
        print(type(float(amt_toss['sum_bal'].item())))
        raw_indu['balance'] = raw_indu.apply(
            lambda row: 0 if (row['cust_seg']=='XXX')&(row['COUNTERPARTY_ORIGINAL_ISIC']==8123) else row['balance'], axis=1 # 여기서 row는 row 단위로 작동한다는 의미
            )
        raw_indu['rwa'] = raw_indu.apply(
            lambda row: 0 if (row['cust_seg']=='XXX')&(row['COUNTERPARTY_ORIGINAL_ISIC']==8123) else row['rwa'], axis=1 # 여기서 row는 row 단위로 작동한다는 의미
            )
        raw_indu['balance'] = raw_indu.apply(
            lambda row: 0 if (row['cust_seg']=='XXX')&(row['COUNTERPARTY_ORIGINAL_ISIC']==8185) else row['balance'], axis=1 # 여기서 row는 row 단위로 작동한다는 의미
            )
        raw_indu['rwa'] = raw_indu.apply(
            lambda row: 0 if (row['cust_seg']=='XXX')&(row['COUNTERPARTY_ORIGINAL_ISIC']==8185) else row['rwa'], axis=1 # 여기서 row는 row 단위로 작동한다는 의미
            )
        map = pd.read_csv(f"C:/Users/1598505/OneDrive - Standard Chartered Bank/1.보고서(WB)/3.Internal/1.Local RIR/{self.yymm}/기초데이터/data/industry_mapping.csv",sep=',',encoding='utf-8-sig')
        raw_indu = raw_indu.merge(map, how='left', on='COUNTERPARTY_ORIGINAL_ISIC')
        cond = raw_indu['cust_seg'].isin(['Business Clients'])
        final_table = pd.pivot_table(
            raw_indu[cond]
            ,values=self.cols
            ,index='ISIC_mapping'
            ,aggfunc='sum',fill_value=0
        )
        for col in self.cols:
            final_table[col]=final_table[col]/1000
        final_table.to_csv(f'C:/Users/1598505/OneDrive - Standard Chartered Bank/1.보고서(WB)/3.Internal/1.Local RIR/{self.yymm}/기초데이터/result/industry_result.csv', index=True, encoding='utf-8-sig')
    def scorecard(self):
        raw_scorecard = pd.read_csv(f"C:/Users/1598505/OneDrive - Standard Chartered Bank/1.보고서(WB)/3.Internal/1.Local RIR/{self.yymm}/기초데이터/data/SCORECARD_{self.yymm}.csv",sep=',',encoding='euc-kr')
        raw_scorecard['cust_seg'] = raw_scorecard.apply(
            lambda row: 'Business Clients' if (row['cust_seg']=='XXX')&(pd.isna(row['SCORECARD'])) else row['cust_seg'], axis=1 # 여기서 row는 row 단위로 작동한다는 의미
            )
        raw_scorecard['balance'] = raw_scorecard.apply(
            lambda row: 0 if (row['cust_seg']=='XXX')&(row['SCORECARD']=='Bank')&(row['EXPOSURE_ATTRIBUTE_1']=='A') else row['balance'], axis=1 # 여기서 row는 row 단위로 작동한다는 의미
            )
        raw_scorecard['rwa'] = raw_scorecard.apply(
            lambda row: 0 if (row['cust_seg']=='XXX')&(row['SCORECARD']=='Bank')&(row['EXPOSURE_ATTRIBUTE_1']=='A') else row['rwa'], axis=1 # 여기서 row는 row 단위로 작동한다는 의미
            )
        
        raw_scorecard['balance'] = raw_scorecard.apply(
            lambda row: 0 if (row['cust_seg']=='XXX')&(row['SCORECARD']=='Funds')&(row['EXPOSURE_ATTRIBUTE_1']=='A') else row['balance'], axis=1 # 여기서 row는 row 단위로 작동한다는 의미
            )
        raw_scorecard['rwa'] = raw_scorecard.apply(
            lambda row: 0 if (row['cust_seg']=='XXX')&(row['SCORECARD']=='Funds')&(row['EXPOSURE_ATTRIBUTE_1']=='A') else row['rwa'], axis=1 # 여기서 row는 row 단위로 작동한다는 의미
            )
        raw_scorecard['balance'] = raw_scorecard.apply(
            lambda row: 0 if (row['EXPOSURE_ATTRIBUTE_1'] in['CI-CCFCL_-KR','CI-CC____-KR']) else row['balance'], axis=1 # 여기서 row는 row 단위로 작동한다는 의미
            )
        raw_scorecard['rwa'] = raw_scorecard.apply(
            lambda row: 0 if (row['EXPOSURE_ATTRIBUTE_1'] in ['CI-CCFCL_-KR','CI-CC____-KR']) else row['rwa'], axis=1 # 여기서 row는 row 단위로 작동한다는 의미
            )
                
        
        raw_scorecard['SCORECARD'] = raw_scorecard.apply(
            lambda row: 'CORP' if (row['SCORECARD'] in ['Large Corporate','Middle Market','ME Corporate','SB/MB Corporate','CRE Investment Loans','Project Finance','Shipping Finance','Sole Proprietors Commercial','Other Corporate']) else row['SCORECARD'], axis=1 # 여기서 row는 row 단위로 작동한다는 의미
            )
        raw_scorecard['SCORECARD'] = raw_scorecard.apply(
            lambda row: 'NBFI' if (row['SCORECARD'] in ['Broker Dealer','Finance and Leasing','Fund Managers','Funds','Life Insurance','Non-Life Insurance']) else row['SCORECARD'], axis=1 # 여기서 row는 row 단위로 작동한다는 의미
            )
        raw_scorecard['SCORECARD'].fillna('CORP', inplace=True)
        cond = raw_scorecard['cust_seg'].isin(['Business Clients'])
        final_table = pd.pivot_table(
            raw_scorecard[~cond]
            ,values=self.cols
            ,index='SCORECARD'
            ,aggfunc='sum',fill_value=0
        )
        for col in self.cols:
            final_table[col]=final_table[col]/1000
        final_table.to_csv(f'C:/Users/1598505/OneDrive - Standard Chartered Bank/1.보고서(WB)/3.Internal/1.Local RIR/{self.yymm}/기초데이터/result/scorecard_result.csv', index=True, encoding='utf-8-sig')
        
    
def generate_report():
    local_rir = local_RIR()
    result = local_rir.cg2_excl()
    result2 = local_rir.Product_BC_retail()
    result3 = local_rir.industry()
    result4 = local_rir.scorecard()

    
    

if __name__ == "__main__":
    print('---다음의 요건들을 확인하세요---')
    print('저장된 폴더 : C:/Users/1598505/OneDrive - Standard Chartered Bank/1.보고서(WB)/3.Internal/1.Local RIR/yymm/기초데이터/data')
    print('저장된 파일 이름 : portfolio_data_yyyymm.csv, cg2_excl_yymm.csv, product_bb_retail_yymm.csv', 'industry_yymm')
    print('결과 파일 이름 : cg_table_yymm.csv, cg_table2_yymm.csv, product_yymm.csv, product_yymm2.csv')
    
    
    generate_report()
    


