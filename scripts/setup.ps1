param([string]$PythonPath = 'python.exe')
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\environment.ps1"
Push-Location $ProjectRoot
try {
    if (-not (Test-Path -LiteralPath $ProjectPython)) {
        & $PythonPath -B -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Failed to create project virtual environment.' }
    }
    $ErrorActionPreference = 'Continue'
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        & uv pip install --python $ProjectPython -r requirements.txt
    } else {
        & $ProjectPython -B -m pip install -r requirements.txt
    }
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    Write-Host 'Ready. Run: .\scripts\start.ps1'
} finally { Pop-Location }
