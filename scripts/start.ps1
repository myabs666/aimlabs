param([ValidateSet('gui','doctor','preview','tune','calibrate','run','simulate','test')][string]$Mode = 'gui')
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\environment.ps1"
if (-not (Test-Path -LiteralPath $ProjectPython)) { throw 'Run scripts/setup.ps1 first.' }
Push-Location $ProjectRoot
try {
    & $ProjectPython -B run.py $Mode
    if ($LASTEXITCODE -ne 0) { throw "AimVision exited with code $LASTEXITCODE. See logs/." }
} finally { Pop-Location }
