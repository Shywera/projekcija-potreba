@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" goto build
.venv\Scripts\python.exe -c "import fastapi, uvicorn, pandas" 1>nul 2>nul
if errorlevel 1 goto rebuild
goto run

:rebuild
echo [Nabava] Postojeci .venv ne radi na ovom racunalu - ponovo gradim...
rmdir /s /q ".venv" 2>nul

:build
echo [Nabava] Kreiram okruzenje i instaliram ovisnosti (jednom, ~1-2 min)...
py -3 -m venv .venv
if errorlevel 1 goto nopy
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt

:run
echo.
echo [Nabava] Pokrecem server na http://localhost:8602
echo Za prekid: CTRL+C pa zatvori prozor.
.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8602
echo.
echo Server je zaustavljen.
pause
goto :eof

:nopy
echo.
echo GRESKA: Python nije pronadjen ("py" ne radi).
echo Instaliraj Python 3 s python.org i ukljuci "Add Python to PATH", pa pokreni run.bat ponovno.
echo.
pause
