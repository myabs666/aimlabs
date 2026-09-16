$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\environment.ps1"
Push-Location $ProjectRoot
try {
    # PyInstaller replaces these output directories on rebuild. Reject redirected paths.
    foreach ($relativeOutput in @('dist', 'dist\AimlabVision', '.runtime', '.runtime\build')) {
        $checkedOutput = [IO.Path]::GetFullPath((Join-Path $ProjectRoot $relativeOutput))
        if (-not $checkedOutput.StartsWith($ProjectRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Build output escaped project.' }
        if ((Test-Path -LiteralPath $checkedOutput) -and ((Get-Item -LiteralPath $checkedOutput).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Build output must not be a junction/symlink: $checkedOutput"
        }
    }
    # Windows PowerShell 5 may wrap native stderr progress as errors when redirected.
    $ErrorActionPreference = 'Continue'
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        & uv pip install --python $ProjectPython -r requirements-build.txt
    } else {
        & $ProjectPython -B -m pip install -r requirements-build.txt
    }
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed.' }
    $ErrorActionPreference = 'Continue'
    & $ProjectPython -B -m PyInstaller --noconfirm --onedir --console --hide-console hide-early `
        --name AimlabVision --distpath dist --workpath .runtime/build --specpath .runtime/build `
        --runtime-hook "$ProjectRoot\scripts\frozen_bootstrap.py" --add-data "$ProjectRoot\config\default.json;config" `
        --hidden-import unittest.mock --hidden-import uuid `
        --collect-all dxcam --copy-metadata dxcam --copy-metadata numpy --copy-metadata opencv-python --copy-metadata comtypes run.py
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
    Write-Host 'Built: dist\AimlabVision\AimlabVision.exe (keep the entire folder).'
} finally { Pop-Location }
