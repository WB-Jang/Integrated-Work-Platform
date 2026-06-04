import pandas as pd

mortgage_loan = float(input('TIS - 대외보고업무 - 금융감독원보고서 - 일별잔액 - 주택담보대출 금액을 억원원 단위로 소수점 둘째자리까지 입력해주세요 : '))

bf_path = input('지난 기준일 파일(15번쿼리)의 경로를 입력해주세요 : ')
bf_file = input('지난 기준일 파일(15번쿼리)명을 /file_name.csv 형식으로 입력해주세요 : ')
bf_path_file = bf_path+bf_file 
bf_raw_15 = pd.read_csv(bf_path_file, sep =',', encoding='euc-kr')

path = input('이번 기준일 파일(15번쿼리)의 경로를 입력해주세요 : ')
file = input('이번 기준일 파일(15번쿼리)명을 /file_name.csv 형식으로 입력해주세요 : ')
path_file = path+file
raw_15 = pd.read_csv(path_file, sep =',', encoding='euc-kr')
raw_15_copied = raw_15.copy()

col_list = raw_15_copied.columns.tolist()
raw_15_copied[col_list[2]]=bf_raw_15[col_list[-2]]

for col in col_list[2:]:
    raw_15_copied[col] = raw_15_copied[col]/100000000

raw_15_copied.iloc[5,-1] = mortgage_loan
raw_15_copied.iloc[13,-1] = mortgage_loan

file_17 = input('이번 기준일 파일명(17번쿼리)을 /file_name.csv 형식으로 입력해주세요 : ')
raw_17 = pd.read_csv(path+file_17, sep=',', encoding='euc-kr')
raw_17_copied = raw_17.copy()
col_list_17 = raw_17.columns.tolist()

for col in col_list_17[2:]:
    raw_17_copied[col]=raw_17_copied[col]/100000000

row_no = [1,6,8,13]

for r in row_no:
    raw_17_copied.iloc[r,14] = mortgage_loan
for r in row_no[:2]:
    raw_17_copied.iloc[r,15] = raw_15_copied.iloc[5,-2]
for r in row_no[2:]:
    raw_17_copied.iloc[r,15] = raw_15_copied.iloc[13,-2]

raw_17_final = raw_17_copied[col_list_17[6:]].drop(index=[0,6,7,13])
raw_17_final.reset_index(inplace=True)
raw_17_final.drop(columns='index',inplace=True)
raw_17_final.iloc[3,12] = raw_17_final.iloc[0,12]
raw_17_final.iloc[8,12] = raw_17_final.iloc[5,12]
raw_17_final.iloc[0,12] = 0
raw_17_final.iloc[5,12] = 0

raw_17_final.iloc[3,13] = raw_17_final.iloc[0,13]
raw_17_final.iloc[8,13] = raw_17_final.iloc[5,13]
raw_17_final.iloc[0,13] = 0
raw_17_final.iloc[5,13] = 0

raw_15_copied['기중 정상화 등(E)']= raw_15_copied['전기준일 연체잔액 (A)']+raw_15_copied['기간중 신규연체 (B)']-raw_15_copied['기간중 상각 (C)']-raw_15_copied['기간중 대환 (D)']-raw_15_copied['기준일 연체잔액 (F)']
report2_col_list = raw_15_copied.columns.tolist()
report2_final_col_list = report2_col_list[:6]+ [report2_col_list[-1]] + report2_col_list[6:8]

raw_15_final = raw_15_copied[report2_final_col_list].drop(index=[0,8]).reset_index()


result_file = input('보고서 1 최종결과파일명을 확장자명 포함하여 기입해주세요')
result_path_file = path+result_file
raw_17_final.to_csv(result_path_file, encoding = 'utf-8-sig', quoting=1, index=False)

result_file = input('보고서 2 최종결과파일명을 확장자명 포함하여 기입해주세요')
result_path_file = path+result_file
raw_15_final.to_csv(result_path_file, encoding = 'utf-8-sig', quoting=1, index=False)