@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" goto build
.venv\Scripts\python.exe -c "import fastapi, uvicorn, pandas" 1>nul 2>nul
if errorlevel 1 goto rebuild
goto net

:rebuild
echo [Nabava] Postojeci .venv ne radi na ovom racunalu - ponovo gradim...
rmdir /s /q ".venv" 2>nul

:build
echo [Nabava] Kreiram okruzenje i instaliram ovisnosti...
py -3 -m venv .venv
if errorlevel 1 goto nopy
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt

:net
set "IP="
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do if not defined IP set "IP=%%a"
if defined IP set "IP=%IP: =%"

echo.
echo Pokrecem Nabava server (WiFi mreza)...
echo   Lokalno:  http://localhost:8602
if defined IP echo   Mreza:    http://%IP%:8602
echo.
echo Sve IPv4 adrese ovog racunala:
ipconfig | findstr /c:"IPv4"
echo.
echo NAPOMENA: bez prijave - svatko na mrezi moze mijenjati podatke (ukljucujuci ucitavanje).
echo Ako drugi uredjaj ne moze pristupiti, pokreni JEDNOM kao Administrator:
echo   netsh advfirewall firewall add rule name="Nabava dev 8602" dir=in action=allow protocol=TCP localport=8602
echo.

.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8602
pause
goto :eof

:nopy
echo.
echo GRESKA: Python nije pronadjen. Instaliraj Python 3 (Add to PATH) pa pokreni ponovno.
echo.
pause
