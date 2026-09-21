@echo off
REM Agent Jo Jobs - one-click install.
setlocal
title Agent Jo Jobs - install
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -Path . -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue" >nul 2>&1

set "PY="
call :try_py py -3
if defined PY goto have_py
call :try_py python
if defined PY goto have_py

echo.
echo   Agent Jo Jobs needs Python 3.10 or newer.
powershell -NoProfile -ExecutionPolicy Bypass -File ".\get-python.ps1"
if errorlevel 1 goto no_python
set "PY=py -3"
goto have_py

:try_py
%* -c "import sys; raise SystemExit(0 if sys.version_info[:2]>=(3,10) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=%*"
goto :eof

:no_python
echo   Python wasn't installed. Nothing else was changed.
pause
exit /b 1

:have_py
echo.
echo   Setting up...
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet
if errorlevel 1 goto pip_failed

".venv\Scripts\python.exe" -c "import jobs.server" >nul 2>&1
if errorlevel 1 goto wont_load

powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Agent Jo Jobs.lnk'); $s.TargetPath=(Resolve-Path '.\start.bat').Path; $s.WorkingDirectory=(Resolve-Path '.').Path; $s.IconLocation=(Resolve-Path '.\agent-jo-jobs.ico').Path; $s.Description='Agent Jo Jobs'; $s.Save()" >nul 2>&1

echo.
echo   Ready. A shortcut called "Agent Jo Jobs" is on your desktop.
echo   It opens at http://127.0.0.1:8766
echo.
choice /C YN /N /T 30 /D N /M "  Start it now? [Y/N] "
if errorlevel 2 goto done
start "" ".\start.bat"
goto done

:pip_failed
echo.
echo   Installing packages failed. If you're on a corporate network, set
echo   HTTPS_PROXY and run this again.
pause
exit /b 1

:wont_load
echo.
echo   The packages installed, but the app won't load. Run:
echo     .venv\Scripts\python.exe -c "import jobs.server"
echo   to see why.
pause
exit /b 1

:done
endlocal
