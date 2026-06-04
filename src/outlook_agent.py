"""
로컬 Outlook COM을 통한 메일 조회 및 LLM 분석 에이전트.
win32com / pythoncom 의존.
"""
import datetime
import os
import tempfile
from typing import Optional

import pythoncom
from logger import get_logger

log = get_logger("outlook")


def _smtp_of(recipient) -> str:
    """수신자(Recipient) 의 실제 SMTP 주소를 최대한 해석.

    Exchange 계정은 Recipient.Address 가 X.500 DN(/O=.../CN=...) 형태라 사람이 읽거나
    이름으로 매칭할 수 없다. AddressEntry 를 통해 PrimarySmtpAddress 를 복구한다.
    """
    try:
        ae = recipient.AddressEntry
    except Exception:
        return ""
    # 1) Exchange 사용자
    try:
        eu = ae.GetExchangeUser()
        if eu is not None:
            smtp = getattr(eu, "PrimarySmtpAddress", "") or ""
            if smtp:
                return smtp
    except Exception:
        pass
    # 2) PR_SMTP_ADDRESS 프로퍼티
    try:
        PR_SMTP = "http://schemas.microsoft.com/mapi/proptag/0x39FE001E"
        v = ae.PropertyAccessor.GetProperty(PR_SMTP)
        if v:
            return str(v)
    except Exception:
        pass
    return ""


# ─── Outlook 메일 조회 ───────────────────────────────────────────────────────

def get_emails(
    start_date: datetime.date,
    end_date: datetime.date,
    sender_filter: str = "",
    recipient_filter: str = "",
    include_attachments: bool = False,
) -> list[dict]:
    """
    로컬 Outlook에서 지정 기간의 수발신 메일을 조회합니다.

    Returns:
        list of dict: subject, sender, recipients, date, direction, body, attachments
    """
    pythoncom.CoInitialize()
    try:
        import win32com.client
        outlook = win32com.client.Dispatch("Outlook.Application")
        ns = outlook.GetNamespace("MAPI")

        end_inclusive = end_date + datetime.timedelta(days=1)
        start_s = start_date.strftime('%m/%d/%Y')
        end_s = end_inclusive.strftime('%m/%d/%Y')

        results: list[dict] = []

        # 수신함(6)=ReceivedTime 기준, 보낸편지함(5)=SentOn 기준.
        # (보낸 메일은 ReceivedTime 이 비어 있을 수 있어 날짜 필터가 누락됨)
        folder_specs = [
            (6, "수신", "[ReceivedTime]"),
            (5, "발신", "[SentOn]"),
        ]

        for folder_id, direction, date_prop in folder_specs:
            date_filter = (
                f"{date_prop} >= '{start_s}' AND {date_prop} < '{end_s}'"
            )
            try:
                folder = ns.GetDefaultFolder(folder_id)
                items = folder.Items
                try:
                    items.Sort(date_prop, True)
                except Exception:
                    pass
                filtered = items.Restrict(date_filter)

                for item in filtered:
                    try:
                        subject = getattr(item, "Subject", "") or ""
                        sender = getattr(item, "SenderName", "") or ""
                        sender_email = getattr(item, "SenderEmailAddress", "") or ""

                        # 발신자 필터
                        if sender_filter:
                            sf = sender_filter.lower()
                            if sf not in sender.lower() and sf not in sender_email.lower():
                                continue

                        # 수신자 목록: 표시용(이름) + 매칭용(이름·SMTP·주소 모두)
                        recipients: list[str] = []
                        recip_match: list[str] = []
                        try:
                            for r in item.Recipients:
                                nm = getattr(r, "Name", "") or ""
                                addr = getattr(r, "Address", "") or ""
                                smtp = _smtp_of(r)
                                disp = nm or smtp or addr
                                if disp:
                                    recipients.append(disp)
                                recip_match.append(" ".join([nm, smtp, addr]).lower())
                        except Exception:
                            pass

                        # 수신자 필터: 이름/SMTP/주소 중 어디에든 매칭되면 통과
                        if recipient_filter:
                            rf = recipient_filter.lower()
                            if not any(rf in blob for blob in recip_match):
                                continue

                        body = (getattr(item, "Body", "") or "")[:8000]

                        # 날짜: 폴더 종류에 맞는 속성 사용
                        try:
                            dt = (getattr(item, "ReceivedTime", None) if direction == "수신"
                                  else getattr(item, "SentOn", None))
                            if dt is None:
                                dt = getattr(item, "ReceivedTime", None) or getattr(item, "SentOn", None)
                            date_str = dt.strftime("%Y-%m-%d %H:%M") if dt else ""
                        except Exception:
                            date_str = ""

                        # 첨부파일 텍스트 추출
                        attachments_text: list[str] = []
                        if include_attachments:
                            try:
                                att_count = item.Attachments.Count
                            except Exception:
                                att_count = 0
                            for i in range(1, att_count + 1):
                                try:
                                    att = item.Attachments.Item(i)
                                    fname = att.FileName or ""
                                    text = _extract_attachment_text(att, fname)
                                    if text:
                                        attachments_text.append(
                                            f"[첨부: {fname}]\n{text[:3000]}"
                                        )
                                except Exception as ae:
                                    log.debug("첨부파일 추출 실패: %s", ae)

                        results.append(
                            {
                                "subject": subject,
                                "sender": sender,
                                "sender_email": sender_email,
                                "recipients": recipients,
                                "date": date_str,
                                "direction": direction,
                                "body": body,
                                "attachments": attachments_text,
                            }
                        )

                    except Exception as ie:
                        log.debug("메일 항목 처리 실패: %s", ie)
                        continue

            except Exception as fe:
                log.warning("폴더 접근 실패 (folder_id=%d): %s", folder_id, fe)
                continue

        results.sort(key=lambda x: x["date"])
        log.info(
            "Outlook 조회 완료: %d건 (%s ~ %s)",
            len(results),
            start_date,
            end_date,
        )
        return results

    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def _extract_attachment_text(att, fname: str) -> str:
    """DOCX/PDF 첨부파일에서 텍스트 추출. 실패 시 빈 문자열 반환."""
    tmp = None
    try:
        ext = os.path.splitext(fname)[1].lower()
        if ext not in (".docx", ".pdf", ".txt"):
            return ""

        tmp = tempfile.mktemp(suffix=ext)
        att.SaveAsFile(tmp)

        if ext == ".docx":
            import docx as _docx
            d = _docx.Document(tmp)
            return "\n".join(p.text for p in d.paragraphs if p.text.strip())
        elif ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(tmp)
            return "".join(page.extract_text() or "" for page in reader.pages)
        elif ext == ".txt":
            with open(tmp, encoding="utf-8", errors="ignore") as f:
                return f.read()
        return ""
    except Exception as e:
        log.debug("첨부 텍스트 추출 오류 (%s): %s", fname, e)
        return ""
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


# ─── LLM 포맷 / 분석 / 초안 ─────────────────────────────────────────────────

def format_emails_for_llm(emails: list[dict], max_chars: int = 40_000) -> str:
    """메일 목록을 LLM 분석용 텍스트로 변환."""
    parts: list[str] = []
    total = 0

    for i, e in enumerate(emails, 1):
        att_block = ""
        if e.get("attachments"):
            att_block = "\n" + "\n".join(e["attachments"])

        entry = (
            f"--- [{i}] {e['direction']} | {e['date']} ---\n"
            f"제목: {e['subject']}\n"
            f"발신자: {e['sender']} <{e['sender_email']}>\n"
            f"수신자: {', '.join(e['recipients'][:5])}\n"
            f"본문:\n{e['body']}{att_block}\n"
        )

        if total + len(entry) > max_chars:
            parts.append(
                f"\n...(조회된 {len(emails)}건 중 {i - 1}건만 표시 — 나머지 {len(emails) - i + 1}건 생략)"
            )
            break

        parts.append(entry)
        total += len(entry)

    return "\n".join(parts)


def analyze_emails(emails: list[dict], task: str, llm) -> str:
    """메일 목록에 대해 지정 태스크를 LLM으로 수행."""
    from langchain_core.prompts import PromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    template = """[Context]
당신은 금융기관 임직원의 업무 이메일을 분석하는 어시스턴트입니다.
분석 대상: Outlook에서 조회한 이메일 수발신 내역

[Objective]
아래 이메일 내역을 바탕으로 요청 작업을 수행하세요.

[요청 작업]
{task}

[Style]
- 핵심 정보를 글머리 기호(•)로 정리
- 수치(건수, 날짜, 금액 등)는 구체적으로 명시
- 불필요한 인사말·부연 없이 실무형으로 작성

[Tone]
전문적이고 간결하게. 추측 금지, 이메일에 기재된 내용에만 근거할 것.

[Audience]
리스크관리·준법감시·업무 담당 실무자

[Response]
항목별 번호 목록으로 정리 → 마지막에 "종합 의견" 한 문단

[이메일 내역]
{emails}

[분석 결과]:
"""
    prompt = PromptTemplate.from_template(template)
    chain = prompt | llm | StrOutputParser()
    email_text = format_emails_for_llm(emails)
    return chain.invoke({"emails": email_text, "task": task})


def create_reply_draft(email: dict, instruction: str, llm) -> str:
    """선택한 메일에 대한 답장 초안을 LLM으로 생성."""
    from langchain_core.prompts import PromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    template = """[Context]
당신은 금융기관 임직원의 공식 이메일 답장을 작성하는 어시스턴트입니다.

[Objective]
아래 원본 이메일에 대한 답장 초안을 작성하세요.

[원본 이메일]
제목: {subject}
발신자: {sender}
날짜: {date}
본문:
{body}

[답장 지시사항]
{instruction}

[Style]
- 공식 비즈니스 문체 (경어체, 격식체)
- 핵심 내용 중심으로 간결하게
- 불필요한 반복·수식어 지양

[Tone]
정중하고 전문적으로. 금융기관 대외 공문 수준의 품격 유지.

[Audience]
이메일 발신자 ({sender})

[Response]
인사말 → 본문(요점 중심) → 마무리 인사 순서로 작성.
서명란은 "[서명]"으로만 표시.

[답장 초안]:
"""
    prompt = PromptTemplate.from_template(template)
    chain = prompt | llm | StrOutputParser()
    return chain.invoke(
        {
            "subject": email.get("subject", ""),
            "sender": email.get("sender", ""),
            "date": email.get("date", ""),
            "body": email.get("body", "")[:3000],
            "instruction": instruction,
        }
    )
