import time
from .model import Frame


def load_dxcam():
    # Keep COM-generated modules out of the global interpreter/AppData as well.
    import sys
    import types
    import comtypes
    from .config import local_path
    cache = local_path(".runtime/cache/comtypes")
    cache.mkdir(parents=True, exist_ok=True)
    if "comtypes.gen" not in sys.modules:
        gen = types.ModuleType("comtypes.gen")
        gen.__path__ = [str(cache)]
        sys.modules["comtypes.gen"] = gen
        comtypes.gen = gen
    else:
        sys.modules["comtypes.gen"].__path__ = [str(cache)]
    import dxcam
    return dxcam


class Capture:
    def __init__(self, cfg, window):
        dxcam = load_dxcam()
        self.cfg = cfg
        self.window = window
        self.camera = dxcam.create(device_idx=cfg.device_idx, output_idx=cfg.output_idx, output_color="BGR")
        self.sequence = 0
        self.last_timestamp = 0.0
        self.last_rect = None
        # DXcam's output descriptor gives the exact desktop origin, including negatives.
        output = getattr(self.camera, "_output", None)
        descriptor = getattr(output, "desc", None)
        if descriptor is None:
            self.camera.release()
            raise RuntimeError("Unsupported DXcam descriptor API; run doctor and use pinned dependencies")
        rect = descriptor.DesktopCoordinates
        self.bounds = (rect.left, rect.top, rect.right, rect.bottom)

    def grab(self):
        client = self.window.rect()
        left, top, right, bottom = client
        ml, mt, mr, mb = self.bounds
        if left < ml or top < mt or right > mr or bottom > mb:
            raise RuntimeError("Game must be fully inside selected DXcam output; select correct device/output in settings")
        width, height = right - left, bottom - top
        rw = min(width, self.cfg.roi_size or width)
        rh = min(height, self.cfg.roi_size or height)
        x = left + (width - rw) // 2
        y = top + (height - rh) // 2
        region = (x - ml, y - mt, x - ml + rw, y - mt + rh)
        # Synchronous polling: no capture queue, no duplicate-frame video mode.
        image = self.camera.grab(region=region)
        if image is None:
            return None
        duplicator = getattr(self.camera, "_duplicator", None)
        timestamp = float(getattr(duplicator, "latest_frame_time", 0.0))
        if timestamp <= self.last_timestamp:
            return None
        if timestamp > time.perf_counter():
            raise RuntimeError("DXGI timestamp is not in the performance-counter clock domain")
        self.last_timestamp = timestamp
        self.sequence += 1
        self.last_rect = client
        center = (left + width / 2 - x, top + height / 2 - y)
        return Frame(image, timestamp, self.sequence, center, (width, height))

    def close(self):
        self.camera.release()
