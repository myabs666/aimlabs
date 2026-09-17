import argparse
from datetime import datetime
import importlib.metadata
import json
import sys
import time
import traceback
from .config import Config, ROOT, local_path
from .session import live_session, stop_requested


def choose_window(cfg):
    from .win32 import find_windows
    windows = find_windows(cfg)
    if not windows:
        raise RuntimeError("Aimlabs window not found. Start the game, then check window_title and process_names in settings.")
    if len(windows) > 1:
        raise RuntimeError("Multiple matching game windows; narrow window_title in settings")
    return windows[0]


def doctor(cfg, capture_test=False):
    from .win32 import dpi_aware, find_windows, INPUT
    from .capture import load_dxcam
    import ctypes
    dpi_aware()
    result = {"python": sys.version, "root": str(ROOT), "input_struct_bytes": ctypes.sizeof(INPUT),
              "versions": {name: importlib.metadata.version(name) for name in ("numpy", "opencv-python", "dxcam")},
              "calibrated": cfg.calibrated, "windows": []}
    for window in find_windows(cfg):
        result["windows"].append({"title": window.title, "process": window.process, "client": window.rect()})
    dxcam = load_dxcam()
    result["devices"] = dxcam.device_info()
    result["outputs"] = dxcam.output_info()
    if capture_test:
        camera = dxcam.create(device_idx=cfg.device_idx, output_idx=cfg.output_idx, output_color="BGR")
        try:
            deadline = time.perf_counter() + 3
            frame = None
            while frame is None and time.perf_counter() < deadline:
                frame = camera.grab()
                time.sleep(.01)
            result["capture_shape"] = list(frame.shape) if frame is not None else None
            if frame is None:
                raise RuntimeError("No desktop frame captured")
        finally:
            camera.release()
    path = local_path("artifacts/doctor.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def live(cfg, config_path, control=False, tune=False, headless=False, ultra=False):
    import cv2
    from .win32 import dpi_aware, Keys, Mouse
    from .capture import Capture
    from .controller import Controller
    from .detector import Detector, annotate
    from .telemetry import Telemetry
    dpi_aware()
    window = choose_window(cfg)
    detector, controller, keys = Detector(cfg), Controller(cfg, ultra=ultra), Keys()
    capture = Capture(cfg, window)
    log = Telemetry("control" if control else "preview")
    # The guard is checked immediately before each injected event.
    armed_rect = None
    mouse = Mouse(lambda: controller.active and window.foreground() and window.rect() == armed_rect)
    last_frame_at, last_preview, last_error = time.perf_counter(), 0.0, ""
    task_started = False
    task_end_guard_at = float("inf")
    title = "AimVision preview | F8 toggle in game | F9 stop | F10 snapshot"
    if not headless:
        cv2.namedWindow(title, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(title, 640, 640)
        if tune:
            for prefix, values in (("Low", cfg.hsv_low), ("High", cfg.hsv_high)):
                for i, name in enumerate(("H", "S", "V")):
                    cv2.createTrackbar(f"{prefix} {name}", title, values[i], 179 if i == 0 else 255, lambda _: None)
    print("Ready. F8 toggles control only while Aimlabs is foreground. F9 exits. F10 saves a project-local snapshot.", flush=True)
    if not control:
        print("PREVIEW ONLY: mouse input disabled. Tune mode: press S in preview to save HSV.", flush=True)
    log.event("start", control=control, mode=cfg.mode, ultra=ultra,
              config=str(config_path), window=window.title)
    last_frame = None
    try:
        while True:
            start = time.perf_counter()
            mouse.tick()
            if keys.pressed(0x78) or stop_requested():  # F9
                break
            toggle = keys.pressed(0x77)
            if toggle and control:
                if controller.active:
                    controller.pause("hotkey")
                    mouse.release_all()
                elif window.foreground():
                    try:
                        armed_rect = window.rect()
                        size = (armed_rect[2] - armed_rect[0], armed_rect[3] - armed_rect[1])
                        if tuple(cfg.calibrated_size) != size:
                            raise ValueError("Window size differs from calibration; recalibrate")
                        controller.arm()
                        if not task_started:
                            mouse.click(cfg.click_hold_ms)
                            countdown_at = time.perf_counter()
                            controller.begin_countdown(countdown_at)
                            task_end_guard_at = controller.end_guard_at
                            task_started = True
                            log.event("start_click", countdown_ms=cfg.start_countdown_ms)
                        else:
                            controller.set_end_guard(task_end_guard_at)
                        last_frame_at = start
                    except (ValueError, RuntimeError) as exc:
                        controller.pause(str(exc))
                        mouse.release_all()
                log.event("toggle", state=controller.state)
                print(controller.state, flush=True)
            if controller.active and (not window.foreground() or window.rect() != armed_rect):
                controller.pause("focus / geometry changed")
                mouse.release_all()
                log.event("pause", reason=controller.state)
            snapshot = keys.pressed(0x79)
            if tune:
                for prefix, name in (("Low", "hsv_low"), ("High", "hsv_high")):
                    setattr(cfg, name, [cv2.getTrackbarPos(f"{prefix} {channel}", title) for channel in ("H", "S", "V")])
            try:
                capture_started = time.perf_counter()
                frame = capture.grab()
                capture_finished = time.perf_counter()
                last_error = ""
            except RuntimeError as exc:
                controller.pause(str(exc))
                mouse.release_all()
                frame = None
                if str(exc) != last_error:
                    print(str(exc), flush=True)
                    log.event("capture_error", error=str(exc))
                    last_error = str(exc)
            if frame is not None:
                last_frame_at = frame.timestamp
                detection_started = time.perf_counter()
                targets, mask = detector.detect(frame)
                detection_finished = time.perf_counter()
                now = time.perf_counter()
                if controller.active and (now - frame.timestamp) * 1000 > cfg.stale_pause_ms:
                    controller.pause("desktop frame timestamp is stale")
                    mouse.release_all()
                    log.event("pause", reason=controller.state)
                action = controller.update(frame, targets, now)
                try:
                    if action.kind == "move":
                        mouse.move(action.dx, action.dy)
                        controller.wait_until = time.perf_counter() + cfg.move_settle_ms / 1000
                    elif action.kind == "move_click":
                        mouse.move_click(action.dx, action.dy, cfg.click_hold_ms,
                                         cfg.ultra_move_click_delay_ms)
                        controller.last_shot = time.perf_counter()
                        controller.wait_until = controller.last_shot + cfg.shot_cooldown_ms / 1000
                    elif action.kind == "click":
                        mouse.click(cfg.click_hold_ms)
                        controller.last_shot = time.perf_counter()
                        controller.wait_until = controller.last_shot + cfg.shot_cooldown_ms / 1000
                    elif action.kind == "pause":
                        mouse.release_all()
                    if action.kind != "none":
                        detail = {}
                        detail_target = (controller.last_clicked if action.kind in ("click", "move_click")
                                         else controller.selected)
                        if detail_target is not None:
                            detail["target"] = [detail_target.x, detail_target.y,
                                                detail_target.radius]
                        if controller.predicted is not None:
                            detail["predicted"] = list(controller.predicted)
                        if action.kind in ("move", "move_click"):
                            detail["move_number"] = (1 if action.kind == "move_click"
                                                     else controller.moves_on_lock)
                        detail["route_remaining"] = len(controller.saved_route)
                        detail["pending_results"] = len(controller.pending_shots)
                        log.event(action.kind, dx=action.dx, dy=action.dy, state=controller.state,
                                  reason=action.reason, **detail)
                except RuntimeError as exc:
                    controller.pause(str(exc))
                    mouse.release_all()
                    log.event("input_error", error=str(exc))
                    print(str(exc), flush=True)
                log.frame((time.perf_counter() - frame.timestamp) * 1000, controller,
                          (capture_finished - capture_started) * 1000,
                          (detection_finished - detection_started) * 1000)
                last_frame = frame
                if not headless and now - last_preview >= 1 / cfg.preview_hz:
                    state = controller.state if control else f"PREVIEW ONLY | targets={len(targets)}"
                    cv2.imshow(title, annotate(frame, targets, state, controller.selected))
                    if tune:
                        cv2.imshow("HSV mask", mask)
                    last_preview = now
            elif controller.active and (time.perf_counter() - last_frame_at) * 1000 > cfg.stale_pause_ms:
                controller.pause("no fresh frames")
                mouse.release_all()
                log.event("pause", reason=controller.state)
            if snapshot and last_frame is not None:
                path = local_path(f"artifacts/snapshot-{datetime.now():%Y%m%d-%H%M%S-%f}.png")
                path.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(path), last_frame.image)
                print(f"Saved {path}", flush=True)
            mouse.tick()
            if not headless:
                key = cv2.waitKey(1) & 0xff
                if key in (27, ord('q')) or cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                    break
                if tune and key == ord('s'):
                    try:
                        cfg.save(config_path)
                        print(f"Saved HSV: {config_path}", flush=True)
                    except ValueError as exc:
                        print(f"Invalid HSV: {exc}", flush=True)
            if not capture.threaded:
                time.sleep(max(0, 1 / cfg.capture_hz - (time.perf_counter() - start)))
    finally:
        controller.pause("exit")
        try:
            mouse.release_all()
        finally:
            capture.close()
            cv2.destroyAllWindows()
            log.event("stop", frames=log.frame_count, attempted_shots=controller.shots, observed_disappearances=controller.disappearances)
            log.close()
    return 0


def calibrate(cfg, config_path):
    import cv2
    from .win32 import dpi_aware, Keys, Mouse
    from .capture import Capture
    from .detector import Detector, annotate
    from .calibration import estimate_scale, combine_samples, match_target, select_target
    from .telemetry import Telemetry
    dpi_aware()
    window = choose_window(cfg)
    initial_rect = window.rect()
    capture, detector, keys = Capture(cfg, window), Detector(cfg), Keys()
    mouse = Mouse(lambda: window.foreground() and window.rect() == initial_rect)
    log = Telemetry("calibration")
    title = "Calibration | F8 starts six automatic probes | F9 stop"
    cv2.namedWindow(title, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(title, 640, 640)
    samples = [[], []]
    axis, state, deadline, phase_timeout, last_frame_at = 0, "READY", 0.0, 0.0, time.perf_counter()
    before = None
    requested = False
    automatic = False
    next_probe_at = 0.0
    size = None
    print("Keep the visible targets stationary. Press F8 once; six automatic probes measure X/Y and return the view after every probe. No shots are fired. F9 aborts.", flush=True)
    try:
        while axis < 2:
            now = time.perf_counter()
            if keys.pressed(0x78) or stop_requested():
                return 0
            trigger = keys.pressed(0x77)
            if window.rect() != initial_rect:
                raise RuntimeError("Window geometry changed during calibration")
            if state != "READY" and not window.foreground():
                raise RuntimeError("Focus lost during probe; calibration aborted without saving")
            if trigger and state == "READY" and window.foreground() and not automatic:
                automatic = True
                next_probe_at = now
                print("Automatic calibration started: 3 X probes, then 3 Y probes.", flush=True)
                log.event("automatic_started")
            if automatic and state == "READY" and window.foreground() and now >= next_probe_at:
                requested = True
            frame = capture.grab()
            if frame is not None:
                last_frame_at = now
                targets, _ = detector.detect(frame)
                size = frame.client_size
                candidate = select_target(targets, frame.center, min(frame.image.shape[:2]) * .45)
                if requested:
                    requested = False
                    log.event("probe_requested", axis=axis, detected_targets=len(targets),
                              intact_targets=sum(target.quality >= .8 for target in targets))
                    if candidate is None:
                        message = "No intact target found near the center; checking again after HSV detection / target placement."
                        print(message, flush=True)
                        log.event("probe_rejected", axis=axis, reason=message)
                        next_probe_at = time.perf_counter() + .5
                    else:
                        before = candidate
                        counts = cfg.calibration_probe_counts
                        mouse.move(counts if axis == 0 else 0, counts if axis == 1 else 0)
                        deadline = time.perf_counter() + cfg.calibration_settle_ms / 1000
                        phase_timeout = deadline + .75
                        state = "PROBE"
                        log.event("probe_sent", axis=axis, counts=counts, target=[before.x, before.y],
                                  detected_targets=len(targets))
                        print(f"Axis {'XY'[axis]} probe sent: {counts} counts; waiting for a fresh frame.", flush=True)
                elif state == "PROBE" and frame.timestamp >= deadline:
                    after = match_target(before, targets, max(250.0, before.radius * 3), min_quality=.3)
                    if after is None:
                        if now >= phase_timeout:
                            log.event("probe_retry", axis=axis, reason="selected target was not matched after movement",
                                      targets=[[target.x, target.y, target.quality] for target in targets])
                            counts = -cfg.calibration_probe_counts
                            mouse.move(counts if axis == 0 else 0, counts if axis == 1 else 0)
                            deadline = time.perf_counter() + cfg.calibration_settle_ms / 1000
                            state = "RECOVER"
                            print("Target association was unstable; returning view and retrying automatically.", flush=True)
                    else:
                        try:
                            scale = estimate_scale(before, after, frame.center, frame.client_size[0], cfg.horizontal_fov, cfg.calibration_probe_counts, axis)
                        except ValueError as exc:
                            log.event("probe_retry", axis=axis, reason=str(exc), before=[before.x, before.y],
                                      after=[after.x, after.y, after.quality])
                            counts = -cfg.calibration_probe_counts
                            mouse.move(counts if axis == 0 else 0, counts if axis == 1 else 0)
                            deadline = time.perf_counter() + cfg.calibration_settle_ms / 1000
                            state = "RECOVER"
                            print(f"Probe measurement was unusable ({exc}); returning view and retrying.", flush=True)
                        else:
                            samples[axis].append(scale)
                            log.event("sample", axis=axis, scale=scale, before=[before.x, before.y],
                                      after=[after.x, after.y], after_quality=after.quality)
                            print(f"Axis {'XY'[axis]} sample {len(samples[axis])}/3: {scale:.3f} counts/radian", flush=True)
                            counts = -cfg.calibration_probe_counts
                            mouse.move(counts if axis == 0 else 0, counts if axis == 1 else 0)
                            deadline = time.perf_counter() + cfg.calibration_settle_ms / 1000
                            phase_timeout = deadline + .75
                            state = "RETURN"
                            log.event("return_sent", axis=axis, counts=counts)
                elif state == "RETURN" and frame.timestamp >= deadline:
                    returned = match_target(before, targets, max(30.0, before.radius * .75), min_quality=.3)
                    if returned is None:
                        if now >= phase_timeout:
                            log.event("return_failed", axis=axis,
                                      targets=[[target.x, target.y, target.quality] for target in targets])
                            raise RuntimeError("Probe did not return near its starting point; check stationary target and mouse settings")
                    else:
                        if len(samples[axis]) == 3:
                            combine_samples(samples[axis])
                            axis += 1
                        state = "READY"
                        next_probe_at = time.perf_counter() + .35
                elif state == "RECOVER" and frame.timestamp >= deadline:
                    state = "READY"
                    next_probe_at = time.perf_counter() + .5
                    log.event("retry_ready", axis=axis)
                label = f"{'XY'[min(axis,1)]}: {len(samples[min(axis,1)])}/3 | {state} | targets={len(targets)} | {'AUTO' if automatic else 'F8 start'}"
                cv2.imshow(title, annotate(frame, targets, label, before if state != "READY" else candidate))
            elif state != "READY" and now - last_frame_at > 1:
                raise RuntimeError("No fresh calibration frame; aborted without saving")
            if state != "READY" and now > deadline + 3:
                raise RuntimeError("Calibration probe timed out")
            key = cv2.waitKey(1) & 0xff
            if key in (27, ord('q')) or cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                return 0
            if not capture.threaded:
                time.sleep(1 / cfg.capture_hz)
        cfg.counts_per_radian_x = combine_samples(samples[0])
        cfg.counts_per_radian_y = combine_samples(samples[1])
        cfg.calibrated_size = list(size)
        cfg.save(config_path)
        log.event("saved", x=cfg.counts_per_radian_x, y=cfg.counts_per_radian_y, size=size)
        print(f"Calibration saved to {config_path}", flush=True)
    finally:
        mouse.release_all()
        capture.close()
        cv2.destroyAllWindows()
        log.close()
    return 0


def learn(cfg, config_path):
    """Run deliberate one-axis movements and re-measure after every fresh frame."""
    if not cfg.calibrated:
        raise RuntimeError("Complete base automatic calibration before low-speed learning")
    import cv2
    from .win32 import dpi_aware, Keys, Mouse
    from .capture import Capture
    from .detector import Detector, annotate
    from .learning import LearningController
    from .telemetry import Telemetry
    dpi_aware()
    window = choose_window(cfg)
    initial_rect = window.rect()
    capture, detector, keys = Capture(cfg, window), Detector(cfg), Keys()
    learner = LearningController(cfg)
    mouse = Mouse(lambda: learner.active and window.foreground() and window.rect() == initial_rect)
    log = Telemetry("learning")
    title = "Low-speed learning | F8 start/pause | F9 stop"
    cv2.namedWindow(title, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(title, 640, 640)
    last_preview = 0.0
    saved = False
    print(f"Low-speed learning ready. F8 starts {cfg.learning_hits} deliberate target shots; every small move is re-detected before the next. F9 exits.", flush=True)
    log.event("start", x=cfg.counts_per_radian_x, y=cfg.counts_per_radian_y,
              required_targets=cfg.learning_hits)
    try:
        while True:
            now = time.perf_counter()
            mouse.tick()
            if keys.pressed(0x78) or stop_requested():
                break
            if keys.pressed(0x77):
                if learner.active:
                    learner.pause("hotkey")
                    mouse.release_all()
                elif window.foreground():
                    learner.arm()
                print(learner.state, flush=True)
                log.event("toggle", state=learner.state)
            if learner.active and (not window.foreground() or window.rect() != initial_rect):
                learner.pause("focus / geometry changed")
                mouse.release_all()
                log.event("pause", reason=learner.state)
            frame = capture.grab()
            if frame is None:
                if not capture.threaded:
                    time.sleep(1 / cfg.capture_hz)
                continue
            targets, _ = detector.detect(frame)
            now = time.perf_counter()
            action = learner.update(frame, targets, now)
            try:
                if action.kind == "move":
                    mouse.move(action.dx, action.dy)
                    learner.wait_until = time.perf_counter() + cfg.learning_settle_ms / 1000
                elif action.kind == "click":
                    mouse.click(cfg.click_hold_ms)
                    learner.last_shot = time.perf_counter()
                    learner.wait_until = learner.last_shot + cfg.shot_cooldown_ms / 1000
                elif action.kind in ("pause", "done"):
                    mouse.release_all()
                if action.kind != "none":
                    log.event(action.kind, dx=action.dx, dy=action.dy,
                              state=learner.state, reason=action.reason)
            except RuntimeError as exc:
                learner.pause(str(exc))
                mouse.release_all()
                log.event("input_error", error=str(exc))
            for event, fields in learner.pop_events():
                log.event(event, **fields)
                if event == "sample":
                    print(f"Axis {'XY'[fields['axis']]} sample {fields['count']}: measured={fields['value']:.2f}, active={fields['applied']:.2f}", flush=True)
            if action.kind == "done":
                counts = learner.finalize()
                cfg.save(config_path)
                saved = True
                log.event("saved", x=cfg.counts_per_radian_x, y=cfg.counts_per_radian_y,
                          x_samples=counts[0], y_samples=counts[1])
                print(f"Low-speed learning complete and saved: X={cfg.counts_per_radian_x:.2f}, Y={cfg.counts_per_radian_y:.2f}, samples={counts}", flush=True)
                break
            if now - last_preview >= 1 / cfg.preview_hz:
                label = (f"{learner.state} | hits={learner.disappearances}/{cfg.learning_hits} | "
                         f"samples X/Y={len(learner.samples[0])}/{len(learner.samples[1])} | "
                         f"{learner.move_phase} gain={learner.current_gain:.2f} cap={learner.current_cap}")
                cv2.imshow(title, annotate(frame, targets, label, learner.selected))
                last_preview = now
            key = cv2.waitKey(1) & 0xff
            if key in (27, ord('q')) or cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                break
            if not capture.threaded:
                time.sleep(1 / cfg.capture_hz)
    finally:
        learner.pause("exit")
        mouse.release_all()
        capture.close()
        cv2.destroyAllWindows()
        log.event("stop", saved=saved, attempted_shots=learner.shots,
                  observed_disappearances=learner.disappearances)
        log.close()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="AimVision — external capture and ordinary mouse control")
    parser.add_argument("command", nargs="?", default="gui", choices=["gui", "doctor", "preview", "tune", "calibrate", "learn", "run", "ultra", "simulate", "test"])
    parser.add_argument("--config", default="config/local.json")
    parser.add_argument("--headless", action="store_true", help="Hide control preview (run only)")
    parser.add_argument("--capture-test", action="store_true", help="doctor: capture one desktop frame without saving pixels")
    args = parser.parse_args(argv)
    try:
        if args.command == "test":
            import unittest
            suite = unittest.defaultTestLoader.discover(str(local_path("tests")))
            if suite.countTestCases() == 0:
                raise RuntimeError("No tests found; use the full source project to run tests")
            return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
        if args.command == "simulate":
            from .simulation import run_simulation
            return run_simulation()
        path = local_path(args.config)
        if not path.exists():
            Config.load("config/default.json").save(path)
        cfg = Config.load(path)
        if args.command == "gui":
            from .gui import launch
            return launch(path)
        if args.command == "doctor":
            with live_session():
                return doctor(cfg, args.capture_test)
        if args.headless and args.command not in ("run", "ultra"):
            raise ValueError("--headless is only supported by run/ultra")
        with live_session():
            if args.command == "calibrate":
                return calibrate(cfg, path)
            if args.command == "learn":
                return learn(cfg, path)
            return live(cfg, path, control=args.command in ("run", "ultra"),
                        tune=args.command == "tune", headless=args.headless,
                        ultra=args.command == "ultra")
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        folder = local_path("logs")
        folder.mkdir(parents=True, exist_ok=True)
        report = folder / f"error-{datetime.now():%Y%m%d-%H%M%S-%f}.txt"
        report.write_text(traceback.format_exc(), encoding="utf-8")
        print(f"ERROR: {exc}\nDetails: {report}", file=sys.stderr, flush=True)
        return 1
