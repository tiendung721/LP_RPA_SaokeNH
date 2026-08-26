$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectDir ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Khong tim thay Python venv: $pythonExe"
}

Set-Location -LiteralPath $projectDir
& $pythonExe "rule_manager.py"
