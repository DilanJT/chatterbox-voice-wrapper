# Installs uv if needed, then runs scripts/manage.py with a managed Python 3.11 (Windows).
# Without make:  powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 setup
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$env:Path = "$env:USERPROFILE\.local\bin;$env:USERPROFILE\.cargo\bin;$env:Path"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "==> Installing uv (Python package manager)"
    powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
$env:UV = (Get-Command uv).Source
$env:PYTHONIOENCODING = "utf-8"
& $env:UV run --no-project --python 3.11 scripts/manage.py @args
exit $LASTEXITCODE
