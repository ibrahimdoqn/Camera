# Tapo Viewer - PowerShell launcher.
# Creates an isolated .venv on first run, installs dependencies,
# then launches the app. Re-running just starts the app.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$VenvDir   = ".venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$Stamp     = Join-Path $VenvDir ".deps_installed"

if (-not (Test-Path $PythonExe)) {
    Write-Host "[Tapo Viewer] .venv bulunamadi, olusturuluyor..."
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        & py -3 -m venv $VenvDir
    } else {
        & python -m venv $VenvDir
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Error "venv olusturulamadi. Python 3.10+ kurulu mu?"
        exit 1
    }
}

# Hash requirements.txt -> only re-install when it changes.
$reqHash = (Get-FileHash -Algorithm SHA1 -Path "requirements.txt").Hash
$oldHash = if (Test-Path $Stamp) { (Get-Content $Stamp -Raw).Trim() } else { "" }

if ($reqHash -ne $oldHash) {
    Write-Host "[Tapo Viewer] Bagimliliklar kuruluyor / guncelleniyor..."
    & $PythonExe -m pip install --upgrade pip
    & $PythonExe -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Error "pip install basarisiz oldu."
        exit 1
    }
    Set-Content -Path $Stamp -Value $reqHash
}

Write-Host "[Tapo Viewer] Baslatiliyor..."
& $PythonExe main.py @args
