import os
import subprocess
import sys


def _get_soffice_cmd() -> str:
    """플랫폼에 맞는 LibreOffice 실행 파일 경로를 반환합니다."""
    if sys.platform == 'win32':
        candidates = [
            r'C:\Program Files\LibreOffice\program\soffice.exe',
            r'C:\Program Files (x86)\LibreOffice\program\soffice.exe',
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        return 'soffice'   # PATH에 있는 경우 폴백
    return 'libreoffice'   # Linux / macOS


def convert_to_pdf_linux(input_path, output_folder):
    """
    LibreOffice를 사용하여 단일 파일을 PDF로 변환합니다. (Windows/Linux/macOS 공용)
    """
    try:
        cmd = [
            _get_soffice_cmd(),
            '--headless',
            '--convert-to', 'pdf',
            input_path,
            '--outdir', output_folder,
        ]

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=120,
        )

        if result.returncode != 0:
            return False, result.stderr.decode('utf-8', errors='replace')

        return True, "Success"
    except subprocess.TimeoutExpired:
        return False, "Timeout (120s 초과)"
    except FileNotFoundError:
        return False, "LibreOffice를 찾을 수 없습니다. 설치 여부를 확인하세요."
    except Exception as e:
        return False, str(e)

def batch_convert_to_pdf(target_folder, log_queue=None):
    """
    지정된 폴더 내의 Word, PPT 파일을 모두 찾아 PDF로 변환합니다.

    log_queue: queue.Queue 전달 시 ppt_word2pdf.convert_each_to_pdf 와 동일한
               형식으로 각 파일 결과를 ('success'|'error', 파일명, 오류메시지) 로
               put 하고, 완료 후 ('done', '', '') 을 put 한다. (app.py/agent_console.py
               가 이 큐를 폴링하므로 두 변환 엔진의 호출 규약을 통일해야 한다.)
    """
    def _put(status, fname, msg):
        if log_queue is not None:
            log_queue.put((status, fname, msg))

    if not os.path.exists(target_folder):
        _put('error', '', f'폴더를 찾을 수 없습니다: {target_folder}')
        _put('done', '', '')
        return

    # 결과가 저장될 폴더 (원본폴더/pdf_output)
    output_folder = os.path.join(target_folder, "pdf_output")
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    extensions = ('.docx', '.doc', '.pptx', '.ppt')
    files = [f for f in os.listdir(target_folder) if f.lower().endswith(extensions) and not f.startswith('~$')]

    if not files:
        _put('done', '', '')
        return

    for file in files:
        input_path = os.path.join(target_folder, file)
        success, msg = convert_to_pdf_linux(input_path, output_folder)

        if success:
            _put('success', file, '')
        else:
            _put('error', file, msg)

    _put('done', '', '')
