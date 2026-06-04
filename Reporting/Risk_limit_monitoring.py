import pandas as pd 
import numpy as np
import configs


def preprocessing(data,ksic,main_debt_group,total_ead):
    
    main_debt_group.drop_duplicates()
    main_debt_group = main_debt_group.dropna(subset = ['SSN_CORP_NUM'])
    
    main_debt_group.info()
    ksic[configs.COLUMN_NMS['RISK_LIMIT_ADD_COLS'][0]] = ksic[configs.COLUMN_NMS['RISK_LIMIT_ADD_COLS'][0]].astype('string').str.strip()
    cols = data.columns
    
    data[cols[0]] = data[cols[0]].astype('float')

    data[cols[3]].fillna('K64999',inplace=True)
    data[configs.COLUMN_NMS['RISK_LIMIT_ADD_COLS'][0]] = np.where((data[cols[0]].astype('string').str[:3]=='400')&(data[cols[0]].isnull()), np.nan, data[cols[3]].astype('string').str[:3])
    
    data[configs.COLUMN_NMS['RISK_LIMIT_ADD_COLS'][0]] = data[configs.COLUMN_NMS['RISK_LIMIT_ADD_COLS'][0]].astype('string')
    data = pd.merge(data,ksic, how='left', on=configs.COLUMN_NMS['RISK_LIMIT_ADD_COLS'][0])
    
    
    data = pd.merge(data,main_debt_group, how='left', on=cols[0])
               
    sum_ead = data[cols[4]].sum()
    data[configs.COLUMN_NMS['RISK_LIMIT_ADD_COLS'][3]]=(total_ead*(data[cols[4]]/sum_ead))
    return data

# def pivot_table_make(data):
#     continue



yymm = input('작성 기준년월을 YYMM 형식으로 입력하세요 : ')
#test_raw2 = pd.read_excel(configs.PATH['RISK_LIMIT_BSM'].format(yymm=yymm), sheet_name='결과',skiprows=6)
#test_raw2.info()
#print(test_raw2)

raw = pd.read_csv(configs.PATH['RISK_LIMIT_RAW_DATA1'].format(yymm=yymm),sep=",", encoding='euc-kr')
ksic = pd.read_csv(configs.PATH['RISK_LIMIT_KSIC'].format(yymm=yymm),sep=",", encoding='utf-8-sig')
main_debt_group = pd.read_csv(configs.PATH['RISK_LIMIT_MAIN_DEBT_GROUP'].format(yymm=yymm),sep=",", encoding='utf-8-sig')
main_debt_group.info()
main_debt_group.drop_duplicates()
main_debt_group = main_debt_group.dropna(subset = ['SSN_CORP_NUM'])
main_debt_group.info()
preprocessing(raw,ksic,main_debt_group,total_ead=17687118).to_csv(configs.PATH['RISK_LIMIT_RESULT'].format(yymm=yymm),encoding='utf-8-sig',index=False)
preprocessing(raw,ksic,main_debt_group,total_ead=17687118).info()
