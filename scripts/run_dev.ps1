$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$env:PYTHONPATH = Join-Path $repoRoot "src"
pytest
