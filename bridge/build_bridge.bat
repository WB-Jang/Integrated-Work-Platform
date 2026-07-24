@echo off
REM ============================================================
REM  IWP Outlook 브릿지 단일 EXE 빌드 스크립트
REM  - Python + pywin32 가 설치된 "빌드용" Windows PC에서 1회 실행
REM  - 결과물: dist\outlook_bridge.exe  → 사용자 PC들에 배포
REM ============================================================
setlocal
cd /d "%~dp0"

echo [1/2] 빌드 의존성 설치...
pip install pyinstaller pywin32 python-docx pypdf

echo [2/2] EXE 빌드...
pyinstaller --onefile --name outlook_bridge ^
  --paths ..\src ^
  --hidden-import win32com ^
  --hidden-import win32com.client ^
  --hidden-import pythoncom ^
  --hidden-import pywintypes ^
  --collect-submodules win32com ^
  outlook_bridge.py

echo.
echo ============================================================
echo  빌드 완료: %~dp0dist\outlook_bridge.exe
echo  이 파일을 사용자 PC에 복사해 실행하세요.
echo ============================================================
pause
