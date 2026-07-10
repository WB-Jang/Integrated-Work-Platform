import pandas as pd
import html
from pathlib import Path
import configs


def send_outlook_mail_with_df(
        subject: str,
        body: str,
        to: "str | list[str] | None" = None,
        cc: "str | list[str] | None" = None,
        out_path_file: str = "",
        display_only: bool = True,
):
    """Outlook 새 메일 창을 띄워 본문에 DataFrame(HTML테이블) 삽입 (내부망 Outlook 전용)
    - display_only=True: 메일 창만 띄움
    - display_only=False: 바로 발송(주의!!)
    """
    import win32com.client as win32
    outlook = win32.Dispatch("Outlook.Application")  # "Outlook.Application"은 Windows 레지스트리에 등록된 응용프로그램의 ProgID임
    mail = outlook.CreateItem(0)

    mail.Attachments.Add(out_path_file)

    if to:
        if to is None or isinstance(to, str):
            mail.To = to
        else:
            mail.To = ";".join(to)
    if cc:
        if to is None or isinstance(cc, str):
            mail.CC = cc
        else:
            mail.CC = ";".join(cc)

    mail.Subject = subject

    mail.HTMLBody = body

    if display_only:
        mail.Display()
    else:
        print('바로 발송!!')


style = """
<style>
    body {
        font-famliy: 'Malgun Gothic', '맑은 고딕';
        font-size: 10pt;
        line-height: 1;
        margin: 0;
        padding: 0;
    }
    p {
        margin: 5px 0;
    }
</style>
"""


def generate_report(raw, yyyymm, end_dt):
    """거액 신규 여신 보고서 (B2419, 건당 50억 이상 신규분).

    통합 raw(.xlsx, 시트 2종)와 기준년월(YYYYMM)·기한(end_dt)을 받아 이메일용
    xlsx와 전결권자 확인요청용 xlsx를 생성하고, Outlook 메일 초안 2건을 띄운다.
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
        _log("[1/4] 통합 raw 로드 중...")
        yyyymm = str(yyyymm)
        raw_file = pd.read_excel(raw, sheet_name=[f'B2419result_{yyyymm}_1', f'B2419report_{yyyymm}_sel1_seq'])
        raw = raw_file[f'B2419result_{yyyymm}_1']
        raw = raw.iloc[1:, :].reset_index()

        seq = raw_file[f'B2419report_{yyyymm}_sel1_seq']

        out_path_file = f"C:/Users/1598505/OneDrive - Standard Chartered Bank/1.보고서(WB)/1.FSS/1.업무보고서/2.월/B2419_월보/2026년도/{yyyymm[2:6]}/b2419_email({yyyymm[2:6]}기준).xlsx"
        confirm_file = f"C:/Users/1598505/OneDrive - Standard Chartered Bank/1.보고서(WB)/1.FSS/1.업무보고서/2.월/B2419_월보/2026년도/{yyyymm[2:6]}/b2419_전결권자확인요청({yyyymm[2:6]}기준).xlsx"
    except Exception as e:
        return _fail("통합 raw 로드", e)

    try:
        _log("[2/4] 컬럼 가공 및 확인요청 파일 저장 중...")
        col_list = configs.COLUMN_NMS['B2419_COLS']
        object_list = raw.select_dtypes(include='object').columns.tolist()

        for col in col_list:
            raw[col] = raw[col].str.strip()

        for col in object_list:
            raw[col] = raw[col].astype('string')

        seq['주민법인SEQ번호'] = seq['주민법인SEQ번호'].astype('string').str.zfill(7)
        raw['ssn_corpno'] = raw['주민법인번호'].str[:6] + seq['주민법인SEQ번호']
        raw['acct_no'] = raw['계좌번호'].str[:5] + seq['계좌SEQ번호'].astype('string').str.zfill(6)
        raw['corp_nm'] = raw['업체명'].str[:2] + seq['고객SEQ명'].astype('string')
        raw['rpsnt_nm'] = raw['업체대표'].str[:2] + seq[4].astype('string')

        raw[configs.COLUMN_NMS['B2419_RAW_COLS']].to_excel(confirm_file, index=False)
    except Exception as e:
        return _fail("컬럼 가공/확인요청 저장", e)

    try:
        _log("[3/4] 이메일용 보고서 파일 저장 중...")
        raw['확인요청'] = '신규/연기/갱신/대환'
        raw['담당자'] = ''
        raw['전년말총자산'] = ''
        raw['전년매출액'] = ''
        raw['전년순이익'] = ''
        raw['유효담보가'] = ''
        raw['대표자'] = ''

        raw['여신한도(승인)'] = raw['여신한도(승인)'] / 1000000
        raw_final = raw[['ssn_corpno', 'acct_no', 'corp_nm', '여신한도(승인)', '확인요청', '담당자', '전년말총자산', '전년매출액', '전년순이익', '유효담보가', '대표자']]
        raw_final.to_excel(out_path_file, index=False)
        html_table = raw_final.to_html(index=False, justify='center')
    except Exception as e:
        return _fail("이메일용 보고서 저장", e)

    try:
        _log("[4/4] Outlook 메일 초안(담당자 회신요청 + 전결권자 확인) 생성 중...")
        send_outlook_mail_with_df(
            subject=f'금감원보고서(B2419) 관련 요청의 건(기한 : {end_dt}까지)',
            cc='ByoungMoon.Yoo@sc.com',
            body=f"""
                                        <html>
                                            {style}
                                            <body>
                                                <p>Dear all,</p>
                                                <p>리스크관리부 장우빈입니다</p>
                                                <br>
                                                <p>금감원 보고서 B2419(신규여신 건당 50억원, 신규분만 보고) 작성을 위해, {yyyymm[4:6]}월 중 승인된 아래 리스트 중 담당업체의 신규 여부를 표의 붉은 박스 부분에 기재하여 회신 부탁드립니다. (기한: {end_dt})</p>
                                                <p>- 기 승인한도 내 기표 건은 신규 취급으로 보고하지 않으므로 “기 승인한도 내 기표”로 회신 부탁 드립니다.</p>
                                                <p>- 신규 여부 확인과 더불어 총자산/매출액/순이익 정보가 공란인 경우 해당 정보도 함께 제공 부탁드립니다.(현재 기입된 정보는 KISLINE의 개별 기준) </p>
                                                <br>
                                                {html_table}
                                                <br>
                                                <p>담당이 아닌 케이스는 말씀 부탁 드리며, 항상 많은 도움 주셔서 감사합니다</p>


                                            </body>
                                        </html>
                                        """,
            out_path_file=out_path_file)
        send_outlook_mail_with_df(
            subject='B2419 보고서 관련 전결권자 성명 확인 요청 건',
            to='SooHyun.Moon@sc.com',
            cc='ByoungMoon.Yoo@sc.com',
            body=f"""
                                        <html>
                                            {style}
                                            <body>

                                                <p>안녕하세요 이사님 </p>
                                                <p>리스크관리부 장우빈입니다</p>
                                                <br>
                                                <p>바쁘신 와중에도 도움주셔서 감사합니다</p>
                                                <p>{yyyymm[:4]}년 {yyyymm[4:6]}월 기준 B2419 보고서 작성을 위한 첨부 파일 내 전결권자직성명(U열) 확인 요청 드립니다</p>


                                            </body>
                                        </html>
                                        """,
            out_path_file=confirm_file)
    except Exception as e:
        # 메일 발송은 부가 기능 — 실패해도 보고서 파일 자체는 정상 산출된 것으로 처리하고 경고만 남긴다.
        import traceback
        _log(f"[경고] Outlook 메일 초안 생성 실패(보고서 파일은 정상 저장됨): {e}")
        _log(traceback.format_exc())

    _log(f"[완료] B2419 거액 신규 여신 보고서 작성 완료: {out_path_file}")
    return {'ok': True, 'log': "\n".join(logs), 'outfile': out_path_file, 'outfiles': [out_path_file, confirm_file]}
