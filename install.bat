@echo off
REM Agent Jo Jobs - one-click install.
REM
REM Kept small on purpose: it finds a Python, then hands everything else to
REM setup_jobs.py, which records every step and its full output in
REM install.log. Whatever goes wrong, this window stays open and shows it.
REM Relative paths and goto labels only (a folder called "x (1)" breaks
REM parenthesised blocks).
setlocal
title Agent Jo Jobs - install
cd /d "%~dp0"
echo.
echo   Agent Jo Jobs - install
echo   Folder: %CD%
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -Path . -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue" >nul 2>&1

if not exist "setup_jobs.py" goto not_unzipped

set "PY="
call :try_py py -3
if defined PY goto have_py
call :try_py python
if defined PY goto have_py

echo.
echo   Agent Jo Jobs needs Python 3.10 or newer.
powershell -NoProfile -ExecutionPolicy Bypass -File ".\get-python.ps1"
if errorlevel 1 goto no_python
REM The Python just installed isn't on this window's PATH yet, so read the
REM PATH afresh and look again, then try where its installer puts it.
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')"`) do set "PATH=%%P"
call :try_py py -3
if defined PY goto have_py
call :try_py python
if defined PY goto have_py
call :try_py "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined PY goto have_py
goto reopen

:try_py
%* -c "import sys; raise SystemExit(0 if sys.version_info[:2]>=(3,10) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=%*"
goto :eof

:have_py
echo   Python: %PY%
%PY% setup_jobs.py
if errorlevel 1 goto setup_failed

powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Agent Jo Jobs.lnk'); $s.TargetPath=(Resolve-Path '.\start.bat').Path; $s.WorkingDirectory=(Resolve-Path '.').Path; $s.IconLocation=(Resolve-Path '.\agent-jo-jobs.ico').Path; $s.Description='Agent Jo Jobs'; $s.Save()" >nul 2>&1

echo.
echo   Ready. A shortcut called "Agent Jo Jobs" is on your desktop.
echo   It opens at http://127.0.0.1:8766
echo.
choice /C YN /N /T 60 /D N /M "  Start it now? [Y/N] "
if errorlevel 2 goto done
start "Agent Jo Jobs" ".\start.bat"
goto done

:setup_failed
echo.
echo   Setup stopped. The last lines of install.log:
echo   ------------------------------------------------------------------
powershell -NoProfile -Command "Get-Content -Path '.\install.log' -Tail 30 -ErrorAction SilentlyContinue"
echo   ------------------------------------------------------------------
echo   The whole log is install.log in this folder.
echo.
pause
exit /b 1

:not_unzipped
echo.
echo   setup_jobs.py isn't next to install.bat. If you opened the zip and
echo   ran install.bat from inside it, extract the zip first (right-click,
echo   Extract All), then run install.bat from the extracted folder.
echo.
pause
exit /b 1

:no_python
echo   Python wasn't installed. Nothing else was changed.
pause
exit /b 1

:reopen
echo.
echo   Python is installed, but this window can't see it yet.
echo   Close this window and run install.bat again.
pause
exit /b 1

:done
endlocal
