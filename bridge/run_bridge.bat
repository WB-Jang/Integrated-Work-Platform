@echo off
REM 개발/테스트용 — 소스에서 바로 실행 (Python + pywin32 설치된 PC)
REM 배포용 EXE 는 build_bridge.bat 로 만드세요.
setlocal
cd /d "%~dp0"
REM 필요 시 토큰/포트 지정:
REM   set IWP_BRIDGE_TOKEN=원하는토큰
REM   set IWP_BRIDGE_PORT=8899
python outlook_bridge.py
pause
