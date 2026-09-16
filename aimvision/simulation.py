"""Deterministic rendered scene; never imports the Windows mouse backend."""
import json
import math
import time
import cv2
import numpy as np
from .config import Config, local_path
from .controller import Controller
from .detector import Detector, annotate
from .model import Frame


def scenario(mode, required_hits=12, artifacts=False):
    cfg = Config(mode=mode, counts_per_radian_x=2600, counts_per_radian_y=2600, calibrated_size=[800, 600])
    controller, detector = Controller(cfg), Detector(cfg)
    controller.arm()
    focal = 800 / (2 * math.tan(math.radians(cfg.horizontal_fov) / 2))
    rng = np.random.default_rng(20260916)
    points = [(-.22, -.12), (.2, .13), (-.05, .22)]
    yaw = pitch = 0.0
    hits = shots = moves = 0
    processing = []
    initial = None
    for sequence in range(1, 3601):
        now = sequence / 120
        image = np.full((600, 800, 3), 24, dtype=np.uint8)
        projected = []
        for x, y in points:
            px = 400 + focal * math.tan(x - yaw)
            py = 300 + focal * math.tan(y - pitch)
            projected.append((px, py))
            if 0 < px < 800 and 0 < py < 600:
                cv2.circle(image, (round(px), round(py)), 12, (255, 220, 0), -1)
        frame = Frame(image, now, sequence, (400.0, 300.0), (800, 600))
        started = time.perf_counter()
        targets, _ = detector.detect(frame)
        action = controller.update(frame, targets, now)
        processing.append((time.perf_counter() - started) * 1000)
        if initial is None:
            initial = annotate(frame, targets, f"SIMULATION | {mode}")
        if action.kind == "move":
            yaw += action.dx / 2600
            pitch += action.dy / 2600
            moves += 1
        elif action.kind == "click":
            shots += 1
            index = min(range(len(points)), key=lambda i: math.hypot(projected[i][0] - 400, projected[i][1] - 300))
            if math.hypot(projected[index][0] - 400, projected[index][1] - 300) <= 12:
                hits += 1
                # New target stays away from the just-hit target's disappearance region.
                points[index] = (yaw + float(rng.choice([-1, 1])) * float(rng.uniform(.14, .35)),
                                 pitch + float(rng.uniform(-.22, .22)))
        elif action.kind == "pause":
            raise AssertionError(f"Simulation paused: {action.reason}")
        if hits >= required_hits:
            break
    if hits < required_hits or hits != shots:
        raise AssertionError(f"Simulation failed: hits={hits}, shots={shots}, state={controller.state}")
    result = {"mode": mode, "simulated_seconds": round(now, 3), "hits": hits, "shots": shots,
              "moves": moves, "frames": sequence, "processing_p50_ms": float(np.percentile(processing, 50)),
              "processing_p95_ms": float(np.percentile(processing, 95)),
              "note": "Synthetic stationary targets only; not an Aimlabs performance or detection-risk measurement."}
    if artifacts:
        path = local_path(f"artifacts/simulation-{mode}.png")
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), initial)
    return result


def run_simulation():
    results = [scenario(mode, artifacts=True) for mode in ("direct", "baseline", "smooth")]
    path = local_path("artifacts/simulation.json")
    path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    print(f"Saved: {path}")
    return 0
