$ProjectRoot = Split-Path -Parent $PSScriptRoot
$env:TEMP = Join-Path $ProjectRoot '.runtime\tmp'
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
$env:UV_CACHE_DIR = Join-Path $ProjectRoot '.runtime\cache\uv'
$env:PIP_CACHE_DIR = Join-Path $ProjectRoot '.runtime\cache\pip'
$env:PYINSTALLER_CONFIG_DIR = Join-Path $ProjectRoot '.runtime\cache\pyinstaller'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:UV_PYTHON_DOWNLOADS = 'never'
New-Item -ItemType Directory -Force -Path $env:TEMP,$env:UV_CACHE_DIR,$env:PIP_CACHE_DIR,$env:PYINSTALLER_CONFIG_DIR | Out-Null
$ProjectPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
