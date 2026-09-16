from collections import deque
from datetime import datetime
import json
import time
from .config import local_path


class Telemetry:
    def __init__(self, prefix):
        folder = local_path("logs")
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / f"{prefix}-{datetime.now():%Y%m%d-%H%M%S-%f}.jsonl"
        self.file = self.path.open("w", encoding="utf-8")
        self.latencies = deque(maxlen=5000)
        self.last_summary = 0.0
        self.frame_count = 0

    def event(self, kind, **data):
        self.file.write(json.dumps({"time": time.time(), "event": kind, **data}, ensure_ascii=False) + "\n")
        self.file.flush()

    def frame(self, latency_ms, controller):
        self.frame_count += 1
        self.latencies.append(latency_ms)
        now = time.perf_counter()
        if now - self.last_summary >= 2:
            ordered = sorted(self.latencies)
            self.event("metrics", state=controller.state, frames=self.frame_count, attempted_shots=controller.shots,
                       observed_disappearances=controller.disappearances,
                       processing_p50_ms=ordered[len(ordered)//2],
                       processing_p95_ms=ordered[min(len(ordered)-1, int(len(ordered)*.95))])
            self.last_summary = now

    def close(self):
        self.file.close()
