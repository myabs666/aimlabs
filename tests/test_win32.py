import ctypes
import sys
import unittest
from unittest.mock import patch


@unittest.skipUnless(sys.platform == "win32", "Windows ABI only")
class WindowsInputTests(unittest.TestCase):
    def test_input_abi(self):
        from aimvision.win32 import INPUT
        self.assertEqual(ctypes.sizeof(INPUT), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

    def test_guard_rejects_before_any_os_input(self):
        from aimvision.win32 import Mouse
        mouse = Mouse(lambda: False)
        with patch.object(mouse, '_send') as send:
            with self.assertRaises(RuntimeError):
                mouse.move(1, 1)
            with self.assertRaises(RuntimeError):
                mouse.click(20)
            send.assert_not_called()

    def test_failed_down_is_not_recorded_as_held(self):
        from aimvision.win32 import Mouse, user32
        mouse = Mouse(lambda: True)
        with patch.object(user32, 'GetAsyncKeyState', return_value=0), patch.object(mouse, '_send', side_effect=RuntimeError('blocked')):
            with self.assertRaises(RuntimeError):
                mouse.click(20)
        self.assertFalse(mouse.held)

    def test_release_still_occurs_after_focus_loss(self):
        from aimvision.win32 import Mouse
        mouse = Mouse(lambda: False)
        mouse.held = True
        with patch.object(mouse, '_send') as send:
            mouse.release_all()
            send.assert_called_once_with(0x0004)
        self.assertFalse(mouse.held)

    def test_click_releases_in_the_call_instead_of_waiting_for_vision_loop(self):
        from aimvision.win32 import Mouse, user32
        mouse = Mouse(lambda: True)
        with patch.object(user32, 'GetAsyncKeyState', return_value=0), \
                patch.object(mouse, '_send') as send, patch('aimvision.win32.time.sleep'):
            mouse.click(2)
        self.assertEqual([call.args[0] for call in send.call_args_list], [0x0002, 0x0004])
        self.assertFalse(mouse.held)

    def test_move_click_queues_movement_before_button_events(self):
        from aimvision.win32 import Mouse, user32
        mouse = Mouse(lambda: True)
        with patch.object(user32, 'GetAsyncKeyState', return_value=0), \
                patch.object(mouse, '_send') as send, patch('aimvision.win32.time.sleep'):
            mouse.move_click(123, -45, 2, 5)
        self.assertEqual([call.args for call in send.call_args_list],
                         [(0x0001, 123, -45), (0x0002,), (0x0004,)])
