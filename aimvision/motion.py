import math


def pixel_angles(point, center, client_width, horizontal_fov):
    """Recover spherical yaw/pitch from a square-pixel pinhole projection."""
    focal = client_width / (2 * math.tan(math.radians(horizontal_fov) / 2))
    x, y = point[0] - center[0], point[1] - center[1]
    yaw = math.atan2(x, focal)
    pitch = math.atan2(y, math.hypot(focal, x))
    return yaw, pitch


def project_angles(angles, center, client_width, horizontal_fov):
    """Project spherical yaw/pitch back to screen coordinates."""
    focal = client_width / (2 * math.tan(math.radians(horizontal_fov) / 2))
    yaw, pitch = angles
    x = focal * math.tan(yaw)
    y = focal * math.tan(pitch) / math.cos(yaw)
    return center[0] + x, center[1] + y


class Motion:
    def __init__(self, cfg):
        self.cfg = cfg
        self.reset()

    def reset(self):
        self.velocity = [0.0, 0.0]
        self.remainder = [0.0, 0.0]
        self.last_time = None

    def step(self, target, frame, now, gain=None):
        cfg = self.cfg
        angles = pixel_angles((target.x, target.y), frame.center, frame.client_size[0], cfg.horizontal_fov)
        active_gain = cfg.gain if gain is None else gain
        desired = [angles[0] * cfg.counts_per_radian_x * active_gain,
                   angles[1] * cfg.counts_per_radian_y * active_gain]
        dt = max(.001, min(.05, now - self.last_time)) if self.last_time is not None else cfg.move_settle_ms / 1000
        self.last_time = now
        if cfg.mode == "smooth":
            length = math.hypot(*desired)
            max_dist = cfg.max_speed * dt
            if length > max_dist:
                desired = [v * max_dist / length for v in desired]
            wanted_velocity = [v / dt for v in desired]
            dv = [wanted_velocity[i] - self.velocity[i] for i in range(2)]
            change = math.hypot(*dv)
            scale = min(1.0, cfg.max_acceleration * dt / change) if change else 1.0
            self.velocity = [self.velocity[i] + dv[i] * scale for i in range(2)]
            desired = [self.velocity[i] * dt for i in range(2)]
        length = math.hypot(*desired)
        if length > cfg.max_step_counts:
            desired = [v * cfg.max_step_counts / length for v in desired]
        # Preserve sub-count movements instead of losing small Sixshot corrections.
        result = []
        for i in range(2):
            total = desired[i] + self.remainder[i]
            count = math.trunc(total)
            self.remainder[i] = total - count
            result.append(count)
        return tuple(result)
