import pandas as pd
from pandas.api.types import CategoricalDtype

class corp_loan:
    def __init__(self):
        pass

    def _month_table(self, raw_data):
        print('--- 기업 여신 조사표 작성 시작 ---')
        print('--- raw data 편집 시작 ---')
        row_nm = ['F425','I551','I5613','R']
        num_list = []
        cols = raw_data.columns.tolist()
        for col in cols[1:]:
            raw_data[col] = raw_data[col]/100000000
        print('--- 억단위 변환 완료 ---')
        for idx,nm in enumerate(row_nm):
            row_num = raw_data[raw_data['코드명']==nm].index.to_numpy().item()
            num_list.append(row_num)
        print(f'--- 코드 {row_nm} 위치 파악 완료 : {num_list} ---')

        raw_parts = []
        for i in range(len(num_list)):
            if i == 0:
                raw_part = raw_data.loc[:num_list[i],:]
                raw_parts.append(raw_part)
            elif i == len(num_list)-1:
                raw_part = raw_data.loc[num_list[i-1]+1:num_list[i],:]
                raw_parts.append(raw_part)
                raw_part = raw_data.loc[num_list[i]+2:,:]
                raw_parts.append(raw_part)
            else:
                raw_part = raw_data.loc[num_list[i-1]+1:num_list[i],:]
                raw_parts.append(raw_part)
        
        additional_row_nm = ['F426','I55101','I55102','I55103','I55104','I55109','I5614']

        add_parts={}

        for i,nm in enumerate(additional_row_nm):
            add_parts[nm] = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]
            

        df_test = pd.DataFrame(add_parts)
        add_parts = df_test.T

        add_parts_new=add_parts.reset_index()
        add_parts_new.columns = raw_parts[0].columns

        raw_parts_integrated = pd.concat([raw_parts[0],add_parts_new.iloc[:1],raw_parts[1],add_parts_new.iloc[1:6],raw_parts[2],add_parts_new.iloc[6:],raw_parts[3],raw_parts[4]], ignore_index=True, axis=0)    
        return raw_parts_integrated

    def complete_table(self,bf_raw_data,raw_data):
        # super().__init__() -> 부모 클래스의 속성을 물려받을 때에 사용
        bf_table = self._month_table(bf_raw_data)
        table = self._month_table(raw_data)

        bf_cols = ['대기업 전월말잔액','중소기업 전월말잔액','개인사업자 전월말잔액']
        cols = ['대기업 금월말잔액','중소기업 금월말잔액','개인사업자 금월말잔액']

        for i,bf_col in enumerate(bf_cols):
            table[bf_col] = bf_table[cols[i]]
        return table
    
    def fs_00409(self,raw_data):
        raw_data['등급'] = raw_data['등급'].fillna('무등급')
        cg = [['1A','1B','2A','2B'],['3A','3B','4A'],['4B','5A','5B'],['6A','6B','7A','7B','8A','8B'],['9A','9B','10A','10B'],['11A','11B','11C'],['12A','12B','12C'],['13'],['14A'],['14B'],['무등급'],['소매 익스포저']]
        for i,ls in enumerate(cg):
            for cg in ls:
                for r in range(raw_data.shape[0]):
                    if cg in raw_data.loc[r,'등급']:
                        raw_data.loc[r,'new등급']=i+1
                        print(f'{cg}는 금감원 {i+1}등급으로 분류되었습니다')

        seg_order = ['대기업','중소+개인','개인']
        raw_data['분류'] = raw_data['분류'].astype(CategoricalDtype(categories=seg_order, ordered=True))

        raw_data['KGAAP 신규금액']=raw_data['KGAAP 신규금액']/100000000
        raw_data['월말 금액']=raw_data['월말 금액']/100000000

        raw_pivot = pd.pivot_table(
        raw_data
        ,values = ['KGAAP 신규금액','월말 금액']
        ,index = 'new등급'
        ,columns = ['분류']
        ,aggfunc='sum'
        ,fill_value=0)
        
        raw_pivot_reset = raw_pivot.reset_index()
        return raw_pivot_reset




def generate_report():
    path = input('파일 경로를 입력해주세요 : ')
    file = input('이번 기준년월 fs_00401 파일명을 /file_name.csv 형식으로 입력해주세요 : ')
    bf_file = input('지난 기준년월 fs_00401파일명을 /file_name.csv 형식으로 입력해주세요 : ')

    file2 = input('이번 기준년월 fs_00409 파일명을 /file_name.csv 형식으로 입력해주세요 : ')

    path_file = path+file
    bf_path_file = path+bf_file
    path_file2 = path+file2

    raw = pd.read_csv(path_file,sep=',', encoding='euc-kr')
    raw_copied = raw.copy()

    bf_raw = pd.read_csv(bf_path_file,sep=',', encoding='euc-kr')
    bf_raw_copied = bf_raw.copy()

    raw2 = pd.read_csv(path_file2,sep=',', encoding='euc-kr')
    raw_copied2 = raw2.copy()


    corp = corp_loan()

    fs_00401 = corp.complete_table(bf_raw_copied, raw_copied)
    fs_00401.to_csv(path+'/fs_00401_result.csv',index=False, encoding='euc-kr')
    fs_00409 = corp.fs_00409(raw_copied2)
    fs_00409.to_csv(path+'/fs_00409_result.csv',index=False, encoding='euc-kr')
    

