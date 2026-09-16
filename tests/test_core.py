import math
from pathlib import Path
import uuid
import unittest
import cv2
import numpy as np
from aimvision.config import Config, ROOT, local_path
from aimvision.calibration import estimate_scale, combine_samples, match_target, select_target
from aimvision.controller import Controller
from aimvision.detector import Detector
from aimvision.learning import LearningController
from aimvision.model import Frame, Target
from aimvision.motion import pixel_angles, project_angles
from aimvision.simulation import scenario


def settings(**kwargs):
    return Config(counts_per_radian_x=2600, counts_per_radian_y=2600, calibrated_size=[800, 600], **kwargs)


def frame(sequence=1, timestamp=1.0, size=(800, 600)):
    return Frame(np.zeros((600, 800, 3), np.uint8), timestamp, sequence, (400, 300), size)


class DetectionTests(unittest.TestCase):
    def test_scaled_detection_maps_centers_back_to_full_resolution(self):
        image = np.zeros((1800, 2880, 3), np.uint8)
        for point in ((500, 500), (1440, 900), (2400, 1200)):
            cv2.circle(image, point, 100, (255, 220, 0), -1)
        full = Frame(image, 1.0, 1, (1440, 900), (2880, 1800))
        targets, mask = Detector(Config(detection_max_width=720)).detect(full)
        self.assertEqual(mask.shape[1], 720)
        self.assertEqual(len(targets), 3)
        found = sorted((round(target.x), round(target.y)) for target in targets)
        expected = [(500, 500), (1440, 900), (2400, 1200)]
        self.assertTrue(all(math.hypot(x - ex, y - ey) <= 3 for (x, y), (ex, ey) in zip(found, expected)))

    def test_circles_reject_noise_rectangle_hud_and_cropped_target(self):
        f = frame()
        color = (255, 220, 0)
        cv2.circle(f.image, (200, 200), 12, color, -1)
        cv2.circle(f.image, (600, 300), 4, color, -1)
        cv2.circle(f.image, (400, 15), 8, color, -1)
        cv2.circle(f.image, (0, 300), 16, color, -1)
        cv2.rectangle(f.image, (400, 400), (480, 410), color, -1)
        f.image[250, 250] = color
        targets, _ = Detector(Config()).detect(f)
        self.assertEqual(len(targets), 2)
        self.assertEqual({(round(t.x), round(t.y)) for t in targets}, {(200, 200), (600, 300)})

    def test_crosshair_hole_preserves_center(self):
        f = frame()
        cv2.circle(f.image, (400, 300), 10, (255, 220, 0), -1)
        cv2.circle(f.image, (400, 300), 2, (255, 255, 255), -1)
        targets, _ = Detector(Config()).detect(f)
        self.assertEqual(len(targets), 1)
        self.assertLess(targets[0].distance(f.center), .5)

    def test_touching_targets_are_split(self):
        f = frame()
        color = (255, 220, 0)
        cv2.circle(f.image, (250, 300), 50, color, -1)
        cv2.circle(f.image, (348, 300), 50, color, -1)
        targets, _ = Detector(Config()).detect(f)
        self.assertEqual(len(targets), 2)
        self.assertEqual([round(target.x) for target in targets], [348, 250])
        self.assertTrue(all(target.quality >= .8 for target in targets))

    def test_partially_occluded_target_is_low_quality(self):
        f = frame()
        cv2.circle(f.image, (300, 300), 50, (255, 220, 0), -1)
        cv2.rectangle(f.image, (300, 250), (360, 350), (0, 0, 0), -1)
        targets, _ = Detector(Config()).detect(f)
        self.assertEqual(len(targets), 1)
        self.assertLess(targets[0].quality, .8)


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.c = Controller(settings(mode="baseline", stable_frames=2))
        self.c.arm()
        self.center = Target(400, 300, 12, 400)

    def test_stale_duplicate_and_pre_settle_frames_cannot_fire(self):
        self.assertEqual(self.c.update(frame(), [self.center], 2).kind, "none")
        self.assertEqual(self.c.update(frame(), [self.center], 1).kind, "none")
        self.assertEqual(self.c.update(frame(), [self.center], 1).kind, "none")
        self.assertEqual(self.c.update(frame(2, 1.02), [self.center], 1.02).kind, "click")
        self.assertEqual(self.c.update(frame(3, 1.03), [self.center], 1.03).kind, "none")

    def test_size_change_pauses(self):
        action = self.c.update(frame(size=(1024, 768)), [self.center], 1)
        self.assertEqual(action.kind, "pause")
        self.assertFalse(self.c.active)

    def test_paused_never_moves(self):
        self.c.pause("test")
        self.assertEqual(self.c.update(frame(), [Target(500, 300, 10, 100)], 1).kind, "none")

    def test_no_infinite_retry_when_click_has_no_effect(self):
        kinds = []
        for i in range(150):
            now = 1 + i / 120
            kinds.append(self.c.update(frame(i, now), [self.center], now).kind)
        self.assertEqual(kinds.count("click"), 2)
        self.assertIn("pause", kinds)
        self.assertFalse(self.c.active)

    def test_disappearance_requires_two_observations(self):
        self.c.update(frame(), [self.center], 1)
        self.c.update(frame(2, 1.02), [self.center], 1.02)
        self.c.update(frame(3, 1.2), [], 1.2)
        self.assertEqual(self.c.disappearances, 0)
        self.c.update(frame(4, 1.22), [], 1.22)
        self.assertEqual(self.c.disappearances, 1)

    def test_lock_does_not_switch_to_new_nearest_target(self):
        a = Target(450, 300, 12, 300)
        self.c.update(frame(), [a], 1)
        expected = self.c.predicted
        tracked = Target(expected[0], expected[1], 12, 300)
        self.c.update(frame(2, 1.05), [self.center, tracked], 1.05)
        self.assertEqual(self.c.selected, tracked)

    def test_uncalibrated_cannot_arm(self):
        with self.assertRaises(ValueError):
            Controller(Config()).arm()

    def test_direct_mode_uses_single_stable_and_result_frame(self):
        controller = Controller(settings(mode="direct", stable_frames=1))
        controller.arm()
        self.assertEqual(controller.update(frame(), [self.center], 1).kind, "click")
        action = controller.update(frame(2, 1.04), [], 1.04)
        self.assertEqual(controller.disappearances, 1)
        self.assertEqual(action.kind, "none")


class CalibrationTests(unittest.TestCase):
    def test_perspective_round_trip(self):
        width, fov, scale, counts = 800, 103, 2600, 40
        focal = width / (2 * math.tan(math.radians(fov) / 2))
        a = .15
        before = Target(400 + focal * math.tan(a), 300, 12, 300)
        after = Target(400 + focal * math.tan(a - counts / scale), 300, 12, 300)
        self.assertAlmostEqual(estimate_scale(before, after, (400, 300), width, fov, counts, 0), scale)
        self.assertAlmostEqual(pixel_angles((before.x, 300), (400, 300), width, fov)[0], a)

    def test_vertical_perspective_round_trip(self):
        width, fov, scale, counts = 800, 103, 3100, -40
        yaw, pitch = .3, -.2
        x, y = project_angles((yaw, pitch), (400, 300), width, fov)
        _, moved_y = project_angles((yaw, pitch - counts / scale), (400, 300), width, fov)
        before = Target(x, y, 12, 300)
        after = Target(x, moved_y, 12, 300)
        self.assertAlmostEqual(estimate_scale(before, after, (400, 300), width, fov, counts, 1), scale)
        self.assertAlmostEqual(pixel_angles((before.x, before.y), (400, 300), width, fov)[1], pitch)
        self.assertAlmostEqual(project_angles(pixel_angles((before.x, before.y), (400, 300), width, fov),
                                              (400, 300), width, fov)[1], before.y)

    def test_failed_input_and_inconsistent_samples_rejected(self):
        target = Target(400, 300, 10, 100)
        with self.assertRaises(ValueError):
            estimate_scale(target, target, (400, 300), 800, 103, 40, 0)
        with self.assertRaises(ValueError):
            combine_samples([100, 101, 190])

    def test_selects_and_matches_one_intact_target_from_many(self):
        targets = [Target(430, 300, 10, 300, .4), Target(470, 300, 10, 300, 1.0),
                   Target(700, 300, 10, 300, 1.0)]
        selected = select_target(targets, (400, 300), 200)
        self.assertEqual(selected, targets[1])
        after = [Target(451, 300, 10, 300, .4), Target(491, 300, 10, 300, 1.0),
                 Target(721, 300, 10, 300, 1.0)]
        self.assertEqual(match_target(selected, after, 100), after[1])

    def test_calibration_can_reassociate_partial_occlusion(self):
        before = Target(500, 350, 40, 5000, 1.0)
        partial = Target(462, 351, 41, 3100, .45)
        self.assertIsNone(match_target(before, [partial], 100))
        self.assertEqual(match_target(before, [partial], 100, min_quality=.3), partial)

    def test_calibration_prefers_clean_upper_target(self):
        lower_near = Target(410, 330, 20, 1200, .9)
        upper_clean = Target(550, 220, 20, 1200, .99)
        self.assertEqual(select_target([lower_near, upper_clean], (400, 300), 300), upper_clean)


class ConfigTests(unittest.TestCase):
    def test_paths_cannot_escape_project(self):
        with self.assertRaises(ValueError):
            local_path(ROOT.parent / "escaped.json")

    def test_atomic_round_trip_stays_local(self):
        # mkdir default ACLs also work under restricted Windows execution tokens.
        folder = local_path(".runtime/tmp") / ("config-test-" + uuid.uuid4().hex)
        folder.mkdir()
        path = folder / "settings.json"
        try:
            settings().save(path)
            self.assertTrue(Config.load(path).calibrated)
            self.assertFalse(path.with_suffix(".json.tmp").exists())
        finally:
            path.unlink(missing_ok=True)
            path.with_suffix(".json.tmp").unlink(missing_ok=True)
            folder.rmdir()

    def test_invalid_config_rejected(self):
        for cfg in (Config(horizontal_fov=float('nan')), Config(hsv_low=[300, 0, 0]), Config(capture_hz=0), Config(stable_frames=0)):
            with self.assertRaises(ValueError):
                cfg.validate()


class EndToEndTests(unittest.TestCase):
    def test_rendered_scenes_converge_in_all_modes(self):
        for mode in ("direct", "baseline", "smooth"):
            result = scenario(mode, required_hits=6)
            self.assertEqual(result["hits"], 6)
            self.assertEqual(result["shots"], 6)
            if mode == "direct":
                self.assertEqual(result["moves"], result["hits"])

    def test_low_speed_learning_remeasures_each_axis(self):
        cfg = settings(learning_hits=4, learning_settle_ms=1, shot_cooldown_ms=20,
                       result_timeout_ms=100, stable_frames=1, aim_radius_fraction=.5)
        learner = LearningController(cfg)
        learner.arm()
        true_scale = (2400.0, 2800.0)
        positions = [(590, 410), (220, 180), (650, 180), (180, 430)]
        target = Target(*positions[0], 20, 1200)
        missing = 0
        now = 1.0
        saw_two_axis_move = False
        for sequence in range(1, 1000):
            now += .01
            visible = [] if missing else [target]
            action = learner.update(frame(sequence, now), visible, now)
            if action.kind == "move":
                saw_two_axis_move |= bool(action.dx and action.dy)
                ax, ay = pixel_angles((target.x, target.y), (400, 300), 800, cfg.horizontal_fov)
                moved = project_angles((ax - action.dx / true_scale[0], ay - action.dy / true_scale[1]),
                                       (400, 300), 800, cfg.horizontal_fov)
                target = Target(*moved, 20, 1200)
            elif action.kind == "click":
                missing = 3
            elif action.kind == "done":
                break
            if missing:
                missing -= 1
                if missing == 0:
                    index = min(learner.disappearances, len(positions) - 1)
                    target = Target(*positions[index], 20, 1200)
        self.assertTrue(learner.completed)
        self.assertTrue(saw_two_axis_move)
        learner.finalize()
        self.assertAlmostEqual(cfg.counts_per_radian_x, true_scale[0], delta=1)
        self.assertAlmostEqual(cfg.counts_per_radian_y, true_scale[1], delta=1)
