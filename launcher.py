"""
Integrated Platform Launcher
Ctrl+C / 터미널 종료 시 모든 자식 프로세스를 안전하게 종료합니다.
"""
import subprocess
import sys
import os
import time
import json
import signal
import threading
import socket

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_procs: list = []
_shutdown_called = False


def _resolve_python() -> str:
    """앱 실행에 사용할 Python 인터프리터 경로를 결정.

    프로젝트에 동봉된 .IWP 가상환경의 인터프리터를 최우선으로 사용한다.
    (시스템 python 으로 launcher 를 실행해도 앱은 항상 .IWP 패키지로 구동되도록 보장)
    venv 가 없으면 현재 인터프리터(sys.executable)로 폴백.
    """
    candidates = [
        os.path.join(BASE_DIR, ".IWP", "Scripts", "python.exe"),  # Windows
        os.path.join(BASE_DIR, ".IWP", "bin", "python"),          # Linux/macOS
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    print(
        "[WARNING] .IWP 가상환경 인터프리터를 찾지 못했습니다. "
        "현재 Python 으로 실행합니다 (패키지 누락 가능: 예) No module named docx).",
        flush=True,
    )
    return sys.executable


def _kill_all():
    """모든 자식 프로세스를 안전하게 종료."""
    global _shutdown_called
    if _shutdown_called:
        return
    _shutdown_called = True

    print("\n[종료] 프로세스 종료 중...", flush=True)
    for p in _procs:
        try:
            if p and p.poll() is None:
                p.terminate()
        except Exception:
            pass

    time.sleep(1)
    for p in _procs:
        try:
            if p and p.poll() is None:
                p.kill()
        except Exception:
            pass

    print("[종료] 완료.", flush=True)


def _signal_handler(signum, frame):
    _kill_all()
    os._exit(0)


signal.signal(signal.SIGINT, _signal_handler)
try:
    signal.signal(signal.SIGTERM, _signal_handler)
except (OSError, ValueError):
    pass


def _monitor_app(app_proc):
    """앱 프로세스를 백그라운드에서 모니터링."""
    app_proc.wait()
    if not _shutdown_called:
        print("[INFO] NiceGUI 앱이 종료되었습니다. launcher도 종료합니다.", flush=True)
        _kill_all()
        os._exit(0)


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _kill_port(port: int):
    """해당 포트를 사용 중인 프로세스를 강제 종료 (Windows)."""
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if f":{port} " in line and "LISTENING" in line:
                parts = line.split()
                pid = int(parts[-1])
                if pid and pid != os.getpid():
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                                   capture_output=True, timeout=5)
                    print(f"[INFO] 포트 {port}를 사용 중인 프로세스(PID {pid}) 종료", flush=True)
                    time.sleep(1)
                    return
    except Exception as e:
        print(f"[WARNING] 포트 {port} 정리 실패: {e}", flush=True)


def main():
    config_path = os.path.join(BASE_DIR, "config.json")
    if not os.path.exists(config_path):
        print(f"[ERROR] config.json을 찾을 수 없습니다: {config_path}")
        sys.exit(1)

    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    app_port = config.get("app_port", 8501)

    # 포트 충돌 방지: 이미 사용 중이면 기존 프로세스 종료
    if _port_in_use(app_port):
        print(f"[WARNING] 포트 {app_port} 이미 사용 중. 기존 프로세스를 종료합니다.", flush=True)
        _kill_port(app_port)
        time.sleep(1)
        if _port_in_use(app_port):
            print(f"[ERROR] 포트 {app_port} 해제 실패. 수동으로 종료 후 다시 시도하세요.", flush=True)
            sys.exit(1)
    committee_llm = config.get("committee_llm", {})
    use_local_llm = committee_llm.get("provider", "local") == "local"

    llm_proc = None
    if use_local_llm:
        model_path_raw = config.get("model_path", "")
        model_path = os.path.normpath(
            os.path.join(BASE_DIR, model_path_raw.replace("/", os.sep))
        )
        server_exe_raw = config.get(
            "llama_server_exe",
            "../Committee_Agent_Workspace_Version/llama-b9143-bin-win-cpu-x64/llama-server.exe",
        )
        server_exe = os.path.normpath(
            os.path.join(BASE_DIR, server_exe_raw.replace("/", os.sep))
        )

        if not os.path.isfile(server_exe):
            print(f"[WARNING] llama-server.exe 없음: {server_exe}")
            print("[WARNING] OpenRouter 모드로 시작합니다.")
            use_local_llm = False
        elif not os.path.isfile(model_path):
            print(f"[WARNING] GGUF 모델 없음: {model_path}")
            print("[WARNING] OpenRouter 모드로 시작합니다.")
            use_local_llm = False

    if use_local_llm:
        llm_port = config.get("llm_port", 8080)
        n_ctx = config.get("n_ctx", 4096)
        n_gpu_layers = config.get("n_gpu_layers", 0)

        print(f"[1/3] LLM 서버 시작 중... (포트: {llm_port})", flush=True)
        llm_proc = subprocess.Popen(
            [
                server_exe, "-m", model_path,
                "-t", "8", "-tb", "8",
                "--top-p", "0.9", "--repeat-penalty", "1.15",
                "--host", "0.0.0.0", "--port", str(llm_port),
                "-c", str(n_ctx), "-ngl", str(n_gpu_layers),
            ],
            cwd=os.path.dirname(server_exe),
        )
        _procs.append(llm_proc)
        print("[1/3] LLM 서버 준비 대기 중 (8초)...", flush=True)
        time.sleep(8)
    else:
        print("[1/3] 로컬 LLM 서버 건너뜀 (OpenRouter 모드)", flush=True)

    app_path = os.path.join(BASE_DIR, "src", "app.py")
    if not os.path.isfile(app_path):
        print(f"[ERROR] app.py 없음: {app_path}")
        _kill_all()
        sys.exit(1)

    python_exe = _resolve_python()
    print(f"[2/3] NiceGUI 앱 시작 중... (포트: {app_port})", flush=True)
    print(f"      인터프리터: {python_exe}", flush=True)
    # PYTHONUNBUFFERED=1: Python 수준 stdout/stderr 버퍼를 완전히 비활성화.
    # Windows Console Host 가 자식 프로세스 출력을 배치 버퍼링하는 현상을 방지하여
    # 로그가 Ctrl+C 시점에 한꺼번에 쏟아지는 문제를 해결한다.
    _app_env = os.environ.copy()
    _app_env["PYTHONUNBUFFERED"] = "1"
    app_proc = subprocess.Popen(
        [python_exe, "-u", app_path],
        cwd=BASE_DIR,
        env=_app_env,
    )
    _procs.append(app_proc)

    time.sleep(2)
    print(f"\n[3/3] 브라우저 접속 주소: http://localhost:{app_port}", flush=True)
    print("=" * 50, flush=True)
    print("  종료하려면 Ctrl+C를 누르세요.", flush=True)
    print("=" * 50, flush=True)

    monitor = threading.Thread(target=_monitor_app, args=(app_proc,), daemon=True)
    monitor.start()

    # 메인 루프: 0.5초마다 깨어나 Ctrl+C 처리 가능하도록
    try:
        while not _shutdown_called:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        _kill_all()


if __name__ == "__main__":
    main()
