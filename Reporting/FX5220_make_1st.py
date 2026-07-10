import pandas as pd
from datetime import datetime

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


def _send_outlook_mail_with_df(subject, body, out_path_file, to="", cc="", bcc="", display_only=True):
    """Outlook 새 메일 창을 띄워 본문/첨부를 구성한다 (내부망 Outlook 전용).
    - display_only=True: 메일 창만 띄움
    - display_only=False: 바로 발송(주의!!)
    """
    import win32com.client as win32
    outlook = win32.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)
    mail.Attachments.Add(out_path_file)
    mail.To = to
    if cc:
        mail.CC = cc
    if bcc:
        mail.BCC = bcc
    mail.Subject = subject
    mail.HTMLBody = body
    if display_only:
        mail.Display()
    else:
        print('바로 발송!!')


def generate_report(raw, dt):
    """FX5220 보고서 (1차) - 신규 외화여신 현황.

    통합 raw(.xlsx, 시트: cur_raw/bf_rm_info) + 기준일(dt, yyyymmdd)을 받아
    신규 외화여신 리스트 CSV를 하드코딩 경로로 저장하고, RM 자료요청 Outlook
    메일 초안을 띄운다. 최종 파일명/경로는 기존 하드코딩 규칙을 그대로 따른다.
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
        dt = str(dt)
        dt_trans = datetime.strptime(dt, '%Y%m%d')
        raw_file = pd.read_excel(raw, sheet_name=['cur_raw', 'bf_rm_info'])
        out_path_file = f"C:/Users/1598505/OneDrive - Standard Chartered Bank/1.보고서(WB)/2.BOK/2.월/FX5220_월보/2026년도/{dt[2:6]}/FX5220_new_list({dt[2:6]}기준).csv"
        raw_copied = raw_file['cur_raw']
        bf_raw = raw_file['bf_rm_info']
        bf_raw = bf_raw[['계좌번호', '업종', '기업규모', '용도', '담당자']].copy()
    except Exception as e:
        return _fail("통합 raw 로드", e)

    try:
        _log("[2/4] 신규 외화여신 추출 중...")
        raw_copied['base_dt'] = dt_trans
        raw_copied['exec_amt'] = raw_copied['exec_amt'].astype('string').str.replace(',', '').astype('float')
        raw_copied['pybck_amt'] = raw_copied['pybck_amt'].astype('string').str.replace(',', '').astype('float')
        raw_copied['loan_asst_bs_amt'] = raw_copied['loan_asst_bs_amt'].astype('string').str.replace(',', '').astype('float')

        raw_copied.rename(columns={raw_copied.columns[0]: '계좌번호'}, inplace=True)

        raw_merged = raw_copied.merge(bf_raw, how='left', on='계좌번호')

        new_condition = raw_merged['exec_amt'] > 0
        raw_new = raw_merged[new_condition]
    except Exception as e:
        return _fail("신규 외화여신 추출", e)

    try:
        _log("[3/4] 결과 CSV 저장 중...")
        raw_new.to_csv(out_path_file, index=False, encoding='utf-8-sig')
    except Exception as e:
        return _fail("결과 저장", e)

    try:
        _log("[4/4] RM 자료요청 Outlook 메일 초안 생성 중...")
        _send_outlook_mail_with_df(
            f'{dt[:4]}.{dt[4:6]}월 말 기준 FX5220 자료 요청',
            f"""

<html>
    {style}
    <body>
        <p>안녕하세요,</p>
        <p>리스크관리부 장우빈입니다</p>
        <br>
        <p>{dt[:4]}년 {dt[4:6]}월말 기준 BOK FX5220 보고서 작성을 위해, 첨부파일의 AE~AH열을 업데이트 해주시면 대단히 감사하겠습니다</p>
        <p>혹시 추가로 더 확인하실 내용이나 자료가 필요하시다면, 말씀 부탁드립니다!</p>
        <br>
        <p>[참고]</p>
        <p>업종(2종류) : 제조업, 비제조업</p>
        <p>기업규모(2종류) : 대기업, 중소기업</p>
        <p>용도 (6종류) : 국내사용시설자금, 해외사용시설자금, 해외사용운전자금, 대내외화차입금상환자금, 대외외화차입금상환자금, 해외직접투자자금</p>
    </body>
</html>
""",
            out_path_file=out_path_file,
        )
    except Exception as e:
        # 메일 발송은 부가 기능 — 실패해도 보고서 파일 자체는 정상 산출된 것으로 처리하고 경고만 남긴다.
        import traceback
        _log(f"[경고] Outlook 메일 초안 생성 실패(보고서 파일은 정상 저장됨): {e}")
        _log(traceback.format_exc())

    _log(f"[완료] FX5220(1차) 신규 외화여신 작성 완료: {out_path_file}")
    return {'ok': True, 'log': "\n".join(logs), 'outfile': out_path_file}
