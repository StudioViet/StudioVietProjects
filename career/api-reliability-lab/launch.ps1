param([ValidateRange(1024,65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$labPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $labPython)) {
    throw 'Create .venv and install requirements-lock.txt first. See README.md.'
}
Push-Location -LiteralPath $PSScriptRoot
try {
    & $labPython -m uvicorn lab.app:app --host 127.0.0.1 --port $Port
}
finally {
    Pop-Location
}
