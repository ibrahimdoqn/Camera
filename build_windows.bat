@echo off
REM Tapo Viewer - Windows packaging script.
REM Builds a standalone, windowed (no console) .exe via PyInstaller.
REM Output: dist\TapoViewer\TapoViewer.exe

setlocal
cd /d "%~dp0"

set "VENV_DIR=.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

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

echo [Tapo Viewer] Bagimliliklar kuruluyor...
"%PYTHON_EXE%" -m pip install --upgrade pip
"%PYTHON_EXE%" -m pip install -r requirements.txt
"%PYTHON_EXE%" -m pip install pyinstaller>=6.0
if errorlevel 1 (
    echo [Tapo Viewer] HATA: pip install basarisiz oldu.
    pause
    exit /b 1
)

if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

echo [Tapo Viewer] PyInstaller calistiriliyor...
"%PYTHON_EXE%" -m PyInstaller --noconfirm --clean TapoViewer.spec
if errorlevel 1 (
    echo [Tapo Viewer] HATA: PyInstaller basarisiz oldu.
    pause
    exit /b 1
)

echo.
echo [Tapo Viewer] Tamamlandi.
echo Calistirmak icin: dist\TapoViewer\TapoViewer.exe
echo.
endlocal
