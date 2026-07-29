"""
브릿지 전용 Outlook COM 로직 (자립형).

이 파일은 IWP 서버의 ``src/outlook_agent.py`` 에서 **브릿지가 실제로 쓰는 함수만**
발췌·이식한 것이다. 브릿지는 사용자 PC에서 ``bridge`` 폴더만 받아 빌드/실행되는
경우가 많아, ``../src`` 에 의존하면 안 된다(그러면 PyInstaller 빌드 시
``No module named 'outlook_agent'`` 가 발생). 따라서 여기서는 win32com/pythoncom/
docx/pypdf + 표준 라이브러리에만 의존한다.

※ 서버측 ``src/outlook_agent.py`` 의 동일 함수와 스키마를 일치시켜 유지할 것.
"""
import os
import logging
import datetime
import tempfile

import pythoncom

log = logging.getLogger("outlook_ops")


# ─── 주소/회신상태 헬퍼 ──────────────────────────────────────────────────────
def _smtp_of(recipient) -> str:
    """수신자(Recipient)의 실제 SMTP 주소를 최대한 해석(Exchange DN 복구 포함)."""
    try:
        ae = recipient.AddressEntry
    except Exception:
        return ""
    try:
        eu = ae.GetExchangeUser()
        if eu is not None:
            smtp = getattr(eu, "PrimarySmtpAddress", "") or ""
            if smtp:
                return smtp
    except Exception:
        pass
    try:
        PR_SMTP = "http://schemas.microsoft.com/mapi/proptag/0x39FE001E"
        v = ae.PropertyAccessor.GetProperty(PR_SMTP)
        if v:
            return str(v)
    except Exception:
        pass
    return ""


# MAPI 프로퍼티: 마지막 수행 동작(회신/전체회신/전달)과 그 시각.
_PR_LAST_VERB_EXECUTED = "http://schemas.microsoft.com/mapi/proptag/0x10810003"
_PR_LAST_VERB_EXECUTION_TIME = "http://schemas.microsoft.com/mapi/proptag/0x10820040"
_VERB_LABELS = {102: "회신", 103: "전체회신", 104: "전달"}


def _reply_status(item) -> str:
    """메일의 회신/전달 여부를 반환. 예: '회신 (2026-06-09 14:21)' / '' (없음)."""
    try:
        pa = item.PropertyAccessor
        verb = int(pa.GetProperty(_PR_LAST_VERB_EXECUTED))
    except Exception:
        return ""
    label = _VERB_LABELS.get(verb, "")
    if not label:
        return ""
    try:
        vt = pa.GetProperty(_PR_LAST_VERB_EXECUTION_TIME)
        if vt:
            label += f" ({vt.strftime('%Y-%m-%d %H:%M')})"
    except Exception:
        pass
    return label


def _extract_attachment_text(att, fname: str) -> str:
    """DOCX/PDF/TXT 첨부에서 텍스트 추출. 실패 시 빈 문자열."""
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


# ─── 메일 조회 ───────────────────────────────────────────────────────────────
def get_emails(
    start_date: datetime.date,
    end_date: datetime.date,
    sender_filter: str = "",
    recipient_filter: str = "",
    include_attachments: bool = False,
) -> list[dict]:
    """로컬 Outlook에서 지정 기간의 수·발신 메일을 조회한다.

    반환 스키마: subject, sender, sender_email, recipients, to, cc, bcc,
    reply_status, unread, entry_id, store_id, date, direction, body, attachments.
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

        # 수신함(6)=ReceivedTime, 보낸편지함(5)=SentOn 기준.
        folder_specs = [
            (6, "수신", "[ReceivedTime]"),
            (5, "발신", "[SentOn]"),
        ]

        for folder_id, direction, date_prop in folder_specs:
            date_filter = f"{date_prop} >= '{start_s}' AND {date_prop} < '{end_s}'"
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

                        if sender_filter:
                            sf = sender_filter.lower()
                            if sf not in sender.lower() and sf not in sender_email.lower():
                                continue

                        recipients: list[str] = []
                        to_list: list[str] = []
                        cc_list: list[str] = []
                        bcc_list: list[str] = []
                        recip_match: list[str] = []
                        try:
                            for r in item.Recipients:
                                nm = getattr(r, "Name", "") or ""
                                addr = getattr(r, "Address", "") or ""
                                smtp = _smtp_of(r)
                                disp = nm or smtp or addr
                                if disp:
                                    recipients.append(disp)
                                    rtype = 1
                                    try:
                                        rtype = int(getattr(r, "Type", 1))
                                    except Exception:
                                        pass
                                    if rtype == 2:
                                        cc_list.append(disp)
                                    elif rtype == 3:
                                        bcc_list.append(disp)
                                    else:
                                        to_list.append(disp)
                                recip_match.append(" ".join([nm, smtp, addr]).lower())
                        except Exception:
                            pass

                        if recipient_filter:
                            rf = recipient_filter.lower()
                            if not any(rf in blob for blob in recip_match):
                                continue

                        body = (getattr(item, "Body", "") or "")[:8000]

                        try:
                            dt = (getattr(item, "ReceivedTime", None) if direction == "수신"
                                  else getattr(item, "SentOn", None))
                            if dt is None:
                                dt = getattr(item, "ReceivedTime", None) or getattr(item, "SentOn", None)
                            date_str = dt.strftime("%Y-%m-%d %H:%M") if dt else ""
                        except Exception:
                            date_str = ""

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
                                        attachments_text.append(f"[첨부: {fname}]\n{text[:3000]}")
                                except Exception as ae:
                                    log.debug("첨부파일 추출 실패: %s", ae)

                        entry_id = getattr(item, "EntryID", "") or ""
                        try:
                            store_id = folder.StoreID or ""
                        except Exception:
                            store_id = ""

                        results.append({
                            "subject": subject,
                            "sender": sender,
                            "sender_email": sender_email,
                            "recipients": recipients,
                            "to": to_list,
                            "cc": cc_list,
                            "bcc": bcc_list,
                            "reply_status": _reply_status(item),
                            "unread": bool(getattr(item, "UnRead", False)),
                            "entry_id": entry_id,
                            "store_id": store_id,
                            "date": date_str,
                            "direction": direction,
                            "body": body,
                            "attachments": attachments_text,
                        })

                    except Exception as ie:
                        log.debug("메일 항목 처리 실패: %s", ie)
                        continue

            except Exception as fe:
                log.warning("폴더 접근 실패 (folder_id=%d): %s", folder_id, fe)
                continue

        results.sort(key=lambda x: x["date"])
        log.info("Outlook 조회 완료: %d건 (%s ~ %s)", len(results), start_date, end_date)
        return results

    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


# ─── 메일 열기 ───────────────────────────────────────────────────────────────
def open_email(entry_id: str, store_id: str = "") -> bool:
    """EntryID 로 해당 메일을 로컬 Outlook 창에서 바로 연다."""
    if not entry_id:
        return False
    pythoncom.CoInitialize()
    try:
        import win32com.client
        ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        item = ns.GetItemFromID(entry_id, store_id) if store_id else ns.GetItemFromID(entry_id)
        item.Display()
        return True
    except Exception as e:
        log.warning("메일 열기 실패 (entry_id=%s...): %s", (entry_id or "")[:24], e)
        return False
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


# ─── 기본 메일함/회신 초안 ───────────────────────────────────────────────────
def default_mailbox() -> str:
    """기본 계정의 SMTP 주소(본인 메일함 식별용)."""
    import win32com.client
    pythoncom.CoInitialize()
    try:
        ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        try:
            acc = ns.Accounts.Item(1)  # COM 컬렉션은 1-based
            smtp = getattr(acc, "SmtpAddress", "") or ""
            if smtp:
                return smtp
            return getattr(acc, "DisplayName", "") or ""
        except Exception:
            try:
                return ns.CurrentUser.Address or ""
            except Exception:
                return ""
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def create_reply_draft(entry_id: str, store_id: str, body: str, reply_all: bool) -> bool:
    """본인 Outlook에서 해당 메일의 회신 초안을 만들어 창을 연다(사용자 검토용)."""
    import win32com.client
    if not entry_id:
        return False
    pythoncom.CoInitialize()
    try:
        ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        item = ns.GetItemFromID(entry_id, store_id) if store_id else ns.GetItemFromID(entry_id)
        reply = item.ReplyAll() if reply_all else item.Reply()
        try:
            reply.Body = (body or "") + "\n\n" + (reply.Body or "")
        except Exception:
            reply.Body = body or ""
        reply.Display()  # 자동 발송하지 않고 초안 창만 표시
        return True
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
