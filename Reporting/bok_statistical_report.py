import pandas as pd
yymm = '2602'
path = f'C:/Users/1598505/OneDrive - Standard Chartered Bank/1.보고서(WB)/2.BOK/2.월/통화금융통계조사표/2026년도/{yymm}/Data/'
file = f'01_월여신_137,148_20{yymm}.csv'
seq_file = f'seq_137_148_{yymm}.csv'
rel_file = 'related_companies.csv'
cls_file = 'classification.csv'

cols = ['기준년월','계좌번호','계정과목코드','주민법인번호','원화환산잔액','대출평균잔액','법인구분코드','기업규모코드'] 
seq_cols = [['계좌번호','계좌SEQ번호',5,6],['주민법인번호','주민법인SEQ번호',6,7]]

# 여기 위는 Configs로 묶도록 하자

tmp_137_148 = pd.read_csv(path+file,encoding='euc-kr')
seq_137_148 = pd.read_csv(path+seq_file,encoding='euc-kr')

raw_137_148 = pd.concat([tmp_137_148,seq_137_148],axis=1)


for sq in seq_cols:
    s,q,i,j = sq
    raw_137_148[s] = raw_137_148[s].astype('string').str[:i]+raw_137_148[q].astype('string').str.zfill(j)
    print(raw_137_148[s])

print(raw_137_148[cols].info())

rel = pd.read_csv(path+rel_file,encoding='cp949')
cls = pd.read_csv(path+cls_file,encoding='euc-kr')

print(rel.info())
print(cls.info())

