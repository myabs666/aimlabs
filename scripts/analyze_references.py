"""Analyze project-local reference screenshots and save annotated copies."""
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import run  # establishes project-local runtime/cache paths
import cv2
import numpy as np
from aimvision.config import Config, local_path
from aimvision.detector import Detector, annotate
from aimvision.model import Frame


def read_image(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def write_image(path, image):
    success, encoded = cv2.imencode(path.suffix, image)
    if not success:
        raise RuntimeError(f"Could not encode {path}")
    encoded.tofile(path)


def main():
    source = local_path("temp")
    output = local_path("artifacts/reference-analysis")
    output.mkdir(parents=True, exist_ok=True)
    cfg = Config.load("config/local.json")
    detector = Detector(cfg)
    report = []
    paths = sorted([*source.glob("*.png"), *source.glob("*.jpg"), *source.glob("*.jpeg")])
    if not paths:
        raise RuntimeError(f"No reference images in {source}")
    for index, path in enumerate(paths, 1):
        image = read_image(path)
        if image is None:
            raise RuntimeError(f"Could not decode {path}")
        height, width = image.shape[:2]
        frame = Frame(image, 0.0, index, (width / 2, height / 2), (width, height))
        targets, mask = detector.detect(frame)
        result_path = output / f"{index:02d}-detected.png"
        mask_path = output / f"{index:02d}-mask.png"
        write_image(result_path, annotate(frame, targets, f"REFERENCE {index} | targets={len(targets)}"))
        write_image(mask_path, mask)
        report.append({
            "source": path.name,
            "size": [width, height],
            "targets": [{"center": [round(t.x, 2), round(t.y, 2)], "radius": round(t.radius, 2),
                         "quality": round(t.quality, 3)} for t in targets],
            "annotated": result_path.name,
            "mask": mask_path.name,
        })
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Saved: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
