import pandas as pd

base_yymm = int(input('기준년월을 YYYYMM 형식으로 입력해주세요 : '))
path = input('해당 기준년월의 FX5260 파일이 위치한 경로를 입력해주세요. 단 역슬래쉬를 슬래쉬로 변경해주세요 : ')
file_sql = input('FX5260 쿼리문을 실행한 결과 .csv 파일 명을 /file.csv 형태로 입력해주세요 : ')
path_file_sql = path+file_sql
raw = pd.read_csv(path_file_sql,sep=',', encoding = 'euc-kr')

file_crms = input('테크비즈니스지원부로부터 전달 받은 외화 대출 .csv 파일 명을 /file.csv 형태로 입력해주세요 : ')
path_file_crms = path+file_crms
raw_crms = pd.read_csv(path_file_crms,sep=',',encoding = 'euc-kr')

file_seq = input('테크비즈니스지원부로부터 전달 받은 외화 대출 seq .csv 파일 명을 /file.csv 형태로 입력해주세요 : ')
path_file_seq = path+file_seq
raw_seq = pd.read_csv(path_file_seq,sep=',', encoding = 'utf-8-sig')

raw_copied = raw.copy()
object_list = raw_copied.select_dtypes(include='object').columns.tolist()

for col in object_list:
    raw_copied[col] = raw_copied[col].astype('string')
    print(f'{col} 컬럼이 string 타입으로 변환되었습니다')

dt_col = []
for col in raw_copied.columns.tolist():
    if col[2:] == 'dt':
        dt_col.append(col)
        raw_copied[col] = pd.to_datetime(raw_copied[col], format='%d%b%Y',errors='coerce')
        raw_copied[col] = raw_copied[col].dt.strftime('%Y-%m-%d')
        print(f'{col} 컬럼은 날짜이며, datetime 형식으로 변환되었습니다')


raw_copied['ssn_corpno'] = raw_copied['ssn_corpno'].astype('string')

raw_merged = raw_crms.merge(raw_seq, how='left', left_index=True, right_index=True) # index 기준으로 merge 
raw_merged[['고객명','고객SEQ명']].head()

raw_merged = raw_crms.merge(raw_seq, how='left',  left_index=True, right_index=True)
raw_merged['주민법인번호'] = raw_merged['주민법인번호'].str[:6]
raw_merged['ssn_corpno'] = raw_merged['주민법인번호']+raw_merged['주민법인SEQ번호']

raw_merged['acct_no'] = raw_merged['계좌번호'].str[:5]+raw_merged['계좌SEQ번호']


raw_merged['고객명'] = raw_merged['고객명'].str[:2]
raw_merged['client_nm'] = raw_merged['고객명']+raw_merged['고객SEQ명']

raw_merged['취급년월일'] = raw_merged['취급년월일'].str.replace('-','').str[:6].astype('string')
raw_merged['취급년월일'] = raw_merged['취급년월일'].replace('','999999').astype('int')


raw_crms_filtered = raw_merged[raw_merged['계정과목코드'].isin([746,747,748,768,780])]
raw_crms_filtered=raw_crms_filtered[raw_crms_filtered['취급년월일']==base_yymm]
raw_crms_filtered=raw_crms_filtered[raw_crms_filtered['약정계정구분_x']=='-']
raw_crms_filtered = raw_crms_filtered.reset_index()

fix_int_cd = [748, 780] 
for idx in range(len(raw_crms_filtered)):
    if raw_crms_filtered.loc[idx,'계정과목코드'] in fix_int_cd:
        raw_crms_filtered.loc[idx,'int_type'] = 'fix'        
        raw_crms_filtered.loc[idx,'interest_amt_fix'] = raw_crms_filtered.loc[idx,'미화환산잔액']*(raw_crms_filtered.loc[idx,'대출이율']/100)
    else:
        raw_crms_filtered.loc[idx,'int_type'] = 'var'
        print(raw_crms_filtered.loc[idx,'acct_no'])
        raw_crms_filtered.loc[idx,'new_interest_var']=float(input('금리를 소수점 둘째자리까지 입력해주세요'))
        raw_crms_filtered.loc[idx,'interest_amt_var']=raw_crms_filtered.loc[idx,'미화환산잔액']*(raw_crms_filtered.loc[idx,'new_interest_var']/100)
print("---고정/변동 금리 구분 완료 ---")
if raw_crms_filtered[raw_crms_filtered['int_type']=='var']['int_type'].any():
    print('--- 변동금리 계좌번호와 이자율, 이자금액입니다')
    print(raw_crms_filtered[raw_crms_filtered['int_type']=='var'].loc[:,['acct_no','new_interest_var','interest_amt_var']])
    print('------------------------------------------')
else:
    print(f"---{base_yymm} 기준 변동금리 계좌가 없습니다---") 
    pass

if raw_crms_filtered[raw_crms_filtered['int_type']=='var']['int_type'].any():
    raw_crms_pivot = pd.pivot_table(
            raw_crms_filtered
            ,values = ['미화환산잔액', 'interest_amt_fix', 'interest_amt_var']
            ,index = ['ssn_corpno','client_nm']
            ,aggfunc='sum'
            ,fill_value=0)
else:
    raw_crms_pivot = pd.pivot_table(
            raw_crms_filtered
            ,values = ['미화환산잔액', 'interest_amt_fix']
            ,index = ['ssn_corpno','client_nm']
            ,aggfunc='sum'
            ,fill_value=0)
    raw_crms_pivot['interest_amt_var']=0.0    
    print("--- pivot table 완성 ---")

raw_crms_pivot = raw_crms_pivot[raw_crms_pivot['미화환산잔액']>1000000]
raw_crms_pivot.sort_values(by='미화환산잔액', ascending=False, inplace=True)
raw_crms_pivot.reset_index(inplace=True)
print(raw_crms_pivot)

merged_v2 = raw_copied.merge(raw_crms_pivot, how='left', on='ssn_corpno')

merged_v2['corp_bond_nice_crdt_grade'].fillna('BB',inplace=True)
invst_grade = ['AAA+','AAA','AAA-','AA+','AA','AA-','A+','A','A-','BBB+','BBB','BBB-'] 
for idx in range(len(merged_v2['corp_bond_nice_crdt_grade'])):
    if merged_v2.loc[idx,'corp_bond_nice_crdt_grade'] in invst_grade:
        merged_v2.loc[idx,'투자투기등급구분코드'] = 1
    else:
        merged_v2.loc[idx,'투자투기등급구분코드'] = 2

ntnl_cd_map = {100:'KR', 193:'', 131:'TH', 193:'CN', 621:'EG'}
merged_v2['차주국가코드'] = merged_v2['ntnl_cd1'].map(ntnl_cd_map).fillna('N/A').astype('string')
merged_v2['차주소재지국가코드'] = merged_v2['ntnl_cd2'].map(ntnl_cd_map).fillna('N/A').astype('string')

merged_v2['취급점포코드'] = str('023')
merged_v2['부점명'] = '리스크관리부'
merged_v2['취급점포소재지식별번호'] = str('03160')
merged_v2['전송구분코드'] = '1'
merged_v2['관리번호'] = ''
merged_v2['취급일자'] = merged_v2['i_dt'].str.replace('-','')
merged_v2['차주명'] = merged_v2['client_nm'].str[:10]
merged_v2['만기일자'] = merged_v2['e_dt'].str.replace('-','')
merged_v2['대출유형코드'] = merged_v2['<CASE  expression>'].astype('string').str.zfill(2)
merged_v2['고정금리'] = ((merged_v2['interest_amt_fix']/merged_v2['미화환산잔액'])*100).round(2)
merged_v2['변동금리'] = ((merged_v2['interest_amt_var']/merged_v2['미화환산잔액'])*100).round(2)
merged_v2['금액'] = (merged_v2['미화환산잔액']/1000).round(0)
merged_v2['작성자직책명'] = str(input('작성자 직책을 입력해주세요 : '))
merged_v2['작성자명'] = str(input('작성자 성명을 입력해주세요 : '))
merged_v2['작성자전화번호'] = str(input('작성자 전화번호를 - 없이 입력해주세요 : '))

cols_for_report = ['취급점포코드','부점명','취급점포소재지식별번호','전송구분코드','관리번호','취급일자','차주명','차주국가코드','차주소재지국가코드','투자투기등급구분코드','만기일자',\
                   '대출유형코드','고정금리','변동금리','금액','작성자직책명','작성자명','작성자전화번호'
                  ]
final_report = merged_v2[cols_for_report]
final_report.head(10)

file = input('최종결과파일명을 /file.csv 형식으로 기입해주세요 : ')
path_file = path+file
final_report.to_csv(path_file, encoding = 'utf-8-sig', quoting=1)