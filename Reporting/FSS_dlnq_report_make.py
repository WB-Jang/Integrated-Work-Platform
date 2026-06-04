import pandas as pd

path = input('이번 기준일 파일의 경로를 입력해주세요 : ')
file1 = input('이번 기준일 1번 파일명을 /file_name.csv 형식으로 입력해주세요 : ')
path_file1 = path+file1
raw1 = pd.read_csv(path_file1, sep =',', encoding='euc-kr')
raw1_copied = raw1.copy()
raw1_final = raw1_copied.drop(index=[0,1])

file2 = input('이번 기준일 2번 파일명을 /file_name.csv 형식으로 입력해주세요 : ')
path_file2 = path+file2
raw2 = pd.read_csv(path_file2, sep =',', encoding='euc-kr')
raw2_copied = raw2.copy()

col_list = raw2_copied.columns.tolist()[3:]

for c in col_list:
    raw2_copied.loc[17,c]+=(raw2_copied.loc[14,c]-raw2_copied.loc[15,c])
    raw2_copied.loc[36,c]+=(raw2_copied.loc[33,c]-raw2_copied.loc[34,c])
    raw2_copied.loc[55,c]+=(raw2_copied.loc[52,c]-raw2_copied.loc[53,c])
    raw2_copied.loc[74,c]+=(raw2_copied.loc[71,c]-raw2_copied.loc[72,c])

raw2_final = raw2_copied.drop(index=[14,33,52,71])

out_path = input('결과 파일을 저장하는 경로를 입력해주세요 : ')
out_file1 = input('첫 번째 결과 파일명을 /file_name.csv 형식으로 입력해주세요 : ')
out_file2 = input('두 번째 결과 파일명을 /file_name.csv 형식으로 입력해주세요 : ')
out_path_file1 = out_path+out_file1
out_path_file2 = out_path+out_file2

raw1_final.to_csv(out_path_file1, index=False, encoding='utf-8-sig')
raw2_final.to_csv(out_path_file2, index=False, encoding='utf-8-sig')

print('결과 파일 생성이 완료되었습니다. 최종 제출 파일에 복사-붙여넣기 하세요')