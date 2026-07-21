@echo off
cd /d "%~dp0"

if not exist "nabava.db" goto nodb
if not exist "backup" mkdir backup
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TS=%%i"
copy /Y "nabava.db" "backup\nabava_%TS%.db" >nul
echo Backup spremljen: backup\nabava_%TS%.db
echo.
pause
goto :eof

:nodb
echo Baza nabava.db jos ne postoji - pokreni app barem jednom (run.bat).
echo.
pause
