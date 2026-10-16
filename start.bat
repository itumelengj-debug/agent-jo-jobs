@echo off
REM Agent Jo Jobs.
REM Name the folder once, relative paths after that, goto rather than
REM parenthesised blocks: a folder called "agent-jo-jobs (1)" breaks anything
REM that expands a path inside a block. If the app stops with an error, this
REM window stays open so the error can be read.
setlocal
title Agent Jo Jobs
cd /d "%~dp0"
echo "%CD%" | findstr /i /c:"\AppData\Local\Temp\" >nul && echo "%CD%" | findstr /i /c:".zip" >nul && goto in_zip
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY goto no_venv
"%PY%" run_jobs.py %*
if errorlevel 1 goto crashed
goto done

:crashed
echo.
echo   Agent Jo Jobs stopped with an error (shown above).
echo   If it says a package is missing, run install.bat again, or send
echo   these lines to support.
echo.
pause
exit /b 1

:no_venv
echo.
echo   No environment here yet. Run install.bat first.
echo.
pause
exit /b 1

:in_zip
echo.
echo   This is running from inside the zip file, so Windows is using a
echo   temporary copy that it deletes later. Nothing set up here will last.
echo.
echo   1. Close this window.
echo   2. Right-click the zip, choose Extract All, pick a folder such as Documents.
echo   3. In the extracted folder, double-click install.bat.
echo.
pause
exit /b 1

:done
endlocal
