"""Construct and close the launcher while withdrawn; sends no mouse input."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run
from unittest.mock import patch
import tkinter as tk
from aimvision.config import local_path
from aimvision.gui import launch

original = tk.Tk


def hidden_root():
    root = original()
    root.withdraw()
    root.after(400, root.destroy)
    return root


with patch.object(tk, "Tk", hidden_root):
    launch(local_path("config/local.json"))
print("GUI construction and event loop: OK")
