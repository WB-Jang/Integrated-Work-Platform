import re
import shutil
from concurrent.futures import ThreadPoolExecutor

from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from read_docx_util import read_docx, read_file_sections, read_file_with_llm_chunks, _is_heading_style, _is_bold_only_line
from logger import get_logger

log = get_logger("summarizer")

# 표 마커 패턴 (read_docx_util._table_to_text 가 삽입하는 형식)
_TABLE_RE = re.compile(r"\[Table Start\].*?\[Table End\]", re.DOTALL)


def _strip_tables(text: str) -> str:
    """섹션 텍스트에서 표 마크업을 제거하고 순수 텍스트만 반환."""
    return _TABLE_RE.sub("", text).strip()


# ─── 압축 체인 ──────────────────────────────────────────────────────────────

def get_compress_chain(llm):
    template = """[Context]
이 텍스트는 금융기관 내부 문서의 섹션 일부입니다.
압축본은 보고서 작성 또는 후속 검색(RAG)에 활용됩니다.

[Objective]
핵심 논점·수치·결론을 유지하면서 원문의 절반 이하 분량으로 압축하세요.
표(Table)는 절대 수정하지 마세요.

[Style]
원문의 공식 문서 문체를 유지하세요. 단어 순화·재해석 금지.

[Tone]
중립적·객관적. 원문에 없는 내용 추가 금지.

[Response]
압축된 텍스트만 출력하세요. 설명·주석·마크다운 제목 없이.

[섹션 제목]: {title}
[원문]:
{text}

[축약본]:
"""
    prompt = PromptTemplate.from_template(template)
    return prompt | llm | StrOutputParser()


def compress_document(file_path, llm, progress_callback=None, config: dict | None = None):
    """
    각 섹션의 텍스트(표 제외)를 LLM으로 압축합니다.
    표가 포함된 섹션은 표 외 텍스트만 압축하고, 표 마크업은 그대로 보존합니다.
    원본 구조와 1:1 매핑이 필요하므로 섹션 순서를 유지하며 병렬 처리합니다.
    """
    if config:
        sections = read_file_with_llm_chunks(file_path, config)
    else:
        sections = read_file_sections(file_path)
    compress_chain = get_compress_chain(llm)

    # 빈 섹션 제거 (원본 인덱스 보존)
    valid_sections = [
        (i, s) for i, s in enumerate(sections)
        if (s.get("content") or "").strip()
    ]
    total_steps = len(valid_sections)
    current_step = [0]

    def _compress_one(item):
        _idx, section = item
        title = section.get("title", "제목 없음")
        content = section.get("content", "")
        has_tables = bool(_TABLE_RE.search(content))
        if has_tables:
            text_only = _strip_tables(content)
            if text_only.strip():
                compressed_text = compress_chain.invoke({"title": title, "text": text_only})
            else:
                compressed_text = ""
            tables = _TABLE_RE.findall(content)
            combined = compressed_text
            if tables:
                combined = combined + "\n\n" + "\n\n".join(tables)
        else:
            combined = compress_chain.invoke({"title": title, "text": content})
        return {
            "title": title,
            "original_chars": len(content),
            "compressed_chars": len(combined),
            "compressed": combined,
            "has_tables": has_tables,
        }

    # 섹션 압축 병렬 실행 — ThreadPoolExecutor.map 은 입력 순서 유지
    compressed_sections: list = []
    workers = min(len(valid_sections), SECTION_PARALLEL_WORKERS) if valid_sections else 1
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(_compress_one, valid_sections):
            compressed_sections.append(res)
            log.info(
                "섹션 압축 완료: %s (%d → %d자)",
                res["title"], res["original_chars"], res["compressed_chars"],
            )
            current_step[0] += 1
            if progress_callback:
                progress_callback(current_step[0], total_steps, f"축약 중: {res['title']}")

    total_orig = sum(s["original_chars"] for s in compressed_sections)
    total_comp = sum(s["compressed_chars"] for s in compressed_sections)

    return {
        "sections": compressed_sections,
        "total_original_chars": total_orig,
        "total_compressed_chars": total_comp,
        "reduction_rate": round((1 - total_comp / total_orig) * 100, 1) if total_orig > 0 else 0,
    }


def create_compressed_docx(original_path: str, compressed_sections: list[dict], output_path: str):
    """
    원본 DOCX 양식을 유지하면서 섹션별 텍스트만 축약본으로 교체한 새 DOCX 생성.
    - DOCX 원본: 표·스타일 보존하면서 텍스트만 교체
    - HWP/PDF 원본: 압축 텍스트로 새 DOCX 생성 (원본 포맷 재현 불가)
    """
    import os
    import docx as _docx
    from docx.oxml.ns import qn
    from lxml import etree

    ext = os.path.splitext(original_path)[1].lower()

    # HWP / PDF → 새 DOCX 생성 (원본 구조 재현 불가)
    if ext != '.docx':
        doc = _docx.Document()
        for s in compressed_sections:
            doc.add_heading(s['title'], level=1)
            clean_text = _TABLE_RE.sub('', s['compressed']).strip()
            if clean_text:
                doc.add_paragraph(clean_text)
        doc.save(output_path)
        log.info("압축 DOCX 생성 완료 (새 문서, 원본=%s): %s", ext, output_path)
        return

    compressed_map = {s["title"]: s["compressed"] for s in compressed_sections}

    shutil.copy2(original_path, output_path)
    doc = _docx.Document(output_path)
    body = doc.element.body

    # body 직접 자식 중 <w:p> 만 추적 (테이블 내부 단락 제외)
    body_para_map: dict = {}
    for p in doc.paragraphs:
        if p._element.getparent() is body:
            body_para_map[id(p._element)] = p

    # 섹션별 body-level content paragraph elements 수집
    current_section: str | None = None
    section_para_elems: dict[str, list] = {}

    for elem in list(body):
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag == "p":
            para = body_para_map.get(id(elem))
            if para is None:
                continue
            if _is_heading_style(para) or _is_bold_only_line(para):
                current_section = para.text.strip()
            elif current_section and para.text.strip():
                section_para_elems.setdefault(current_section, []).append(elem)
        # tag == 'tbl' → 복사된 파일이므로 자동 보존

    # 섹션별 텍스트 교체
    for title, compressed_text in compressed_map.items():
        if not compressed_text:
            continue
        elems = section_para_elems.get(title, [])
        if not elems:
            continue

        first_elem = elems[0]

        # 단락 속성(pPr) 보존, 나머지 자식 제거
        pPr = first_elem.find(qn("w:pPr"))
        for child in list(first_elem):
            if pPr is None or child is not pPr:
                first_elem.remove(child)

        # 새 run에 압축 텍스트 삽입 (표 마크업은 원본 <w:tbl>로 이미 보존되므로 제거)
        clean_text = _TABLE_RE.sub("", compressed_text).strip()
        new_r = etree.SubElement(first_elem, qn("w:r"))
        new_t = etree.SubElement(new_r, qn("w:t"))
        new_t.text = clean_text
        if clean_text != clean_text.strip():
            new_t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

        # 나머지 content 단락 제거 (표 행은 body 직하 <w:p>가 아니므로 영향 없음)
        for elem in elems[1:]:
            parent = elem.getparent()
            if parent is not None:
                parent.remove(elem)

    doc.save(output_path)
    log.info("압축 DOCX 생성 완료: %s", output_path)


# ─── 요약 체인 ──────────────────────────────────────────────────────────────

def get_section_summary_chain(llm):
    template = """[Context]
이 텍스트는 금융기관 내부 문서의 섹션 일부입니다.
요약본은 문서 전체의 종합 요약 생성에 사용됩니다.

[Objective]
섹션의 핵심 논점·사실·결론을 빠짐없이 포함하여 간결하게 요약하세요.

[Style]
원문 문체를 유지하되, 불필요한 반복·부연은 제거하세요.

[Tone]
중립적·객관적. 원문에 없는 내용 추가 금지.

[Response]
요약문만 출력하세요. 설명·주석·마크다운 제목 없이.

[섹션 제목]: {title}
[텍스트]:
{text}

[요약]:
"""
    prompt = PromptTemplate.from_template(template)
    return prompt | llm | StrOutputParser()


def get_combine_summary_chain(llm):
    template = """[Context]
아래 텍스트는 금융기관 내부 문서에서 추출된 섹션별 요약들입니다.

[Objective]
섹션별 요약들을 통합하여 문서 전체의 핵심 내용을 담은 종합 요약 하나를 작성하세요.

[Style]
논리적 흐름을 유지하고, 중복 내용은 제거하세요.
공식 보고서 문체로 작성하세요.

[Tone]
중립적·객관적. 원문 요약에 없는 내용 추가 금지.

[Audience]
경영진 또는 업무 담당자 (보고용)

[Response]
종합 요약문만 출력하세요. 섹션 제목·마크다운 없이.

[섹션별 요약]:
{summaries}

[종합 요약]:
"""
    prompt = PromptTemplate.from_template(template)
    return prompt | llm | StrOutputParser()


def get_single_summary_chain(llm):
    """짧은 문서용 — 전체 텍스트를 한 번의 호출로 요약."""
    template = """[Context]
아래는 금융기관 내부 문서 전문입니다.
요약본은 경영진 보고 또는 업무 참고용으로 활용됩니다.

[Objective]
문서의 핵심 논점·사실·결론을 빠짐없이 포함하여 간결하게 요약하세요.

[Style]
논리적 흐름을 유지하고, 불필요한 반복·부연은 제거하세요.
공식 보고서 문체로 작성하세요.

[Tone]
중립적·객관적. 원문에 없는 내용 추가 금지.

[Audience]
경영진 또는 업무 담당자 (보고용)

[Response]
요약문만 출력하세요. 마크다운 제목·설명 없이.

[문서]:
{text}

[요약]:
"""
    prompt = PromptTemplate.from_template(template)
    return prompt | llm | StrOutputParser()


# Fast-path 임계치 — 이 미만이면 단일 호출로 요약
SINGLE_CALL_SECTIONS_THRESHOLD = 2
SINGLE_CALL_CHARS_THRESHOLD    = 3000

# 섹션 병렬 요약 워커 수 (Rate Limit 고려)
SECTION_PARALLEL_WORKERS = 8


def hierarchical_summarize(file_path, llm, progress_callback=None, config: dict | None = None):
    """계층적 요약. 짧은 문서는 단일 호출, 긴 문서는 섹션 병렬 처리."""
    if config:
        sections = read_file_with_llm_chunks(file_path, config)
    else:
        sections = read_file_sections(file_path)

    # 빈 섹션 제거
    sections = [
        s for s in sections
        if (s.get("content") or "").strip()
    ]

    total_chars = sum(len(s.get("content", "")) for s in sections)
    log.info("문서 요약: %d개 섹션 · 총 %d자", len(sections), total_chars)

    # ── Fast-path: 짧은 문서는 단일 호출로 처리 + 스트리밍 ───────────────
    if (len(sections) <= SINGLE_CALL_SECTIONS_THRESHOLD
            or total_chars <= SINGLE_CALL_CHARS_THRESHOLD):
        full_text = "\n\n".join(
            f"## {s.get('title', '제목 없음')}\n{s.get('content', '')}"
            for s in sections
        )
        single_chain = get_single_summary_chain(llm)

        # 스트리밍 시도 — 토큰 도착 시마다 progress_callback 에 부분 텍스트 전달
        partial = []
        try:
            for token in single_chain.stream({"text": full_text}):
                if token:
                    partial.append(token)
                    if progress_callback:
                        progress_callback(
                            1, 2,
                            f"__STREAM__{''.join(partial)}",
                        )
            final_summary = ''.join(partial)
        except Exception:
            # 스트리밍 미지원/오류 → invoke 폴백
            if progress_callback:
                progress_callback(1, 2, "단일 호출 요약 중...")
            final_summary = single_chain.invoke({"text": full_text})

        if progress_callback:
            progress_callback(2, 2, "단일 요약 완료")

        section_summaries = [
            {"title": s.get("title", "제목 없음"),
             "summary": "(통합 요약으로 처리됨)"}
            for s in sections
        ]
        return {
            "section_summaries": section_summaries,
            "final_summary": final_summary,
        }

    # ── 일반 path: 섹션 병렬 요약 ───────────────────────────────────────
    section_chain = get_section_summary_chain(llm)
    combine_chain = get_combine_summary_chain(llm)

    total_steps = len(sections) + 2
    current_step = 0

    def _summarize_one(idx_and_section):
        idx, section = idx_and_section
        title = section.get("title", "제목 없음")
        content = section.get("content", "")
        summary = section_chain.invoke({"title": title, "text": content})
        return idx, {"title": title, "summary": summary}

    # ThreadPoolExecutor 로 섹션 요약 병렬 실행
    section_summaries: list[dict] = [None] * len(sections)  # type: ignore
    workers = min(len(sections), SECTION_PARALLEL_WORKERS)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for idx, summ in ex.map(_summarize_one, enumerate(sections)):
            section_summaries[idx] = summ
            current_step += 1
            if progress_callback:
                progress_callback(
                    current_step, total_steps,
                    f"섹션 요약 중: {summ['title']}",
                )

    # None (실패 등) 제거
    section_summaries = [s for s in section_summaries if s]

    # ── combine 단계 ──────────────────────────────────────────────────
    GROUP_SIZE = 3
    if len(section_summaries) > GROUP_SIZE:
        # 중간 요약도 병렬 처리
        groups = [
            section_summaries[i:i + GROUP_SIZE]
            for i in range(0, len(section_summaries), GROUP_SIZE)
        ]

        def _combine_group(group):
            combined_text = "\n\n".join(
                f"### {s['title']}\n{s['summary']}" for s in group
            )
            return combine_chain.invoke({"summaries": combined_text})

        with ThreadPoolExecutor(max_workers=min(len(groups), 4)) as ex:
            grouped_summaries = list(ex.map(_combine_group, groups))

        current_step += 1
        if progress_callback:
            progress_callback(current_step, total_steps, "중간 요약 통합 중...")

        all_mid = "\n\n".join(
            f"[파트 {i+1}]\n{s}" for i, s in enumerate(grouped_summaries)
        )
        final_summary = combine_chain.invoke({"summaries": all_mid})
    else:
        # 1~3개 섹션 — combine 1회만
        combined_text = "\n\n".join(
            f"### {s['title']}\n{s['summary']}" for s in section_summaries
        )
        final_summary = combine_chain.invoke({"summaries": combined_text})

    current_step += 1
    if progress_callback:
        progress_callback(current_step, total_steps, "최종 요약 완료")

    return {
        "section_summaries": section_summaries,
        "final_summary": final_summary,
    }
