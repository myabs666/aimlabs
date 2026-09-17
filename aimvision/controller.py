import itertools
import math

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
        self.pending_move = None
        self.moves_on_lock = 0
        self.fire_enabled_at = 0.0
        self.countdown_active = False
        self.view_angles = [0.0, 0.0]
        self.saved_route = []
        self.pending_shots = []
        self.end_guard_at = float("inf")
        self.unresponsive_moves = 0
        self.last_clicked = None
        self.motion.reset()

    def arm(self):
        if not self.cfg.calibrated:
            raise ValueError("Calibrate X/Y before enabling mouse control")
        self.reset()
        self.active = True
        self.state = "SEEK"

    def begin_countdown(self, now):
        """Allow aiming immediately, but suppress task shots until the countdown ends."""
        self.fire_enabled_at = now + self.cfg.start_countdown_ms / 1000
        self.countdown_active = True
        self.end_guard_at = self.fire_enabled_at + self.cfg.end_guard_after_ms / 1000
        self.wait_until = now + max(self.cfg.click_hold_ms, self.cfg.shot_cooldown_ms) / 1000
        self.state = "COUNTDOWN"

    def set_end_guard(self, timestamp):
        self.end_guard_at = timestamp

    def _global_angles(self, target, frame):
        yaw, pitch = pixel_angles((target.x, target.y), frame.center,
                                  frame.client_size[0], self.cfg.horizontal_fov)
        return self.view_angles[0] + yaw, self.view_angles[1] + pitch

    def _shoot(self, now, frame, reason=""):
        self.last_clicked = self.selected
        if self.cfg.mode == "direct":
            position = self._global_angles(self.selected, frame)
            # A delayed retry replaces the older pending observation at the same
            # direction instead of creating two verification records.
            self.pending_shots = [shot for shot in self.pending_shots
                                  if self._count_distance(shot[0], position) > self.cfg.lock_distance_px]
            self.pending_shots.append([position, self.selected.radius, now, 0])
            self.selected = None
            self.predicted = None
            self.pending_move = None
            self.moves_on_lock = 0
            self.state = "PIPELINE"
        else:
            self.state = "WAIT_RESULT"
        self.last_shot = now
        self.wait_until = now + max(self.cfg.click_hold_ms, self.cfg.shot_cooldown_ms) / 1000
        self.attempts += 1
        self.shots += 1
        self.stable = 0
        return Action("click", reason=reason)

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
        self.pending_move = None
        self.moves_on_lock = 0
        self.saved_route = []
        self.motion.reset()
        self.state = "SEEK"

    def _post_move_match(self, targets, now):
        """Wait until the captured scene actually reflects the injected move."""
        before, expected, sent_at = self.pending_move
        candidate = min(targets, key=lambda target: target.distance(expected), default=None)
        limit = max(24.0, min(self.cfg.lock_distance_px,
                              before.radius * self.cfg.post_move_match_radius_fraction))
        expected_dx, expected_dy = expected[0] - before.x, expected[1] - before.y
        expected_length_sq = expected_dx * expected_dx + expected_dy * expected_dy
        confirmed = candidate is not None and candidate.distance(expected) <= limit
        if confirmed and expected_length_sq >= 144:
            observed_dx, observed_dy = candidate.x - before.x, candidate.y - before.y
            progress = (observed_dx * expected_dx + observed_dy * expected_dy) / expected_length_sq
            confirmed = progress >= .30
        if confirmed:
            self.unresponsive_moves = 0
            self.pending_move = None
            self.selected = candidate
            self.predicted = (candidate.x, candidate.y)
            self.missing = 0
            self.state = "AIM"
            return True
        if (now - sent_at) * 1000 < self.cfg.post_move_timeout_ms:
            return False
        if now >= self.end_guard_at:
            self.unresponsive_moves += 1
            if self.unresponsive_moves >= self.cfg.end_guard_move_failures:
                self.pause("no visual response after repeated moves; task likely ended")
                return False
        self._drop_lock()
        return False

    def _count_distance(self, first, second):
        return math.hypot((first[0] - second[0]) * self.cfg.counts_per_radian_x,
                          (first[1] - second[1]) * self.cfg.counts_per_radian_y)

    def _project_global(self, position, frame):
        return project_angles((position[0] - self.view_angles[0],
                               position[1] - self.view_angles[1]),
                              frame.center, frame.client_size[0], self.cfg.horizontal_fov)

    def _plan_and_select(self, targets, frame):
        """Save the shortest route through up to three currently visible targets."""
        candidates = sorted(targets, key=lambda target: self._aim_cost(target, frame))[:self.cfg.planned_targets]
        positions = {id(target): self._global_angles(target, frame) for target in candidates}
        origin = tuple(self.view_angles)

        def route_cost(route):
            points = [origin] + [positions[id(target)] for target in route]
            return sum(self._count_distance(points[index], points[index + 1])
                       for index in range(len(points) - 1))

        route = min(itertools.permutations(candidates), key=route_cost)
        self.saved_route = [positions[id(target)] for target in route[1:]]
        return route[0]

    def _select_saved(self, targets, frame):
        if not self.saved_route:
            return None
        expected_global = self.saved_route.pop(0)
        expected_pixel = self._project_global(expected_global, frame)
        candidate = min(targets, key=lambda target: target.distance(expected_pixel), default=None)
        if candidate is None:
            self.saved_route = []
            return None
        limit = max(self.cfg.lock_distance_px * 1.5, candidate.radius * 1.5)
        if candidate.distance(expected_pixel) > limit:
            self.saved_route = []
            return None
        return candidate

    def _pending_match(self, shot, targets, frame):
        expected = self._project_global(shot[0], frame)
        width, height = frame.image.shape[1], frame.image.shape[0]
        if not (-shot[1] <= expected[0] <= width + shot[1] and
                -shot[1] <= expected[1] <= height + shot[1]):
            return None, False
        candidate = min(targets, key=lambda target: target.distance(expected), default=None)
        limit = max(24.0, min(self.cfg.lock_distance_px, shot[1] * 1.1))
        return candidate, candidate is not None and candidate.distance(expected) <= limit

    def _observe_pending_shots(self, targets, frame):
        remaining = []
        for shot in self.pending_shots:
            _, visible = self._pending_match(shot, targets, frame)
            expected = self._project_global(shot[0], frame)
            width, height = frame.image.shape[1], frame.image.shape[0]
            on_screen = (-shot[1] <= expected[0] <= width + shot[1] and
                         -shot[1] <= expected[1] <= height + shot[1])
            if not on_screen:
                remaining.append(shot)
                continue
            shot[3] = 0 if visible else shot[3] + 1
            if shot[3] >= 2:
                self.disappearances += 1
            else:
                remaining.append(shot)
        self.pending_shots = remaining

    def _pipeline_eligible(self, targets, frame, now):
        eligible = []
        for target in targets:
            position = self._global_angles(target, frame)
            blocked = any((now - shot[2]) * 1000 < self.cfg.repeat_fire_interval_ms and
                          self._count_distance(position, shot[0]) <= self.cfg.lock_distance_px
                          for shot in self.pending_shots)
            if not blocked:
                eligible.append(target)
        return eligible

    def _aim_cost(self, target, frame):
        """Mouse-count distance is the real travel cost; pixels are perspective warped."""
        yaw, pitch = pixel_angles((target.x, target.y), frame.center,
                                  frame.client_size[0], self.cfg.horizontal_fov)
        return ((yaw * self.cfg.counts_per_radian_x) ** 2 +
                (pitch * self.cfg.counts_per_radian_y) ** 2) ** .5

    def _select_next(self, targets, frame):
        return self._plan_and_select(targets, frame)

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
        if self.countdown_active and now >= self.fire_enabled_at:
            self.countdown_active = False
            if self.selected is not None:
                self.lock_started = now
        if cfg.mode == "direct" and self.pending_move is None:
            self._observe_pending_shots(targets, frame)
        if self.state == "PIPELINE":
            eligible = self._pipeline_eligible(targets, frame, now)
            if not eligible:
                return Action("none", reason="waiting for next pipeline target")
            self.selected = self._select_saved(eligible, frame)
            if self.selected is None:
                self.selected = self._plan_and_select(eligible, frame)
            self.predicted = (self.selected.x, self.selected.y)
            self.lock_started = now
            self.moves_on_lock = 0
            self.missing = 0
            self.state = "AIM"
        if self.state == "WAIT_RESULT":
            nearby = [t for t in targets if t.distance((self.selected.x, self.selected.y)) < max(6, self.selected.radius * .65)]
            self.missing = self.missing + 1 if not nearby else 0
            if self.missing >= 2:
                self.disappearances += 1
                self.ghost = (self.selected.x, self.selected.y, max(8, self.selected.radius * 1.6), now + cfg.ghost_ms / 1000)
                self._drop_lock()
            elif cfg.mode == "direct" and nearby:
                candidate = min(nearby, key=lambda t: t.distance(frame.center))
                self.selected = candidate
                self.predicted = (candidate.x, candidate.y)
                tolerance = max(1.0, candidate.radius * cfg.aim_radius_fraction)
                if candidate.distance(frame.center) > tolerance:
                    self.state = "AIM"
                    self.stable = 0
                elif (now - self.last_shot) * 1000 >= cfg.repeat_fire_interval_ms:
                    return self._shoot(now, frame, "retry until target disappears")
                else:
                    return Action("none")
            elif cfg.mode == "direct":
                # One missing observation is promising hit feedback. Wait for the
                # second frame instead of falling into the finite-retry branch.
                return Action("none")
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
            self.selected = self._select_next(eligible, frame)
            self.predicted = (self.selected.x, self.selected.y)
            self.lock_started = now
            self.moves_on_lock = 0
            self.state = "AIM"
        elif self.pending_move is not None:
            if not self._post_move_match(targets, now):
                if not self.active:
                    return Action("pause", reason=self.state)
                return Action("none", reason="waiting for observed movement")
        else:
            match = min(targets, key=lambda t: t.distance(self.predicted), default=None)
            limit = max(24.0, min(cfg.lock_distance_px,
                                  self.selected.radius * cfg.post_move_match_radius_fraction))
            if match is None or match.distance(self.predicted) > limit:
                self.stable = 0
                self.missing += 1
                if self.missing >= 2:
                    self._drop_lock()
                return Action("none")
            self.missing = 0
            self.selected = match
            self.predicted = (match.x, match.y)
        if not self.countdown_active and (now - self.lock_started) * 1000 > cfg.lock_timeout_ms:
            self.pause("aim timeout; check calibration")
            return Action("pause", reason=self.state)
        tolerance = max(1.0, self.selected.radius * cfg.aim_radius_fraction)
        if self.selected.distance(frame.center) <= tolerance:
            self.motion.reset()
            self.stable += 1
            if self.countdown_active or now < self.fire_enabled_at:
                self.state = "COUNTDOWN"
                return Action("none", reason="countdown: aiming only")
            if self.stable >= cfg.stable_frames and (now - self.last_shot) * 1000 >= cfg.shot_cooldown_ms:
                return self._shoot(now, frame)
            return Action("none")
        self.stable = 0
        gain = (cfg.direct_correction_gain
                if cfg.mode == "direct" and self.moves_on_lock > 0 else cfg.gain)
        dx, dy = self.motion.step(self.selected, frame, now, gain=gain)
        if dx or dy:
            # Spherical prediction includes horizontal/vertical perspective
            # coupling. Fresh detection after every short move remains final.
            yaw, pitch = pixel_angles((self.selected.x, self.selected.y), frame.center,
                                      frame.client_size[0], cfg.horizontal_fov)
            self.predicted = project_angles(
                (yaw - dx / cfg.counts_per_radian_x,
                 pitch - dy / cfg.counts_per_radian_y),
                frame.center, frame.client_size[0], cfg.horizontal_fov)
            self.pending_move = (self.selected, self.predicted, now)
            self.moves_on_lock += 1
            self.view_angles[0] += dx / cfg.counts_per_radian_x
            self.view_angles[1] += dy / cfg.counts_per_radian_y
            self.state = "WAIT_MOVE"
            self.wait_until = now + cfg.move_settle_ms / 1000
            return Action("move", dx, dy)
        return Action("none")
