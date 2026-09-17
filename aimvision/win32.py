"""Documented Win32 window metadata and ordinary SendInput. No process injection."""
import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
from pathlib import PureWindowsPath
import sys
import time


if sys.platform != "win32":
    raise RuntimeError("Live capture and input require Windows")

user32 = C.WinDLL("user32", use_last_error=True)
kernel32 = C.WinDLL("kernel32", use_last_error=True)


def bind(dll, name, result, args):
    function = getattr(dll, name)
    function.restype = result
    function.argtypes = args
    return function


EnumProc = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
bind(user32, "EnumWindows", W.BOOL, [EnumProc, W.LPARAM])
bind(user32, "IsWindowVisible", W.BOOL, [W.HWND])
bind(user32, "IsIconic", W.BOOL, [W.HWND])
bind(user32, "GetWindowTextLengthW", C.c_int, [W.HWND])
bind(user32, "GetWindowTextW", C.c_int, [W.HWND, W.LPWSTR, C.c_int])
bind(user32, "GetClientRect", W.BOOL, [W.HWND, C.POINTER(W.RECT)])
bind(user32, "ClientToScreen", W.BOOL, [W.HWND, C.POINTER(W.POINT)])
bind(user32, "GetForegroundWindow", W.HWND, [])
bind(user32, "GetWindowThreadProcessId", W.DWORD, [W.HWND, C.POINTER(W.DWORD)])
bind(user32, "GetAsyncKeyState", C.c_short, [C.c_int])
bind(kernel32, "OpenProcess", W.HANDLE, [W.DWORD, W.BOOL, W.DWORD])
bind(kernel32, "CloseHandle", W.BOOL, [W.HANDLE])
bind(kernel32, "QueryFullProcessImageNameW", W.BOOL, [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)])


def dpi_aware():
    try:
        fn = bind(user32, "SetProcessDpiAwarenessContext", W.BOOL, [C.c_void_p])
        fn(C.c_void_p(-4))  # Per-monitor v2; already set in packaged manifest is OK.
    except AttributeError:
        user32.SetProcessDPIAware()


def executable(hwnd):
    pid = W.DWORD()
    user32.GetWindowThreadProcessId(hwnd, C.byref(pid))
    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION only.
    if not handle:
        return ""
    try:
        length = W.DWORD(32768)
        buffer = C.create_unicode_buffer(length.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, C.byref(length)):
            return ""
        return PureWindowsPath(buffer.value).name.lower()
    finally:
        kernel32.CloseHandle(handle)


@dataclass(frozen=True)
class Window:
    hwnd: int
    title: str
    process: str

    def rect(self):
        if user32.IsIconic(self.hwnd) or not user32.IsWindowVisible(self.hwnd):
            raise RuntimeError("Game window is minimized or unavailable")
        rect, origin = W.RECT(), W.POINT(0, 0)
        if not user32.GetClientRect(self.hwnd, C.byref(rect)) or not user32.ClientToScreen(self.hwnd, C.byref(origin)):
            raise C.WinError(C.get_last_error())
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width < 64 or height < 64:
            raise RuntimeError("Game client is too small")
        return origin.x, origin.y, origin.x + width, origin.y + height

    def foreground(self):
        return user32.GetForegroundWindow() == self.hwnd and not user32.IsIconic(self.hwnd)


def find_windows(cfg):
    found = []
    allowed = {name.lower() for name in cfg.process_names}

    @EnumProc
    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        buffer = C.create_unicode_buffer(user32.GetWindowTextLengthW(hwnd) + 1)
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        if cfg.window_title.lower() in buffer.value.lower():
            process = executable(hwnd)
            if process in allowed:
                found.append(Window(hwnd, buffer.value, process))
        return True

    user32.EnumWindows(visit, 0)
    return found


class MOUSEINPUT(C.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD), ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class KEYBDINPUT(C.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class HARDWAREINPUT(C.Structure):
    _fields_ = [("uMsg", W.DWORD), ("wParamL", W.WORD), ("wParamH", W.WORD)]


class INPUTUNION(C.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(C.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("type", W.DWORD), ("value", INPUTUNION)]


bind(user32, "SendInput", W.UINT, [W.UINT, C.POINTER(INPUT), C.c_int])


class Keys:
    def __init__(self):
        self.previous = {}

    def pressed(self, key):
        down = bool(user32.GetAsyncKeyState(key) & 0x8000)
        old = self.previous.get(key, False)
        self.previous[key] = down
        return down and not old


class Mouse:
    def __init__(self, guard):
        self.guard = guard
        self.held = False
        self.release_at = 0.0

    def _send(self, flags, dx=0, dy=0):
        event = INPUT(type=0)
        event.mi = MOUSEINPUT(dx, dy, 0, flags, 0, 0)
        C.set_last_error(0)
        sent = user32.SendInput(1, C.byref(event), C.sizeof(INPUT))
        if sent != 1:
            raise RuntimeError(f"SendInput inserted {sent}/1 events; Windows error {C.get_last_error()}. Check foreground and integrity levels.")

    def move(self, dx, dy):
        if not self.guard():
            raise RuntimeError("Input guard rejected movement: game not ready/foreground")
        if dx or dy:
            self._send(0x0001, int(dx), int(dy))

    def click(self, hold_ms):
        if not self.guard():
            raise RuntimeError("Input guard rejected click: game not ready/foreground")
        if self.held:
            raise RuntimeError("Previous click has not been released")
        if user32.GetAsyncKeyState(0x01) & 0x8000:
            raise RuntimeError("Physical left button is already held")
        self._send(0x0002)
        self.held = True
        self.release_at = time.perf_counter() + hold_ms / 1000
        # The vision loop can take tens of milliseconds. Releasing from its next
        # tick would turn a requested 2 ms click into a 40-60 ms hold.
        remaining = self.release_at - time.perf_counter()
        if remaining > 0:
            time.sleep(remaining)
        self.release_all()

    def tick(self):
        if self.held and time.perf_counter() >= self.release_at:
            self.release_all()

    def release_all(self):
        if self.held:
            self._send(0x0004)
            self.held = False
