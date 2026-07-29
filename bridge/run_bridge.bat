@echo off
REM Dev/test only - run the bridge straight from source
REM (needs Python + pywin32). For distribution build the EXE
REM with build_bridge.bat. ASCII-only on purpose (CP949 console).
REM Optional token/port:
REM   set IWP_BRIDGE_TOKEN=your-token
REM   set IWP_BRIDGE_PORT=8899
setlocal
cd /d "%~dp0"
python outlook_bridge.py
pause
