from contextlib import contextmanager
from .config import local_path


def stop_requested():
    return local_path(".runtime/stop.request").exists()


@contextmanager
def live_session():
    """One live capture/input process at a time; GUI stop is a graceful request."""
    import msvcrt
    path = local_path(".runtime/session.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError("Another live AimVision session is already running") from exc
        try:
            local_path(".runtime/stop.request").unlink(missing_ok=True)
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
