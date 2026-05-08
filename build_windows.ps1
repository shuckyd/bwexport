# Build a single-file bwexport.exe with PyInstaller.
# Run on a Windows box with Python 3.11+ on PATH. Output: dist\bwexport.exe

$ErrorActionPreference = "Stop"

Write-Host "==> Installing build dependencies..."
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install pyinstaller

Write-Host "==> Building bwexport.exe..."
pyinstaller `
    --onefile `
    --noconsole `
    --clean `
    --name bwexport `
    --collect-submodules keyring.backends `
    --hidden-import keyring.backends.Windows `
    --hidden-import win32timezone `
    run_gui.py

Write-Host ""
Write-Host "==> Done. Output: dist\bwexport.exe"
Write-Host "Copy that single file anywhere on the Windows server. It still needs the bw CLI on PATH:"
Write-Host "    winget install Bitwarden.CLI"
