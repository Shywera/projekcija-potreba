@echo off
cd /d "%~dp0"
echo [Nabava] Povlacim zadnje promjene s GitHuba...
git pull
if errorlevel 1 goto err
echo.
echo [Nabava] Osvjezavam ovisnosti (ako se sto promijenilo)...
if not exist ".venv\Scripts\python.exe" goto skip
.venv\Scripts\python.exe -m pip install -r requirements.txt --quiet --disable-pip-version-check
:skip
echo.
echo [Nabava] Gotovo. Pokreni run.bat za start servera.
pause
goto :eof
:err
echo.
echo GRESKA pri "git pull". Provjeri poruku iznad (npr. lokalne izmjene ili nema interneta).
pause
