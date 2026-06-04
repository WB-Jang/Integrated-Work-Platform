"""
Word/PPT → PDF 변환 모듈

Word COM 첫 실행 에러 수정:
- 변환 전 gen_py 캐시 자동 정리
- 기존 WINWORD.EXE 프로세스 종료 후 시작
- 실패 시 1회 재시도 (캐시 재정리 후)
"""
import os
import subprocess
import time
import shutil

import win32com
import win32com.client
from win32com.client import gencache
from pypdf import PdfWriter

ppSaveAsPDF = 32
_gen_py_cleaned = False  # 프로세스당 1회만 정리


def cleanup_gen_py():
    """win32com gen_py 캐시 폴더를 삭제 (COM 에러 예방)."""
    global _gen_py_cleaned
    paths = set()

    gen_attr = getattr(win32com, "__gen_path__", None)
    if gen_attr:
        paths.add(gen_attr)

    try:
        gen_path = gencache.GetGeneratePath()
        if gen_path:
            paths.add(gen_path)
    except Exception:
        pass

    for p in paths:
        if p and os.path.isdir(p):
            try:
                print(f"[cleanup_gen_py] 삭제: {p}", flush=True)
                shutil.rmtree(p, ignore_errors=True)
            except Exception as e:
                print(f"[cleanup_gen_py] 삭제 실패: {e}", flush=True)

    _gen_py_cleaned = True


def _kill_word():
    """실행 중인 WINWORD.EXE를 종료하여 COM 충돌 방지."""
    try:
        result = subprocess.run(
            ["taskkill", "/f", "/im", "WINWORD.EXE"],
            capture_output=True, timeout=10, text=True,
        )
        if "성공" in result.stdout or "SUCCESS" in result.stdout.upper():
            print("[INFO] 기존 Word 프로세스 종료 완료", flush=True)
            time.sleep(1)
    except Exception:
        pass


def get_files(folder_path):
    """폴더 내의 .docx/.doc/.pptx/.ppt 파일 리스트를 반환합니다."""
    extensions = ('.docx', '.doc', '.pptx', '.ppt')
    files = [
        f for f in os.listdir(folder_path)
        if f.lower().endswith(extensions) and not f.startswith('~$')
    ]
    return sorted(files)


def convert_ppt_to_pdf(input_path: str, output_path: str) -> bool:
    """win32com을 사용하여 PPT를 PDF로 변환."""
    powerpoint = None
    presentation = None
    try:
        powerpoint = win32com.client.DispatchEx("PowerPoint.Application")
        presentation = powerpoint.Presentations.Open(input_path, WithWindow=False)
        presentation.SaveAs(output_path, FileFormat=ppSaveAsPDF)
        return True
    except Exception as e:
        print(f"[PPT 변환 에러] {e}", flush=True)
        return False
    finally:
        if presentation:
            try:
                presentation.Close()
            except Exception:
                pass
        if powerpoint:
            try:
                if powerpoint.Presentations.Count == 0:
                    powerpoint.Quit()
            except Exception:
                pass


MAX_RETRY = 5


def _convert_word_to_pdf(input_path: str, output_path: str):
    """Word → PDF 변환 (최대 MAX_RETRY회 시도)."""
    from docx2pdf import convert

    last_error = None
    for attempt in range(MAX_RETRY):
        try:
            if attempt == 0 and not _gen_py_cleaned:
                cleanup_gen_py()
            elif attempt > 0:
                _kill_word()
                cleanup_gen_py()
                time.sleep(2)
            convert(input_path, output_path)
            return
        except Exception as e:
            last_error = e
            print(f"[Word 변환 시도 {attempt+1} 실패] {e}", flush=True)

    raise RuntimeError(f"Word 변환 실패 ({MAX_RETRY}회 시도): {last_error}")


def convert_to_pdf_wrapper(input_path: str, output_path: str):
    """파일 확장자에 따라 적절한 변환 도구 호출 (최대 MAX_RETRY회 시도)."""
    ext = os.path.splitext(input_path)[1].lower()
    if ext in ('.docx', '.doc'):
        _convert_word_to_pdf(input_path, output_path)
    elif ext in ('.pptx', '.ppt'):
        last_error = None
        for attempt in range(MAX_RETRY):
            if attempt > 0:
                _kill_word()
                cleanup_gen_py()
                time.sleep(2)
            if convert_ppt_to_pdf(input_path, output_path):
                return
            last_error = f"PPT 변환 실패 (시도 {attempt+1})"
        raise RuntimeError(f"PowerPoint 변환 실패 ({MAX_RETRY}회 시도): {last_error}")
    else:
        raise ValueError(f"지원하지 않는 확장자: {ext}")


def convert_each_to_pdf(folder_path: str, output_folder: str = None, log_queue=None):
    """여러 Word/PPT 파일을 각각의 PDF 파일로 저장.

    log_queue: queue.Queue 전달 시 각 파일 결과를 ('success'|'error', 파일명, 오류메시지) 형태로 put.
               완료 후 ('done', '', '') 을 put.
    """
    if output_folder is None:
        output_folder = folder_path

    os.makedirs(output_folder, exist_ok=True)
    target_files = get_files(folder_path)

    if not target_files:
        print("[INFO] 변환할 파일이 없습니다.", flush=True)
        if log_queue:
            log_queue.put(('done', '', ''))
        return

    if not _gen_py_cleaned:
        cleanup_gen_py()

    print(f"[INFO] 총 {len(target_files)}개 파일 변환 시작...", flush=True)

    for i, file in enumerate(target_files, 1):
        input_path = os.path.join(folder_path, file)
        output_filename = os.path.splitext(file)[0] + ".pdf"
        output_path = os.path.join(output_folder, output_filename)

        print(f"[{i}/{len(target_files)}] 변환 중: {file}", flush=True)
        try:
            convert_to_pdf_wrapper(input_path, output_path)
            print(f"  [완료] {output_filename}", flush=True)
            if log_queue:
                log_queue.put(('success', file, ''))
        except Exception as e:
            print(f"  [실패] {file} - {e}", flush=True)
            if log_queue:
                log_queue.put(('error', file, str(e)))

    if log_queue:
        log_queue.put(('done', '', ''))


if __name__ == "__main__":
    target_folder = r"C:\변환할_파일_폴더"
    output_folder = r"C:\PDF_출력_폴더"

    print("--- 개별 PDF 변환 시작 ---")
    convert_each_to_pdf(target_folder, output_folder)
    cleanup_gen_py()
    print("완료")
