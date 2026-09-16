"""Benchmark full and scaled detection on a project-local reference image."""
import statistics
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import run  # noqa: F401 - establishes project-local runtime paths
import cv2
import numpy as np
from aimvision.config import Config, local_path
from aimvision.detector import Detector
from aimvision.model import Frame


def main():
    path = next(local_path("temp").glob("*.png"))
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    height, width = image.shape[:2]
    for max_width in (0, 1280, 960, 720):
        cfg = Config.load("config/local.json")
        cfg.detection_max_width = max_width
        detector = Detector(cfg)
        elapsed = []
        targets = []
        for sequence in range(15):
            started = time.perf_counter()
            targets, _ = detector.detect(Frame(image, 0, sequence, (width / 2, height / 2),
                                                (width, height)))
            elapsed.append((time.perf_counter() - started) * 1000)
        ordered = sorted(elapsed)
        print({"max_width": max_width, "targets": len(targets),
               "median_ms": round(statistics.median(elapsed), 2),
               "p95_ms": round(ordered[13], 2)})


if __name__ == "__main__":
    main()
