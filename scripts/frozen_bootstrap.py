"""Runs before third-party PyInstaller runtime hooks; no external temp/cache files."""
import os
from pathlib import Path
import sys
import tempfile

project = Path(sys.executable).resolve().parent
if (project.parent.parent / "config/default.json").exists():
    project = project.parent.parent
temporary = project / ".runtime/tmp"
temporary.mkdir(parents=True, exist_ok=True)
for name in ("TEMP", "TMP", "TMPDIR"):
    os.environ[name] = str(temporary)
tempfile.tempdir = str(temporary)
sys.dont_write_bytecode = True
