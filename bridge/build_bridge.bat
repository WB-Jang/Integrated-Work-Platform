@echo off
REM ============================================================
REM  IWP Outlook Bridge - single EXE build script
REM  Run once on a "build" Windows PC with Python + pywin32.
REM  Output: dist\outlook_bridge.exe  -> distribute to user PCs
REM  (This file is ASCII-only on purpose: Korean text in a .bat
REM   breaks under the CP949 console codepage. See README.md.)
REM ============================================================
setlocal
cd /d "%~dp0"

echo [1/2] Installing build dependencies...
pip install pyinstaller pywin32 python-docx pypdf
if errorlevel 1 goto :fail

echo [2/2] Building EXE...
REM outlook_agent / logger live in ..\src and are imported lazily inside
REM handler functions, so PyInstaller cannot auto-detect them -> list them
REM as explicit hidden imports (otherwise: "No module named 'outlook_agent'"
REM at runtime, because the onefile exe cannot see the repo's src\ folder).
pyinstaller --onefile --name outlook_bridge --paths ..\src --hidden-import win32com --hidden-import win32com.client --hidden-import pythoncom --hidden-import pywintypes --hidden-import outlook_agent --hidden-import logger --collect-submodules win32com outlook_bridge.py
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo  Build complete: %~dp0dist\outlook_bridge.exe
echo  Copy this file to user PCs and run it.
echo ============================================================
pause
exit /b 0

:fail
echo.
echo *** BUILD FAILED - see the messages above. ***
pause
exit /b 1
