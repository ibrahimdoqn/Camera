@echo off
REM Tapo Viewer - Windows launcher.
REM Creates an isolated .venv on first run, installs dependencies,
REM then launches the app. Re-running just starts the app.

setlocal
cd /d "%~dp0"

set "VENV_DIR=.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "STAMP=%VENV_DIR%\.deps_installed"

if not exist "%PYTHON_EXE%" (
    echo [Tapo Viewer] .venv bulunamadi, olusturuluyor...
    where py >nul 2>nul
    if %ERRORLEVEL%==0 (
        py -3 -m venv "%VENV_DIR%"
    ) else (
        python -m venv "%VENV_DIR%"
    )
    if errorlevel 1 (
        echo [Tapo Viewer] HATA: venv olusturulamadi. Python 3.10+ kurulu mu?
        pause
        exit /b 1
    )
)

REM Hash requirements.txt -> only re-install when it changes.
for /f "delims=" %%H in ('certutil -hashfile requirements.txt SHA1 ^| findstr /v ":"') do set "REQ_HASH=%%H"
set "REQ_HASH=%REQ_HASH: =%"

set "OLD_HASH="
if exist "%STAMP%" set /p OLD_HASH=<"%STAMP%"

if not "%REQ_HASH%"=="%OLD_HASH%" (
    echo [Tapo Viewer] Bagimliliklar kuruluyor / guncelleniyor...
    "%PYTHON_EXE%" -m pip install --upgrade pip
    "%PYTHON_EXE%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [Tapo Viewer] HATA: pip install basarisiz oldu.
        pause
        exit /b 1
    )
    >"%STAMP%" echo %REQ_HASH%
)

echo [Tapo Viewer] Baslatiliyor...
"%PYTHON_EXE%" main.py %*
endlocal
