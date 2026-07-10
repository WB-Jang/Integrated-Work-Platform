# 파일 경로 관리
PATH = {
    'CRIR_RAW_DATA1': "C:/Users/1598505/OneDrive - Standard Chartered Bank/1.보고서(WB)/3.Internal/8.CRIR/test/{yymm}/raw_data_{yymm}.csv",
    'RISK_LIMIT_RAW_DATA1' : 'C:/Users/1598505/OneDrive - Standard Chartered Bank/4.내부자본적정성.리스크한도.리스크한도/2. 자본모니터링/{yymm}/test/bcrs_20{yymm}_corp_data.csv',
    'RISK_LIMIT_KSIC' : 'C:/Users/1598505/OneDrive - Standard Chartered Bank/4.내부자본적정성.리스크한도.리스크한도/2. 자본모니터링/{yymm}/test/ksic.csv',
    'RISK_LIMIT_BSM' : 'Z:/01.Business Seg (New) 20{yymm}_EC_simple_N.XLSX',
    'RISK_LIMIT_MAIN_DEBT_GROUP' : 'C:/Users/1598505/OneDrive - Standard Chartered Bank/4.내부자본적정성.리스크한도.리스크한도/2. 자본모니터링/{yymm}/test/main_debt_group.csv',
    'RISK_LIMIT_RESULT' : 'C:/Users/1598505/OneDrive - Standard Chartered Bank/4.내부자본적정성.리스크한도.리스크한도/2. 자본모니터링/{yymm}/test/result_{yymm}.csv',
    'DRM_FREE' : 'C:/Users/1598505/SCBapps/DRM_free',
    # 'Z_DRIVE' : 'Z:/'

}

COLUMN_NMS = {
    'CRIR_RAW_COLS' : ['Reporting Month','LEID','CG','Residual Maturity (Years)','Booking Location','Main Profile','Customer Segment',\
                       'Group Segment Desc','CCR Country','Scorecard Grouping','Segment','Tenor Bucket','Industry Limits Classification','Product Grouping','Segment Classification','Net Nominal'],
                       # 컬럼 순서는 변경하지 말것, 추가가 필요하면 가장 뒤에 붙일 것
    'RISK_LIMIT_ADD_COLS' : ['industry1','industry2','group_nm','final_ead'], # Risk Limit 자료 작성 시 raw data에 추가로 생성해야 하는 컬럼명 리스트
    'TENOR_BUCKET_ORDER' : ['<=1 year','1-3 years','3-5 years','>5 years'],
    'SEGMENT_ORDER' : ['Sovereign & MDO','Corporates','Financial Institutions','Nostros, Interbank & Securities','Others'],
    'CG_ORDER' : ['Investment grade (CG1-5)','Sub-investment grade (CG6-8)','Sub-investment grade (CG9-11)','GSAM (CG12)','GSAM (CG13-14)'],
    'CLLTRL_COLS' : ['CG','Ccmv','Net Nominal','Cash','Property','Commodities & SIP Repo','Guarantee','Other Collateral','Plant, Machinery & Other stock in WC','Securities','Ships & Aircrafts'],
    'CG_ORDER_CLLTRL' : ['Investment grade (CG1-5)','Sub-investment grade (CG till 11C)','GSAM (CG12)','GSAM (CG13-14)'],
    'CLLTRL_ORDER' : ['Cash','Property','Guarantee','Ships & Aircrafts','Others','Total'],
    'B2419_COLS' : ['주민법인번호','업체명','계좌번호','업체대표'],
    'B2419_RAW_COLS' : ['기준년월','취급점포','ssn_corpno','corp_nm','rpsnt_nm','주생산품','업체종합평점(CRG)','종합평점조사일(CRG부여일)','전년말총자산','전년매출액','전년순이익','취급일',\
            '계정과목코드','과목','acct_no','acct_no','여신한도(승인)','실제여신','승인일자','세부용도','전결권자직성명'],
    'CORP_ORDER' : ['기업','대기업','중소기업','개인사업자'],



}
CG_GROUPS = {
    'Investment grade (CG1-5)' : ['1A','1B','2A','2B','3A','3B','4A','4B','5A','5B'],
    'Sub-investment grade (CG6-8)' : ['6A','6B','7A','7B','8A','8B'],
    'Sub-investment grade (CG9-11)' : ['9A','9B','10A','10B','11A','11B','11C'],
    'GSAM (CG12)' : ['12A','12B','12C'],
    'GSAM (CG13-14)' : ['13','14A','14B','13','14']
}
CG_GROUPS_CLLTRL = {
    'Investment grade (CG1-5)' : ['1A','1B','2A','2B','3A','3B','4A','4B','5A','5B'],
    'Sub-investment grade (CG till 11C)' : ['6A','6B','7A','7B','8A','8B','9A','9B','10A','10B','11A','11B','11C'],
    'GSAM (CG12)' : ['12A','12B','12C'],
    'GSAM (CG13-14)' : ['13','14A','14B','13','14']
}
CRNCY_CD_GROUP = {'미달러화' : ['1'],
                  '일본엔화' : ['2'],
                  '유로화' : ['161'],
                  '기타통화' : ['그 외']}

ANNEX3_CG_GROUPS = {
    'CG 1-3' : ['1A','1B','2A','2B','3A','3B'],
    'CG 4' : ['4A','4B'],
    'CG 5' : ['5A','5B'],
    'CG 6' : ['6A','6B'],
    'CG 7-8' : ['7A','7B','8A','8B'],
    'CG 9-10' : ['9A','9B','10A','10B'],
    'CG 11' : ['11A','11B','11C'],
    'CG 12' : ['12A','12B','12C'],
}

ANNEX3_CG_FI_GROUPS = {
    'CG 1-3' : ['1A','1B','2A','2B','3A','3B'],
    'CG 4-5A' : ['4A','4B','5A'],
    'CG 5B-6' : ['5B','6A','6B'],
    'CG 7-8' : ['7A','7B','8A','8B'],
    'CG 9-10' : ['9A','9B','10A','10B'],
    'CG 11' : ['11A','11B','11C'],
    'CG 12' : ['12A','12B','12C'],
}
