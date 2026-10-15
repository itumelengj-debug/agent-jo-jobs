@echo off
REM Agent Jo Jobs.
REM Name the folder once, relative paths after that, goto rather than
REM parenthesised blocks: a folder called "agent-jo-jobs (1)" breaks anything
REM that expands a path inside a block. If the app stops with an error, this
REM window stays open so the error can be read.
setlocal
title Agent Jo Jobs
cd /d "%~dp0"
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY goto no_venv
"%PY%" run_jobs.py %*
if errorlevel 1 goto crashed
goto done

:crashed
echo.
echo   Agent Jo Jobs stopped with an error (shown above).
echo   If it says a package is missing, run install.bat again.
echo.
pause
exit /b 1

:no_venv
echo.
echo   No environment here yet. Run install.bat first.
echo.
pause
exit /b 1

:done
endlocal
