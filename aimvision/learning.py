"""Low-speed closed-loop calibration using live target shots."""

import math
from statistics import median

from .calibration import estimate_scale, match_target
from .model import Action
from .motion import pixel_angles, project_angles


class LearningController:
    """Learn axes separately, then accelerate with measured two-axis moves."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.samples = [[], []]
        self.events = []
        self.shots = 0
        self.disappearances = 0
        self.active = False
        self.completed = False
        self.reset()

    def reset(self):
        self.state = "PAUSED"
        self.selected = None
        self.pending = None
        self.last_sequence = -1
        self.wait_until = 0.0
        self.last_shot = -float("inf")
        self.stable = 0
        self.missing = 0
        self.attempts = 0
        self.last_progress = 0.0
        self.move_phase = "1D"
        self.current_gain = self.cfg.learning_gain
        self.current_cap = self.cfg.learning_max_step_counts

    def arm(self):
        if not self.cfg.calibrated:
            raise ValueError("Complete base X/Y calibration before low-speed learning")
        self.reset()
        self.active = True
        self.completed = False
        self.state = "SEEK"

    def pause(self, reason="paused"):
        self.active = False
        self.pending = None
        self.state = "PAUSED: " + reason

    def pop_events(self):
        events, self.events = self.events, []
        return events

    def _drop_lock(self):
        self.selected = None
        self.pending = None
        self.stable = self.missing = self.attempts = 0
        self.last_progress = 0.0
        self.state = "SEEK"

    def _observe_axis(self, before, after, frame, axis, counts):
        if counts == 0:
            return
        current = self.cfg.counts_per_radian_x if axis == 0 else self.cfg.counts_per_radian_y
        fields = {"axis": axis, "counts": counts, "current": current}
        try:
            value = estimate_scale(before, after, frame.center, frame.client_size[0],
                                   self.cfg.horizontal_fov, counts, axis)
        except ValueError as exc:
            fields["reason"] = str(exc)
            self.events.append(("sample_rejected", fields))
            return
        fields["value"] = value
        if not current * .65 <= value <= current * 1.5:
            self.events.append(("sample_rejected", fields))
            return
        self.samples[axis].append(value)
        applied = current
        if len(self.samples[axis]) >= 3:
            applied = median(self.samples[axis][-15:])
            if axis == 0:
                self.cfg.counts_per_radian_x = applied
            else:
                self.cfg.counts_per_radian_y = applied
        self.events.append(("sample", {"axis": axis, "value": value,
                                       "applied": applied, "count": len(self.samples[axis])}))

    def _observe_move(self, after, frame, now):
        before, dx, dy, _, _ = self.pending
        self.pending = None
        self._observe_axis(before, after, frame, 0, dx)
        self._observe_axis(before, after, frame, 1, dy)
        self.last_progress = now

    def _match_after_move(self, intact, frame):
        before, dx, dy, scale_x, scale_y = self.pending
        yaw, pitch = pixel_angles((before.x, before.y), frame.center,
                                  frame.client_size[0], self.cfg.horizontal_fov)
        expected = project_angles((yaw - dx / scale_x, pitch - dy / scale_y),
                                  frame.center, frame.client_size[0], self.cfg.horizontal_fov)
        candidate = min(intact, key=lambda target: target.distance(expected), default=None)
        limit = max(self.cfg.lock_distance_px * 1.5, before.radius * 2.5)
        return candidate if candidate is not None and candidate.distance(expected) <= limit else None

    def finalize(self):
        for axis in (0, 1):
            if len(self.samples[axis]) >= 3:
                value = median(self.samples[axis][-15:])
                if axis == 0:
                    self.cfg.counts_per_radian_x = value
                else:
                    self.cfg.counts_per_radian_y = value
        return tuple(len(values) for values in self.samples)

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
        if frame.timestamp < self.wait_until:
            return Action("none", reason="waiting for post-action frame")

        intact = [target for target in targets if target.quality >= .8]
        matched_after_move = None
        if self.pending is not None:
            matched_after_move = self._match_after_move(intact, frame)
            if matched_after_move is None:
                self.events.append(("sample_rejected", {"reason": "target lost after movement"}))
                self._drop_lock()
                return Action("none")
            self._observe_move(matched_after_move, frame, now)
            self.selected = matched_after_move

        if self.state == "WAIT_RESULT":
            nearby = [target for target in intact
                      if target.distance((self.selected.x, self.selected.y)) < max(6, self.selected.radius * .65)]
            self.missing = self.missing + 1 if not nearby else 0
            if self.missing >= 2:
                self.disappearances += 1
                self.events.append(("target_cleared", {"hits": self.disappearances}))
                if self.disappearances >= cfg.learning_hits and all(len(values) >= 3 for values in self.samples):
                    self.active = False
                    self.completed = True
                    self.state = "DONE"
                    return Action("done")
                if self.disappearances >= cfg.learning_hits * 2:
                    self.pause("insufficient X/Y learning samples; use targets spread across both axes")
                    return Action("pause", reason=self.state)
                self._drop_lock()
            elif (now - self.last_shot) * 1000 >= cfg.result_timeout_ms:
                if self.attempts >= cfg.max_shots_per_target:
                    self.pause("target did not disappear after retries")
                    return Action("pause", reason=self.state)
                self.state = "AIM"
                self.stable = 0
                self.last_progress = now
            else:
                return Action("none")

        if self.selected is None:
            if not intact:
                return Action("none")
            self.selected = min(intact, key=lambda target: target.distance(frame.center))
            self.last_progress = now
            self.state = "AIM"
        elif matched_after_move is None:
            match = match_target(self.selected, intact, max(cfg.lock_distance_px, self.selected.radius * 2))
            if match is None:
                self.missing += 1
                if self.missing >= 2:
                    self._drop_lock()
                return Action("none")
            self.missing = 0
            self.selected = match

        if self.last_progress and (now - self.last_progress) * 1000 > cfg.learning_stall_timeout_ms:
            self.pause("no aiming progress; check target detection")
            return Action("pause", reason=self.state)

        tolerance = max(1.0, self.selected.radius * cfg.aim_radius_fraction)
        if self.selected.distance(frame.center) <= tolerance:
            self.stable += 1
            if self.stable >= max(3, cfg.stable_frames) and (now - self.last_shot) * 1000 >= cfg.shot_cooldown_ms:
                self.state = "WAIT_RESULT"
                self.last_shot = now
                self.wait_until = now + max(cfg.click_hold_ms, cfg.shot_cooldown_ms) / 1000
                self.attempts += 1
                self.shots += 1
                self.stable = 0
                self.last_progress = now
                return Action("click")
            return Action("none")

        self.stable = 0
        angles = pixel_angles((self.selected.x, self.selected.y), frame.center,
                              frame.client_size[0], cfg.horizontal_fov)
        desired = [angles[0] * cfg.counts_per_radian_x,
                   angles[1] * cfg.counts_per_radian_y]
        if all(len(values) >= 3 for values in self.samples):
            confidence = min(1.0, min(len(values) for values in self.samples) / 6)
            gain = cfg.learning_gain + (cfg.learning_fast_gain - cfg.learning_gain) * confidence
            cap = round(cfg.learning_max_step_counts +
                        (cfg.learning_fast_max_step_counts - cfg.learning_max_step_counts) * confidence)
            raw = [value * gain for value in desired]
            counts = [math.trunc(max(-cap, min(cap, value))) for value in raw]
            for axis in (0, 1):
                if counts[axis] == 0 and raw[axis]:
                    counts[axis] = 1 if raw[axis] > 0 else -1
            self.move_phase = "2D"
        else:
            needed = [axis for axis in (0, 1) if len(self.samples[axis]) < 3]
            axis = max(needed, key=lambda value: abs(desired[value]))
            raw = desired[axis] * cfg.learning_gain
            count = math.trunc(max(-cfg.learning_max_step_counts,
                                   min(cfg.learning_max_step_counts, raw)))
            if count == 0:
                count = 1 if raw > 0 else -1
            counts = [count if axis == 0 else 0, count if axis == 1 else 0]
            gain, cap = cfg.learning_gain, cfg.learning_max_step_counts
            self.move_phase = "1D"
        self.current_gain, self.current_cap = gain, cap
        self.pending = (self.selected, counts[0], counts[1],
                        cfg.counts_per_radian_x, cfg.counts_per_radian_y)
        self.wait_until = now + cfg.learning_settle_ms / 1000
        return Action("move", counts[0], counts[1])
