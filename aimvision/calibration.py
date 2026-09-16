"""Two-axis empirical calibration with observation and explicit user-triggered probes."""
import math
from statistics import median
from .motion import pixel_angles


def select_target(targets, center, max_distance):
    """Pick the nearest intact target; multiple visible targets are expected."""
    candidates = [target for target in targets if target.quality >= .8 and target.distance(center) <= max_distance]
    # Prefer a clean contour and the upper half, where the weapon model is
    # least likely to cover the circle after a probe.
    return min(candidates, key=lambda target: (target.quality < .95,
                                               target.y > center[1],
                                               target.distance(center)), default=None)


def match_target(before, targets, max_distance, min_quality=.8):
    """Associate the same target after a small calibration probe."""
    candidates = [target for target in targets if target.quality >= min_quality]
    candidate = min(candidates, key=lambda target: target.distance((before.x, before.y)), default=None)
    if candidate is None or candidate.distance((before.x, before.y)) > max_distance:
        return None
    return candidate


def estimate_scale(before, after, center, width, hfov, counts, axis):
    a = pixel_angles((before.x, before.y), center, width, hfov)[axis]
    b = pixel_angles((after.x, after.y), center, width, hfov)[axis]
    delta = a - b
    if abs(delta) < 0.001:
        raise ValueError("Too little movement measured; input may not be accepted")
    scale = counts / delta
    if not math.isfinite(scale) or not 10 <= scale <= 1_000_000:
        raise ValueError("Unexpected direction / scale; use one stationary target")
    return scale


def combine_samples(samples):
    if len(samples) < 3:
        raise ValueError("Three valid samples are required")
    middle = median(samples)
    if max(abs(v - middle) / middle for v in samples) > .2:
        raise ValueError("Calibration varies more than 20%; keep target and mouse stationary")
    return middle
