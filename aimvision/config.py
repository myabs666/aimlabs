from dataclasses import asdict, dataclass, field, fields
import json
import math
import os
from pathlib import Path


ROOT = Path(os.environ.get("AIMLAB_VISION_ROOT", Path(__file__).resolve().parents[1])).resolve()


def local_path(value: str | Path) -> Path:
    path = Path(value)
    path = (path if path.is_absolute() else ROOT / path).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError(f"Path must stay inside project: {path}")
    return path


@dataclass
class Config:
    window_title: str = "aimlab"
    process_names: list[str] = field(default_factory=lambda: ["aimlab_tb.exe", "aimlab.exe"])
    device_idx: int = 0
    output_idx: int = 0
    roi_size: int = 0
    capture_hz: int = 120
    preview_hz: int = 20
    detection_max_width: int = 720
    hsv_low: list[int] = field(default_factory=lambda: [75, 90, 90])
    hsv_high: list[int] = field(default_factory=lambda: [115, 255, 255])
    min_area: float = 12.0
    max_area: float = 100000.0
    min_circularity: float = 0.55
    min_fill: float = 0.5
    exclude_top_fraction: float = 0.08
    exclude_bottom_fraction: float = 0.08
    horizontal_fov: float = 103.0
    counts_per_radian_x: float = 0.0
    counts_per_radian_y: float = 0.0
    calibrated_size: list[int] = field(default_factory=lambda: [0, 0])
    calibration_probe_counts: int = 40
    calibration_settle_ms: float = 180.0
    learning_hits: int = 8
    learning_gain: float = 0.45
    learning_max_step_counts: int = 30
    learning_fast_gain: float = 0.95
    learning_fast_max_step_counts: int = 180
    learning_settle_ms: float = 90.0
    learning_stall_timeout_ms: float = 3000.0
    mode: str = "direct"
    gain: float = 1.0
    max_step_counts: int = 1400
    max_speed: float = 2400.0
    max_acceleration: float = 18000.0
    move_settle_ms: float = 8.0
    max_frame_age_ms: float = 80.0
    stale_pause_ms: float = 500.0
    aim_radius_fraction: float = 0.65
    stable_frames: int = 1
    click_hold_ms: float = 2.0
    shot_cooldown_ms: float = 35.0
    result_timeout_ms: float = 180.0
    ghost_ms: float = 50.0
    lock_distance_px: float = 100.0
    lock_timeout_ms: float = 1800.0
    max_shots_per_target: int = 2

    def validate(self):
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and not math.isfinite(value):
                raise ValueError(f"{f.name} must be finite")
        if not self.window_title.strip() or not self.process_names or any(not isinstance(x, str) or not x.endswith('.exe') for x in self.process_names):
            raise ValueError("A game window title and executable names are required")
        for name in ("device_idx", "output_idx", "roi_size", "capture_hz", "preview_hz", "detection_max_width", "calibration_probe_counts", "learning_hits", "learning_max_step_counts", "learning_fast_max_step_counts", "max_step_counts", "stable_frames", "max_shots_per_target"):
            if type(getattr(self, name)) is not int:
                raise ValueError(f"{name} must be an integer")
        if (self.device_idx < 0 or self.output_idx < 0 or
                (self.roi_size != 0 and self.roi_size < 64) or
                (self.detection_max_width != 0 and self.detection_max_width < 320)):
            raise ValueError("Invalid capture device / ROI")
        if not 1 <= self.capture_hz <= 500 or not 1 <= self.preview_hz <= 60:
            raise ValueError("Capture Hz must be 1..500, preview Hz 1..60")
        if len(self.hsv_low) != 3 or len(self.hsv_high) != 3:
            raise ValueError("HSV thresholds must have three integers")
        for i, cap in enumerate((179, 255, 255)):
            if not (type(self.hsv_low[i]) is int and type(self.hsv_high[i]) is int and 0 <= self.hsv_low[i] <= self.hsv_high[i] <= cap):
                raise ValueError("Invalid HSV bounds (H: 0..179; S,V: 0..255)")
        if not 0 < self.min_area < self.max_area or not 10 < self.horizontal_fov < 170:
            raise ValueError("Invalid target area / horizontal FOV")
        for name in ("min_circularity", "min_fill", "learning_gain", "learning_fast_gain", "gain", "aim_radius_fraction"):
            if not 0 < getattr(self, name) <= 1:
                raise ValueError(f"{name} must be in (0,1]")
        if not (0 <= self.exclude_top_fraction < .4 and 0 <= self.exclude_bottom_fraction < .4):
            raise ValueError("Invalid HUD exclusion fractions")
        if self.mode not in ("direct", "baseline", "smooth"):
            raise ValueError("mode must be direct, baseline or smooth")
        if self.counts_per_radian_x < 0 or self.counts_per_radian_y < 0:
            raise ValueError("Calibration counts must be non-negative")
        if len(self.calibrated_size) != 2 or any(type(v) is not int or v < 0 for v in self.calibrated_size):
            raise ValueError("Invalid calibrated_size")
        for name in ("max_speed", "max_acceleration", "max_step_counts", "learning_hits", "learning_max_step_counts", "learning_fast_max_step_counts", "learning_settle_ms", "learning_stall_timeout_ms", "stable_frames", "max_shots_per_target", "lock_distance_px", "lock_timeout_ms", "move_settle_ms", "max_frame_age_ms", "stale_pause_ms", "click_hold_ms", "shot_cooldown_ms", "result_timeout_ms", "ghost_ms", "calibration_probe_counts", "calibration_settle_ms"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.shot_cooldown_ms < self.click_hold_ms or self.result_timeout_ms < self.shot_cooldown_ms:
            raise ValueError("Expected click_hold <= cooldown <= result_timeout")
        if self.stale_pause_ms < self.max_frame_age_ms:
            raise ValueError("stale_pause must be >= max_frame_age")
        if (self.calibration_probe_counts > 200 or self.learning_max_step_counts > 100 or
                self.learning_fast_max_step_counts > 400 or self.max_step_counts > 2000 or
                self.learning_fast_max_step_counts < self.learning_max_step_counts or
                self.learning_fast_gain < self.learning_gain):
            raise ValueError("Mouse steps exceed supported limits")
        return self

    @property
    def calibrated(self):
        return self.counts_per_radian_x > 0 and self.counts_per_radian_y > 0 and min(self.calibrated_size) > 0

    @classmethod
    def load(cls, path):
        path = local_path(path)
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        unknown = set(data) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown settings: {sorted(unknown)}")
        return cls(**data).validate()

    def save(self, path):
        self.validate()
        path = local_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(path)
