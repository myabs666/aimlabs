from datetime import datetime
import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk
from .config import Config, ROOT, local_path


def launch(config_path):
    root = tk.Tk()
    root.title("AimVision · Aimlabs 视觉打靶")
    root.geometry("780x750")
    root.minsize(720, 640)
    style = ttk.Style(root)
    style.theme_use("vista")
    body = ttk.Frame(root, padding=20)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="AimVision", font=("Segoe UI", 23, "bold")).pack(anchor="w")
    ttk.Label(body, text="外部截屏 · 颜色识别 · 普通鼠标输入", font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=(0, 12))
    ttk.Label(body, text="操作顺序：启动 Aimlabs → 调色预览 → 单靶校准 → 启动控制\n切回游戏按 F8：自动点击启动，倒计时只瞄准，结束后自动射击。F9 随时退出。", justify="left").pack(anchor="w")
    form = ttk.LabelFrame(body, text="设置（更多参数在 config/local.json）", padding=12)
    form.pack(fill="x", pady=12)
    definitions = [
        ("window_title", "游戏窗口标题包含", str),
        ("horizontal_fov", "水平 FOV（与游戏实际设置一致）", float),
        ("roi_size", "截屏边长（0 = 整个客户区）", int),
        ("capture_hz", "连续截屏目标频率", int),
        ("device_idx", "显卡编号（环境检查可查看）", int),
        ("output_idx", "该显卡的显示器编号", int),
        ("mode", "移动方式", str),
    ]
    variables = {}
    for row, (name, label, _) in enumerate(definitions):
        ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=3)
        variable = tk.StringVar()
        variables[name] = variable
        widget = ttk.Combobox(form, textvariable=variable, values=["direct", "smooth", "baseline"], state="readonly") if name == "mode" else ttk.Entry(form, textvariable=variable)
        widget.grid(row=row, column=1, sticky="ew", padx=(20, 0), pady=3)
    form.columnconfigure(1, weight=1)
    calibration_text = tk.StringVar()
    ttk.Label(body, textvariable=calibration_text).pack(anchor="w")
    process, output_file, current_log = None, None, None
    log_position = 0
    closing = False

    def reload():
        cfg = Config.load(config_path)
        for name, _, _ in definitions:
            variables[name].set(str(getattr(cfg, name)))
        calibration_text.set(f"校准：X={cfg.counts_per_radian_x:.2f} / Y={cfg.counts_per_radian_y:.2f} counts/rad，窗口 {cfg.calibrated_size}" if cfg.calibrated else "校准：尚未完成，自动控制不会启用。")

    def save():
        try:
            cfg = Config.load(config_path)
            previous_fov = cfg.horizontal_fov
            for name, _, kind in definitions:
                setattr(cfg, name, kind(variables[name].get()))
            if cfg.horizontal_fov != previous_fov:
                cfg.counts_per_radian_x = cfg.counts_per_radian_y = 0
                cfg.calibrated_size = [0, 0]
            cfg.save(config_path)
            reload()
            return True
        except (ValueError, TypeError) as exc:
            messagebox.showerror("设置无效", str(exc), parent=root)
            return False

    toolbar = ttk.Frame(body)
    toolbar.pack(fill="x", pady=10)
    status = tk.StringVar(value="就绪。所有配置、日志、截图和临时文件均保存在工程内。")

    def start(command):
        nonlocal process, output_file, current_log, log_position
        if process is not None and process.poll() is None:
            messagebox.showinfo("已有任务", "请先停止当前任务。", parent=root)
            return
        if not save():
            return
        if command == "learn" and not Config.load(config_path).calibrated:
            messagebox.showerror("需要基础校准", "基础自动校准尚未成功保存。请先点击“基础自动校准”，切回游戏后按一次 F8，等待 X/Y 各 3 次探测全部完成并显示已保存。", parent=root)
            return
        if command == "calibrate":
            messagebox.showinfo("基础自动校准", "进入有静止圆靶的场景，保持靶不移动。画面中可以有多个靶，程序会选择准星附近无遮挡的靶。\n\n校准不射击。切回游戏后只需按一次 F8，程序会自动完成横轴和纵轴各 3 次小幅移动并返回。\n\n整个过程请勿移动鼠标。F9 可中止。", parent=root)
        elif command == "learn":
            messagebox.showinfo("低速闭环学习", "请先完成基础校准，再进入静止圆靶任务。切回游戏按 F8 后，程序会低速瞄准并打 8 个靶。\n\n每次只移动一个轴的一小段，等待新画面后二次识别同一靶，并据此修正 X/Y 灵敏度。完成后自动保存，再使用高速控制。F9 可中止且不会保存未完成学习。", parent=root)
        elif command == "run":
            messagebox.showinfo("全自动高速控制", "请停留在任务的开始界面并切回游戏，只按一次 F8。\n\n程序会自动点击左键启动任务；3.1 秒倒计时期间只瞄准不射击，结束后自动连续打靶。若一次射击后目标仍存在，会持续补射直到目标消失。F9 可随时停止。", parent=root)
        elif command == "ultra":
            messagebox.showinfo("极高速控制（实验）", "该模式使用独立的逐帧弹道循环：每个发生变化的新画面重新选靶，移动后短暂等待输入生效并立即开火。相同画面不会重复移动，连续无视觉响应会自动暂停。\n\n它可能比高速模式更快，也可能因灵敏度、FOV 或小靶误差降低准确率。当前高速模式不会被修改。切回游戏按一次 F8，F9 随时停止。", parent=root)
        args = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-B", str(ROOT / "run.py")]
        args += [command, "--config", str(config_path)]
        if command in ("run", "ultra"):
            args.append("--headless")
        current_log = local_path(f"logs/launcher-{datetime.now():%Y%m%d-%H%M%S-%f}.txt")
        current_log.parent.mkdir(parents=True, exist_ok=True)
        output_file = current_log.open("w", encoding="utf-8")
        log_position = 0
        text.delete("1.0", "end")
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        try:
            process = subprocess.Popen(args, cwd=ROOT, stdout=output_file, stderr=subprocess.STDOUT,
                                       env=env, creationflags=subprocess.CREATE_NO_WINDOW)
            status.set(f"运行中：{command}。F9 或“停止”可结束。")
        except OSError as exc:
            output_file.close()
            output_file = None
            messagebox.showerror("启动失败", str(exc), parent=root)

    def stop():
        if process is not None and process.poll() is None:
            local_path(".runtime/stop.request").write_text("stop", encoding="utf-8")
            status.set("正在请求停止并释放鼠标，请稍候…")

    buttons = [("保存设置", save), ("环境检查", lambda: start("doctor")), ("调色预览", lambda: start("tune")),
               ("基础自动校准", lambda: start("calibrate")), ("低速闭环学习", lambda: start("learn")),
               ("启动高速控制", lambda: start("run")), ("启动极高速控制", lambda: start("ultra")),
               ("停止", stop)]
    for i, (label, callback) in enumerate(buttons):
        ttk.Button(toolbar, text=label, command=callback).grid(row=i // 3, column=i % 3, sticky="ew", padx=3, pady=3)
    for i in range(3):
        toolbar.columnconfigure(i, weight=1)
    ttk.Label(body, textvariable=status, wraplength=720).pack(anchor="w", pady=(0, 6))
    text = tk.Text(body, height=10, wrap="word", font=("Consolas", 9))
    text.pack(fill="both", expand=True)
    bottom = ttk.Frame(body)
    bottom.pack(fill="x", pady=(8, 0))
    ttk.Button(bottom, text="运行离线模拟", command=lambda: start("simulate")).pack(side="left")
    ttk.Button(bottom, text="打开工程", command=lambda: os.startfile(ROOT)).pack(side="right")

    def poll():
        nonlocal process, output_file, log_position
        if current_log is not None and current_log.exists():
            with current_log.open("r", encoding="utf-8", errors="replace") as stream:
                stream.seek(log_position)
                chunk = stream.read()
                log_position = stream.tell()
            if chunk:
                text.insert("end", chunk)
                text.see("end")
        if process is not None and process.poll() is not None:
            status.set(f"任务结束，退出码 {process.returncode}。日志保存在 logs/。")
            process = None
            if output_file:
                output_file.close()
                output_file = None
            reload()
        if closing and process is None:
            root.destroy()
            return
        root.after(150, poll)

    def close():
        nonlocal closing
        closing = True
        if process is not None and process.poll() is None:
            stop()
        else:
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    reload()
    root.after(150, poll)
    root.mainloop()
    return 0
