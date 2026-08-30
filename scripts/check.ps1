[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
if (Test-Path Variable:\PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $true
}
$projectRoot = Split-Path -Parent $PSScriptRoot
$virtualEnvironmentPython = Join-Path $projectRoot "backend/.venv/Scripts/python.exe"
$pythonPrefixArguments = @()

if (Test-Path -LiteralPath $virtualEnvironmentPython) {
    $pythonExecutable = $virtualEnvironmentPython
}
elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonExecutable = "python"
}
elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonExecutable = "py"
    $pythonPrefixArguments = @("-3.12")
}
else {
    throw "Python 3.12 was not found. Create backend/.venv as described in README.md, then retry."
}

Push-Location (Join-Path $projectRoot "backend")
try {
    & $pythonExecutable @pythonPrefixArguments -m ruff format --check .
    & $pythonExecutable @pythonPrefixArguments -m ruff check .
    & $pythonExecutable @pythonPrefixArguments -m mypy src
    & $pythonExecutable @pythonPrefixArguments -m pytest
}
finally {
    Pop-Location
}

Push-Location (Join-Path $projectRoot "frontend")
try {
    npm run lint
    npm run test
    npm run build
}
finally {
    Pop-Location
}

Push-Location $projectRoot
try {
    docker compose config --quiet
}
finally {
    Pop-Location
}

Write-Host "All RouteWise checks passed." -ForegroundColor Green
