"""Source/frozen entry point. Establish project-local paths before third-party imports."""
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
# A packaged build lives in <project>/dist/AimlabVision.
if getattr(sys, "frozen", False) and (ROOT.parent.parent / "config" / "default.json").exists():
    ROOT = ROOT.parent.parent
os.environ["AIMLAB_VISION_ROOT"] = str(ROOT)
for name, relative in {
    "TEMP": ".runtime/tmp", "TMP": ".runtime/tmp", "TMPDIR": ".runtime/tmp",
    "PIP_CACHE_DIR": ".runtime/cache/pip", "UV_CACHE_DIR": ".runtime/cache/uv",
    "PYINSTALLER_CONFIG_DIR": ".runtime/cache/pyinstaller",
    "MPLCONFIGDIR": ".runtime/cache/matplotlib", "XDG_CACHE_HOME": ".runtime/cache",
}.items():
    path = ROOT / relative
    path.mkdir(parents=True, exist_ok=True)
    os.environ[name] = str(path)
sys.dont_write_bytecode = True
tempfile.tempdir = str(ROOT / ".runtime/tmp")
if getattr(sys, "frozen", False):
    bundled = Path(sys._MEIPASS) / "config/default.json"
    default = ROOT / "config/default.json"
    if not default.exists() and bundled.exists():
        default.parent.mkdir(parents=True, exist_ok=True)
        default.write_bytes(bundled.read_bytes())

if __name__ == "__main__":
    from aimvision.app import main
    raise SystemExit(main())
