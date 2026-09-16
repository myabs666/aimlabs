from .model import Action
from .motion import Motion, pixel_angles, project_angles


class Controller:
    """Pure decision logic: no OS calls, clock calls or sleeps."""
    def __init__(self, cfg):
        self.cfg = cfg
        self.motion = Motion(cfg)
        self.shots = 0
        self.disappearances = 0  # Observations, not verified hits.
        self.active = False
        self.reset()

    def reset(self):
        self.state = "PAUSED"
        self.selected = None
        self.predicted = None
        self.lock_started = 0.0
        self.last_sequence = -1
        self.wait_until = 0.0
        self.last_shot = -float("inf")
        self.stable = 0
        self.missing = 0
        self.attempts = 0
        self.ghost = None
        self.motion.reset()

    def arm(self):
        if not self.cfg.calibrated:
            raise ValueError("Calibrate X/Y before enabling mouse control")
        self.reset()
        self.active = True
        self.state = "SEEK"

    def pause(self, reason="paused"):
        self.active = False
        self.reset()
        self.state = "PAUSED: " + reason

    def _drop_lock(self):
        self.selected = None
        self.predicted = None
        self.stable = 0
        self.attempts = 0
        self.missing = 0
        self.motion.reset()
        self.state = "SEEK"

    def update(self, frame, targets, now):
        cfg = self.cfg
        if not self.active:
            return Action("none")
        if tuple(cfg.calibrated_size) != tuple(frame.client_size):
            self.pause("client size changed; recalibrate")
            return Action("pause", reason=self.state)
        if now < frame.timestamp or (now - frame.timestamp) * 1000 > cfg.max_frame_age_ms:
            return Action("none", reason="stale frame")
        if frame.sequence <= self.last_sequence:
            return Action("none", reason="duplicate frame")
        self.last_sequence = frame.sequence
        # Only an observation captured AFTER settling may drive the next action.
        if frame.timestamp < self.wait_until:
            return Action("none", reason="waiting for post-action frame")
        if self.state == "WAIT_RESULT":
            nearby = [t for t in targets if t.distance((self.selected.x, self.selected.y)) < max(6, self.selected.radius * .65)]
            self.missing = self.missing + 1 if not nearby else 0
            required_missing = 1 if cfg.mode == "direct" else 2
            if self.missing >= required_missing:
                self.disappearances += 1
                self.ghost = (self.selected.x, self.selected.y, max(8, self.selected.radius * 1.6), now + cfg.ghost_ms / 1000)
                self._drop_lock()
            elif (now - self.last_shot) * 1000 >= cfg.result_timeout_ms:
                if self.attempts >= cfg.max_shots_per_target:
                    self.pause("target did not disappear after retries")
                    return Action("pause", reason=self.state)
                self.state = "AIM"
                self.stable = 0
            else:
                return Action("none")
        if self.selected is None:
            eligible = targets
            if self.ghost is not None:
                gx, gy, radius, until = self.ghost
                if now < until:
                    eligible = [t for t in targets if t.distance((gx, gy)) > radius]
                else:
                    self.ghost = None
            if not eligible:
                return Action("none")
            self.selected = min(eligible, key=lambda t: t.distance(frame.center))
            self.predicted = (self.selected.x, self.selected.y)
            self.lock_started = now
            self.state = "AIM"
        else:
            match = min(targets, key=lambda t: t.distance(self.predicted), default=None)
            if match is None or match.distance(self.predicted) > max(cfg.lock_distance_px, self.selected.radius * 2):
                self.stable = 0
                self.missing += 1
                if self.missing >= 2:
                    self._drop_lock()
                return Action("none")
            self.missing = 0
            self.selected = match
            self.predicted = (match.x, match.y)
        if (now - self.lock_started) * 1000 > cfg.lock_timeout_ms:
            self.pause("aim timeout; check calibration")
            return Action("pause", reason=self.state)
        tolerance = max(1.0, self.selected.radius * cfg.aim_radius_fraction)
        if self.selected.distance(frame.center) <= tolerance:
            self.motion.reset()
            self.stable += 1
            if self.stable >= cfg.stable_frames and (now - self.last_shot) * 1000 >= cfg.shot_cooldown_ms:
                self.state = "WAIT_RESULT"
                self.last_shot = now
                self.wait_until = now + max(cfg.click_hold_ms, cfg.shot_cooldown_ms) / 1000
                self.attempts += 1
                self.shots += 1
                self.stable = 0
                return Action("click")
            return Action("none")
        self.stable = 0
        dx, dy = self.motion.step(self.selected, frame, now)
        if dx or dy:
            # Spherical prediction includes horizontal/vertical perspective
            # coupling. Fresh detection after every short move remains final.
            yaw, pitch = pixel_angles((self.selected.x, self.selected.y), frame.center,
                                      frame.client_size[0], cfg.horizontal_fov)
            self.predicted = project_angles(
                (yaw - dx / cfg.counts_per_radian_x,
                 pitch - dy / cfg.counts_per_radian_y),
                frame.center, frame.client_size[0], cfg.horizontal_fov)
            self.wait_until = now + cfg.move_settle_ms / 1000
            return Action("move", dx, dy)
        return Action("none")
