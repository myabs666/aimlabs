from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch
import numpy as np
from aimvision.capture import Capture
from aimvision.config import Config


class CaptureGeometryTests(unittest.TestCase):
    def make_capture(self, client, roi=0):
        self.camera = SimpleNamespace(
            _output=SimpleNamespace(desc=SimpleNamespace(DesktopCoordinates=SimpleNamespace(left=-1920, top=0, right=0, bottom=1080))),
            _duplicator=SimpleNamespace(latest_frame_time=time.perf_counter() - .01),
            release=lambda: None,
        )

        def grab(region):
            self.region = region
            return np.zeros((region[3] - region[1], region[2] - region[0], 3), np.uint8)

        self.camera.grab = grab
        with patch('aimvision.capture.load_dxcam', return_value=SimpleNamespace(create=lambda **_: self.camera)):
            return Capture(Config(roi_size=roi), SimpleNamespace(rect=lambda: client))

    def test_negative_monitor_origin_and_full_client(self):
        capture = self.make_capture((-1820, 100, -220, 1000))
        frame = capture.grab()
        self.assertEqual(self.region, (100, 100, 1700, 1000))
        self.assertEqual(frame.center, (800, 450))
        self.assertEqual(frame.client_size, (1600, 900))
        self.assertEqual(frame.image.shape, (900, 1600, 3))

    def test_center_crop_and_timestamp_deduplication(self):
        capture = self.make_capture((-1820, 100, -220, 1000), roi=800)
        frame = capture.grab()
        self.assertEqual(self.region, (500, 150, 1300, 950))
        self.assertEqual(frame.center, (400, 400))
        self.assertEqual(frame.timestamp, self.camera._duplicator.latest_frame_time)
        self.assertIsNone(capture.grab())

    def test_window_crossing_outputs_is_rejected(self):
        capture = self.make_capture((-500, 0, 500, 900))
        with self.assertRaises(RuntimeError):
            capture.grab()
