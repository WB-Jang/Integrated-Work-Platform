import os
import re
import docx

from logger import get_logger

log = get_logger("read_docx_util")


# ── 내부 유틸 ────────────────────────────────────────────────────────────────

def _is_heading_style(paragraph) -> bool:
    """Word의 Heading 스타일이면 True"""
    try:
        name = (paragraph.style.name or '').lower()
    except Exception:
        return False
    return name.startswith('heading') or name.startswith('title') or name.startswith('제목')


def _is_bold_only_line(paragraph) -> bool:
    """문단의 모든 텍스트 런이 굵게(bold)이면 True (제목으로 간주)"""
    runs = [r for r in paragraph.runs if r.text and r.text.strip()]
    if not runs:
        return False
    return all(bool(r.bold) for r in runs)


def _table_to_html(table) -> str:
    """표를 HTML로 변환 (화면 표시용)."""
    rows_html = []
    for row in table.rows:
        cells = ''.join(f'<td>{cell.text.strip()}</td>' for cell in row.cells)
        rows_html.append(f'<tr>{cells}</tr>')
    return (
        '\n[Table Start]\n<table border="1" style="border-collapse:collapse;">'
        + ''.join(rows_html)
        + '</table>\n[Table End]\n'
    )


def _table_to_markdown(table) -> str:
    """
    표를 마크다운 형식으로 변환 (LLM 청킹용).
    LLM이 구조를 이해하기 쉬운 형태로 변환.
    """
    if not table.rows:
        return ""
    rows = []
    for i, row in enumerate(table.rows):
        cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
        rows.append("| " + " | ".join(cells) + " |")
        if i == 0:
            rows.append("| " + " | ".join(["---"] * len(cells)) + " |")
    return "\n[TABLE START]\n" + "\n".join(rows) + "\n[TABLE END]\n"


def _iter_block_items(parent):
    """문서의 본문에서 문단/표를 등장 순서대로 yield"""
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph
    from docx.table import Table

    if hasattr(parent, 'element'):
        body = parent.element.body
    else:
        body = parent

    for child in body.iterchildren():
        if child.tag == qn('w:p'):
            yield Paragraph(child, parent)
        elif child.tag == qn('w:tbl'):
            yield Table(child, parent)


# ── DOCX 파싱 ────────────────────────────────────────────────────────────────

def read_docx(file_path: str) -> list[dict]:
    """
    DOCX 문서를 섹션 단위로 파싱 (기존 방식 유지).
    제목(Heading 스타일 또는 볼드체로만 구성된 문단)으로 섹션 구분.
    표는 HTML 형식으로 변환.

    Returns:
        list of dict: [{"title": str, "content": str}, ...]
    """
    doc = docx.Document(file_path)
    sections = []
    current_title = "Introduction"
    buffer = []

    for block in _iter_block_items(doc):
        from docx.text.paragraph import Paragraph
        from docx.table import Table

        if isinstance(block, Paragraph):
            text = block.text.strip()
            if not text:
                continue

            is_title = _is_heading_style(block) or _is_bold_only_line(block)

            if is_title:
                if buffer:
                    sections.append({
                        "title": current_title,
                        "content": "\n".join(buffer),
                    })
                current_title = text
                buffer = []
            else:
                buffer.append(text)
        elif isinstance(block, Table):
            buffer.append(_table_to_html(block))

    if buffer:
        sections.append({
            "title": current_title,
            "content": "\n".join(buffer),
        })

    return sections


def read_docx_as_text(file_path: str) -> str:
    """
    DOCX 문서를 LLM 청킹용 전체 텍스트로 변환.
    표는 마크다운 형식으로 변환하여 LLM이 구조를 이해할 수 있도록.
    """
    doc = docx.Document(file_path)
    parts = []

    for block in _iter_block_items(doc):
        from docx.text.paragraph import Paragraph
        from docx.table import Table

        if isinstance(block, Paragraph):
            text = block.text.strip()
            if not text:
                continue
            is_title = _is_heading_style(block) or _is_bold_only_line(block)
            if is_title:
                parts.append(f"\n## {text}\n")
            else:
                parts.append(text)
        elif isinstance(block, Table):
            parts.append(_table_to_markdown(block))

    return "\n".join(parts)


# ── PDF 파싱 ────────────────────────────────────────────────────────────────

def read_pdf_as_text(file_path: str) -> str:
    """PDF 텍스트 추출.

    1차로 pypdf 로 추출하고, 결과가 비거나 너무 짧으면(일부 PDF는 pypdf 가 구조를
    제대로 파싱하지 못함) pypdfium2(Chrome PDF 엔진)로 재시도하여 더 많은 텍스트를
    채택한다. 두 엔진 모두 텍스트가 없으면 빈 문자열을 반환한다(= 이미지/스캔 PDF로
    텍스트 레이어가 없는 경우. 이 경우 상위에서 사용자에게 안내).
    """
    text = ""
    # 1) pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        pages = [(page.extract_text() or "") for page in reader.pages]
        text = "\n\n".join(t for t in pages if t.strip())
    except Exception as e:
        log.warning("PDF 파싱 오류(pypdf) (%s): %s", file_path, e)

    # 2) pypdf 결과가 빈약하면 pypdfium2 로 재시도
    if len(text.strip()) < 20:
        try:
            import pypdfium2 as pdfium
            doc = pdfium.PdfDocument(file_path)
            parts = []
            for i in range(len(doc)):
                tp = doc[i].get_textpage()
                parts.append(tp.get_text_range() or "")
            alt = "\n\n".join(t for t in parts if t.strip())
            if len(alt.strip()) > len(text.strip()):
                text = alt
        except Exception as e:
            log.debug("PDF 파싱(pypdfium2) 실패 (%s): %s", file_path, e)

    return text


def pdf_has_text(file_path: str) -> bool:
    """PDF 에 추출 가능한 텍스트 레이어가 있는지 여부."""
    return len(read_pdf_as_text(file_path).strip()) >= 20


def read_pdf_sections(file_path: str) -> list[dict]:
    """PDF를 단일 섹션으로 반환 (LLM 청킹 전 단계에서 사용)."""
    text = read_pdf_as_text(file_path)
    if not text:
        return []
    return [{"title": os.path.splitext(os.path.basename(file_path))[0], "content": text}]


# ── HWP 파싱 ────────────────────────────────────────────────────────────────

def _read_hwpx_as_text(file_path: str) -> str:
    """
    HWPX (ZIP + XML) 자체 파서.
    Contents/section*.xml 의 <hp:t> / <hc:t> 텍스트 노드를 추출.
    """
    import zipfile
    import re as _re

    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            section_names = sorted(
                n for n in z.namelist()
                if n.startswith('Contents/section') and n.endswith('.xml')
            )
            if not section_names:
                # 일부 HWPX 변형: 다른 위치의 XML 시도
                section_names = sorted(
                    n for n in z.namelist()
                    if n.endswith('.xml') and ('section' in n.lower() or 'content' in n.lower())
                )
            text_parts: list[str] = []
            # <ns:t ...>텍스트</ns:t> 의 텍스트만 추출 (네임스페이스 무관)
            t_re = _re.compile(r'<[^/<>]*:t(?:\s[^<>]*)?>([^<]*)</[^<>]*:t>', _re.DOTALL)
            p_re = _re.compile(r'</[^<>]*:p>', _re.DOTALL)
            for name in section_names:
                with z.open(name) as f:
                    xml_text = f.read().decode('utf-8', errors='ignore')
                # <p>를 줄바꿈으로 치환 후 <t>만 모음
                xml_text = p_re.sub('\n', xml_text)
                for m in t_re.finditer(xml_text):
                    chunk = m.group(1)
                    if chunk.strip():
                        # XML 엔티티 디코딩
                        chunk = (chunk.replace('&amp;', '&').replace('&lt;', '<')
                                       .replace('&gt;', '>').replace('&quot;', '"')
                                       .replace('&apos;', "'"))
                        text_parts.append(chunk)
                text_parts.append('\n')
            return '\n'.join(p.strip() for p in text_parts if p.strip())
    except Exception as e:
        log.warning("HWPX 파싱 오류 (%s): %s", file_path, e)
        return ""


def _read_hwpml_as_text(file_path: str) -> str:
    """
    HWPML(.hwp 확장자지만 XML 기반) 파서.
    법제처 등에서 배포하는 .hwp 파일이 이 형식.
    <CHAR>...</CHAR> 와 <TEXT> 노드의 텍스트를 추출, <P> 종료 시 줄바꿈.
    """
    import re as _re
    try:
        with open(file_path, 'rb') as f:
            raw = f.read()
        # 인코딩 감지
        text = raw.decode('utf-8', errors='ignore')
        if '<HWPML' not in text and '<?xml' not in text[:200]:
            return ""
        # <P>를 줄바꿈으로 치환
        text = _re.sub(r'</P\s*>', '\n', text)
        # <CHAR>...</CHAR> 안의 텍스트 추출 (속성 있을 수 있음)
        char_re = _re.compile(r'<CHAR(?:\s[^/<>]*)?>([^<]*)</CHAR>', _re.DOTALL)
        parts: list[str] = []
        for line in text.split('\n'):
            chars = char_re.findall(line)
            if chars:
                joined = ''.join(chars)
                # XML 엔티티 디코딩
                joined = (joined.replace('&nbsp;', ' ')
                                 .replace('&amp;', '&').replace('&lt;', '<')
                                 .replace('&gt;', '>').replace('&quot;', '"')
                                 .replace('&apos;', "'"))
                joined = joined.strip()
                if joined:
                    parts.append(joined)
        return '\n'.join(parts)
    except Exception as e:
        log.warning("HWPML 파싱 오류 (%s): %s", file_path, e)
        return ""


def _is_hwpml(file_path: str) -> bool:
    """파일 헤더로 HWPML(XML 기반 HWP) 여부 판정."""
    try:
        with open(file_path, 'rb') as f:
            head = f.read(256)
        return head.startswith(b'<?xml') and b'HWPML' in head
    except Exception:
        return False


def _read_hwp5_via_pyhwp(file_path: str) -> str:
    """
    HWP 5.x 파일을 pyhwp 의 hwp5txt 또는 Python API 로 텍스트 변환.
    """
    # 1) pyhwp Python API (가장 안정적)
    try:
        from hwp5.dataio import ParseError  # noqa: F401  (모듈 존재 확인)
        from hwp5.hwp5txt import TextTransform
        from hwp5.xmlmodel import Hwp5File
        import io as _io

        tt = TextTransform()
        buf = _io.BytesIO()
        with Hwp5File(file_path) as hwp:
            tt.transform_hwp5_to_text(hwp, buf)
        return buf.getvalue().decode('utf-8', errors='ignore')
    except Exception as e_api:
        log.debug("pyhwp Python API 실패: %s", e_api)

    # 2) hwp5txt CLI fallback (PATH에 있을 때)
    try:
        import subprocess
        result = subprocess.run(
            ["hwp5txt", file_path],
            capture_output=True, timeout=60,
        )
        if result.returncode == 0:
            return result.stdout.decode('utf-8', errors='ignore')
        log.debug("hwp5txt CLI exit=%s stderr=%s",
                  result.returncode, result.stderr.decode('utf-8', errors='ignore')[:200])
    except FileNotFoundError:
        log.debug("hwp5txt CLI 없음")
    except Exception as e_cli:
        log.debug("hwp5txt CLI 실패: %s", e_cli)
    return ""


def read_hwp_as_text(file_path: str) -> str:
    """
    HWP/HWPX 텍스트 추출. 여러 파서를 순차 시도하여 첫 성공 결과를 반환한다.
    - .hwpx → ZIP+XML 자체 파서
    - .hwp  → HWPML(XML) → pyhwp(HWP5) → (실제로 ZIP이면) HWPX 파서 순으로 폴백
    실패 시 빈 문자열을 반환하며, 각 단계의 실패 사유를 로그로 남긴다.
    """
    import zipfile

    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".hwpx":
        text = _read_hwpx_as_text(file_path)
        if text:
            return text
        log.warning("HWPX 자체 파서 실패: %s", file_path)
        return ""

    # .hwp — 형식이 섞여 있을 수 있어 가능한 파서를 순차적으로 모두 시도한다.
    # 1) HWPML(XML 기반 .hwp)
    if _is_hwpml(file_path):
        text = _read_hwpml_as_text(file_path)
        if text:
            return text
        log.warning("HWPML 파싱 결과 빈 텍스트 — 다음 파서로 폴백: %s", file_path)

    # 2) HWP 5.x (OLE 컴파운드) — pyhwp
    text = _read_hwp5_via_pyhwp(file_path)
    if text:
        return text
    log.warning("pyhwp(HWP5) 추출 실패/빈 텍스트 — ZIP 폴백 시도: %s", file_path)

    # 3) 확장자는 .hwp 이지만 실제로는 ZIP(HWPX) 구조인 경우 폴백
    try:
        if zipfile.is_zipfile(file_path):
            text = _read_hwpx_as_text(file_path)
            if text:
                log.info("HWP 확장자이나 ZIP(HWPX) 구조로 추출 성공: %s", file_path)
                return text
    except Exception as e:
        log.debug("ZIP(HWPX) 폴백 실패: %s", e)

    log.warning(
        "HWP 텍스트 추출 최종 실패 (%s). 파일이 손상되었거나 미지원 형식일 수 있습니다. "
        "pyhwp 설치 여부도 확인하세요(pip install pyhwp).", file_path,
    )
    return ""


def read_hwp_sections(file_path: str) -> list[dict]:
    """HWP를 단일 섹션으로 반환."""
    text = read_hwp_as_text(file_path)
    if not text:
        return []
    return [{"title": os.path.splitext(os.path.basename(file_path))[0], "content": text}]


# ── 통합 파싱 인터페이스 ─────────────────────────────────────────────────────

def read_file_as_text(file_path: str) -> str:
    """
    파일 확장자에 따라 적절한 파싱 방법으로 텍스트 추출 (LLM 청킹용).
    DOCX, PDF, HWP, HWPX 지원.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".docx":
        return read_docx_as_text(file_path)
    elif ext == ".pdf":
        return read_pdf_as_text(file_path)
    elif ext in (".hwp", ".hwpx"):
        return read_hwp_as_text(file_path)
    else:
        log.warning("지원하지 않는 파일 형식: %s", ext)
        return ""


def read_file_sections(file_path: str) -> list[dict]:
    """
    파일을 섹션 목록으로 파싱 (기존 방식, LLM 청킹 없이 사용).
    DOCX, PDF, HWP 지원.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".docx":
        return read_docx(file_path)
    elif ext == ".pdf":
        return read_pdf_sections(file_path)
    elif ext in (".hwp", ".hwpx"):
        return read_hwp_sections(file_path)
    else:
        log.warning("지원하지 않는 파일 형식: %s", ext)
        return []


def read_file_with_llm_chunks(file_path: str, config: dict) -> list[dict]:
    """
    LLM 청킹을 사용하여 파일을 의미 단위 섹션으로 변환.
    반환 형식은 read_docx()와 동일: [{"title": str, "content": str}, ...]
    각 LLM 청크가 하나의 섹션이 됨.

    Args:
        file_path: DOCX / PDF / HWP 파일 경로
        config: 앱 설정 dict (openrouter 필요)

    Returns:
        list of dict: [{"title": str, "content": str}, ...]
    """
    from llm_chunker import chunk_text

    full_text = read_file_as_text(file_path)
    if not full_text.strip():
        log.warning("파일에서 텍스트를 추출할 수 없음: %s", file_path)
        return []

    chunks = chunk_text(full_text, config)
    if not chunks:
        # fallback: 기존 섹션 방식
        log.warning("LLM 청킹 실패. 섹션 방식으로 대체.")
        return read_file_sections(file_path)

    # 각 청크를 섹션으로 변환 (번호 부여)
    sections = []
    for i, chunk in enumerate(chunks, 1):
        # 첫 줄을 제목으로, 나머지를 내용으로
        lines = chunk.strip().split("\n", 1)
        title = lines[0][:60] if lines else f"청크 {i}"
        content = lines[1].strip() if len(lines) > 1 else chunk
        sections.append({"title": title, "content": content})

    return sections
