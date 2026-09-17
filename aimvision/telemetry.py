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
        self.capture_waits = deque(maxlen=5000)
        self.detection_times = deque(maxlen=5000)
        self.last_summary = 0.0
        self.frame_count = 0

    def event(self, kind, **data):
        self.file.write(json.dumps({"time": time.time(), "event": kind, **data}, ensure_ascii=False) + "\n")
        self.file.flush()

    @staticmethod
    def _percentiles(values):
        ordered = sorted(values)
        return (ordered[len(ordered) // 2],
                ordered[min(len(ordered) - 1, int(len(ordered) * .95))])

    def frame(self, latency_ms, controller, capture_wait_ms=0.0, detection_ms=0.0):
        self.frame_count += 1
        self.latencies.append(latency_ms)
        self.capture_waits.append(capture_wait_ms)
        self.detection_times.append(detection_ms)
        now = time.perf_counter()
        if now - self.last_summary >= 2:
            age_p50, age_p95 = self._percentiles(self.latencies)
            capture_p50, capture_p95 = self._percentiles(self.capture_waits)
            detection_p50, detection_p95 = self._percentiles(self.detection_times)
            self.event("metrics", state=controller.state, frames=self.frame_count, attempted_shots=controller.shots,
                       observed_disappearances=controller.disappearances,
                       frame_age_p50_ms=age_p50, frame_age_p95_ms=age_p95,
                       capture_wait_p50_ms=capture_p50, capture_wait_p95_ms=capture_p95,
                       detection_p50_ms=detection_p50, detection_p95_ms=detection_p95)
            self.last_summary = now

    def close(self):
        self.file.close()
