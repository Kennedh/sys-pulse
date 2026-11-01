param([switch]$Zip)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$taskPython = Join-Path $taskRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython = 'python' }
& $taskPython tools/build_release.py
if ($LASTEXITCODE -ne 0) { throw 'O empacotamento não concluiu.' }
Write-Output 'Pronto: dist/releases'
exit 0
