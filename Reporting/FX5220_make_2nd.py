import pandas as pd
from datetime import datetime

dt = str(input('날짜를 yyyymmdd 형식으로 입력해주세요'))

dt_trans = datetime.strptime(dt, '%Y%m%d')

path = input('이번 기준년월 파일의 경로를 입력해주세요')
file = input('이번 기준년월 파일명을 /file_name.csv 형식으로 입력해주세요')
path_file = path+file
raw = pd.read_csv(path_file,sep=',')
raw_copied = raw.copy()
raw_copied.rename(columns={raw_copied.columns[0] : '계좌번호'}, inplace=True)

bf_path = input('지난 기준년월 파일의 경로를 입력해주세요')
bf_file = input('지난 기준년월 파일명을 /file_name.csv 형식으로 입력해주세요')
bf_path_file = bf_path+bf_file
bf_raw = pd.read_csv(bf_path_file,sep=',')
bf_raw_copied = bf_raw[['계좌번호','업종',	'기업규모',	'용도',	'담당자']].copy()

new_path = input('이번 기준년월 신규 외화 여신 회신 받은 파일의 경로를 입력해주세요')
new_file = input('이번 기준년월 신규 외화 여신 회신 받은 파일명을 /file_name.csv 형식으로 입력해주세요')
new_path_file = new_path+new_file
new_raw_response = pd.read_csv(new_path_file,sep=',')
new_raw_response_copied = new_raw_response.copy()

raw_merged = raw_copied.merge(bf_raw_copied, how='left', on='계좌번호')

null_condition = raw_merged['담당자'].isnull()
rm_info = pd.concat([raw_merged[~null_condition],new_raw_response_copied.drop(['base_dt'],axis=1)], axis=0)
out_path = input('rm_info 파일을 저장하는 경로를 입력해주세요')
out_file = input('rm_info 파일명을 /file_name.csv 형식으로 입력해주세요')
out_path_file = out_path+out_file
rm_info.to_csv(out_path_file, index=False, encoding='utf-8-sig')

file_list = [raw_merged,new_raw_response_copied]

for file in file_list:
    
    file['exec_amt'] = file['exec_amt'].astype('string').str.replace(',','').astype('float')
    file['실행금액(US)'] = file['실행금액(US)'].astype('string').str.replace(',','').astype('float')
    file['pybck_amt'] = file['pybck_amt'].astype('string').str.replace(',','').astype('float')
    file['회수금액(US)'] = file['회수금액(US)'].astype('string').str.replace(',','').astype('float')
    file['loan_asst_bs_amt'] = file['loan_asst_bs_amt'].astype('string').str.replace(',','').astype('float')
    file['잔액(US)'] = file['잔액(US)'].astype('string').str.replace(',','').astype('float')
            
    file['loan_deadln_dt'] = file['loan_deadln_dt'].astype('string').str.replace('-','')
    file['loan_deadln_dt'] = pd.to_datetime(file['loan_deadln_dt'],format='%Y%m%d')
    
    file['new_start_dt'] = file['new_start_dt'].astype('string').str.replace('-','')
    file['new_start_dt'] = pd.to_datetime(file['new_start_dt'],format='%Y%m%d')
    
    file['maturity1'] = file['loan_deadln_dt']-file['new_start_dt']
    file['maturity2'] = file['loan_deadln_dt']-dt_trans
    
    file['maturity1_gb'] = 0
    for i in range(len(file['maturity1'])):
        if file.loc[i,'maturity1'].days<91:
            file.loc[i,'maturity1_gb']=1
        elif file.loc[i,'maturity1'].days<186:
            file.loc[i,'maturity1_gb']=2
        elif file.loc[i,'maturity1'].days<371:
            file.loc[i,'maturity1_gb']=3        
        elif file.loc[i,'maturity1'].days<741:
            file.loc[i,'maturity1_gb']=4
        else:
            file.loc[i,'maturity1_gb']=5
    
    file['maturity2_gb'] = 0
    for i in range(len(file['maturity2'])):
        if file.loc[i,'maturity2'].days<91:
            file.loc[i,'maturity2_gb']=1
        elif file.loc[i,'maturity2'].days<186:
            file.loc[i,'maturity2_gb']=2
        elif file.loc[i,'maturity2'].days<371:
            file.loc[i,'maturity2_gb']=3        
        elif file.loc[i,'maturity2'].days<741:
            file.loc[i,'maturity2_gb']=4
        else:
            file.loc[i,'maturity2_gb']=5


from pandas.api.types import CategoricalDtype

seg_order = ['CIB','SME','IND','etc']
raw_copied['seg'] = raw_copied['seg'].astype(CategoricalDtype(categories=seg_order, ordered=True))

from pandas.api.types import CategoricalDtype
seg_order = ['대기업','중소기업']
indu_order = ['제조업','비제조업']

raw_merged = raw_merged[['maturity1_gb','maturity2_gb','crncy_cd','실행금액(US)','기업규모','업종','용도','회수금액(US)','잔액(US)']]

raw_merged['기업규모'] = raw_merged['기업규모'].astype(CategoricalDtype(categories=seg_order, ordered=True))
raw_merged['업종'] = raw_merged['업종'].astype(CategoricalDtype(categories=indu_order, ordered=True))


from pandas.api.types import CategoricalDtype
seg_order = ['대기업','중소기업']
indu_order = ['제조업','비제조업']

new_raw_response_copied = new_raw_response_copied[['maturity1_gb','maturity2_gb','crncy_cd','실행금액(US)','기업규모','업종','용도','회수금액(US)','잔액(US)']]

new_raw_response_copied['기업규모'] = new_raw_response_copied['기업규모'].astype(CategoricalDtype(categories=seg_order, ordered=True))
new_raw_response_copied['업종'] = new_raw_response_copied['업종'].astype(CategoricalDtype(categories=indu_order, ordered=True))

new_raw_response_copied.info()

new_condition = raw_merged['실행금액(US)']>0
raw_old=raw_merged[~new_condition]

merged_data = pd.concat([raw_old, new_raw_response_copied], ignore_index=True, axis=0) 


new_condition = merged_data['실행금액(US)']>0
raw_new=merged_data[new_condition]

raw_new_pivot_1st = pd.pivot_table(
        raw_new
        ,values = '실행금액(US)'
        ,index = 'crncy_cd'
        ,columns = ['기업규모','업종']
        ,aggfunc='sum'
        ,fill_value=0)

raw_new_pivot_2nd = pd.pivot_table(
        raw_new
        ,values = '실행금액(US)'
        ,index = '용도'
        ,columns = ['기업규모','업종']
        ,aggfunc='sum'
        ,fill_value=0)

pybck_condition = merged_data['회수금액(US)']>0
raw_pybck=merged_data[pybck_condition]

raw_pybck_pivot_1st = pd.pivot_table(
        raw_pybck
        ,values = '회수금액(US)'
        ,index = 'crncy_cd'
        ,columns = ['기업규모','업종']
        ,aggfunc='sum'
        ,fill_value=0)

raw_pybck_pivot_2nd = pd.pivot_table(
        raw_pybck
        ,values = '회수금액(US)'
        ,index = '용도'
        ,columns = ['기업규모','업종']
        ,aggfunc='sum'
        ,fill_value=0)


raw_merged_pivot_1st = pd.pivot_table(
        merged_data
        ,values = '잔액(US)'
        ,index = 'crncy_cd'
        ,columns = ['기업규모','업종']
        ,aggfunc='sum'
        ,fill_value=0)

raw_merged_pivot_2nd = pd.pivot_table(
        merged_data
        ,values = '잔액(US)'
        ,index = '용도'
        ,columns = ['기업규모','업종']
        ,aggfunc='sum'
        ,fill_value=0)

raw_mature_pivot_1st = pd.pivot_table(
        merged_data
        ,values = '잔액(US)'
        ,index = 'maturity1_gb'
        ,columns = ['기업규모','업종']
        ,aggfunc='sum'
        ,fill_value=0)

raw_mature_pivot_2nd = pd.pivot_table(
        merged_data
        ,values = '잔액(US)'
        ,index = 'maturity1_gb'
        ,columns = ['기업규모','업종']
        ,aggfunc='sum'
        ,fill_value=0)

print('최종 피벗테이블 결과가 출력됩니다...')
print(raw_new_pivot_1st)
print('-'*60)
print(raw_new_pivot_2nd)
print('-'*60)
print(raw_pybck_pivot_1st)
print('-'*60)
print(raw_pybck_pivot_2nd)
print(raw_merged_pivot_1st)
print('-'*60)
print(raw_merged_pivot_2nd)
print('-'*60)
print(raw_mature_pivot_1st)
print('-'*60)
print(raw_mature_pivot_2nd)
print('최종 피벗테이블을 제출 양식에 복사-붙여넣기 하세요')