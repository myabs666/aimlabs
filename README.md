# AimVision

Windows 上针对 Aimlabs 静止圆靶的外部视觉自动打靶原型。使用 Python、DXcam、OpenCV 和普通 `SendInput`，提供中文启动界面、颜色调试、双轴校准、闭环控制、日志和离线模拟。

**默认只预览或暂停。自动控制必须先完成校准，再切回游戏按 F8 启用。F9 退出。** 平滑移动用于减少抖动，不代表避免检测。

## 启动

已构建时，双击 `dist/AimlabVision/AimlabVision.exe`。必须保留同目录 `_internal`，这是目录式打包，不是单文件 EXE。

源码启动：双击 `start.cmd`，或在本工程 PowerShell 中执行：

```powershell
.\scripts\start.ps1
```

首次在其他环境安装（需要已有 Python 3.13 x64）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

所有依赖装入 `.venv`；临时与缓存写入 `.runtime`；不修改全局 Python 或系统设置。仅当前进程设置 TEMP/TMP 等环境变量。不要从外部工具自行使用默认缓存目录安装依赖。

## 第一次使用

1. 启动 Aimlabs，建议先用无边框窗口，确保整个游戏客户区位于同一显示器。
2. 启动界面中运行“环境检查”，核对游戏窗口、显卡和显示器。已实测窗口标题为 `aimlab_tb`，进程为 `aimlab_tb.exe`，当时客户区为 `2880×1800`。
3. 将“水平 FOV”改为游戏实际使用的水平视场角。默认 103 只是起始值，并非已从游戏读取。不要混淆垂直 FOV 或其他游戏预设的换算值。
4. 打开“调色预览”。绿色圆圈表示完整靶，蓝色圆圈表示由可见圆弧推断的遮挡靶。中心白色小点是准星，不应被标记。拖动 Low/High H/S/V 滑块，在预览窗口按 **S** 保存；H 范围 0..179，S/V 范围 0..255。按 Q 或 F9 结束。调色期间不发送鼠标输入。
5. 进入有静止圆靶的场景。打开“靶场校准”，画面中可以同时有多个靶；程序会选择准星附近的完整靶，忽略枪械遮挡靶。切回游戏只按一次 F8，程序会自动执行 X/Y 各 3 次探测，共 6 次；每次小幅移动后自动反向返回。过程中不要自行移动鼠标。校准不射击，全部通过才保存。
6. 基础校准成功后点击“低速闭环学习”，进入 Gridshot 等静止圆靶任务并按一次 **F8**。开始阶段分别移动 X/Y，每轴取得 3 个样本后自动切换为 X/Y 同步移动；可信样本增加时，增益会从 0.45 提升到 0.95，单轴步长上限从 30 提升到 180。预览状态栏会显示 `1D/2D`、当前 gain 和 cap。连续完成至少 8 个靶后保存学习结果。中途 F9 退出不会保存未完成学习。
7. 移动方式选择 `direct`，点击“启动高速控制”，切回游戏按 **F8**。它会以 X/Y 同步大步接近目标，再根据新帧微调；再次 F8 暂停，**F9** 退出。`smooth` 保留加速度限制，移动会明显更慢。

高速静止靶建议使用 `direct`；`baseline` 使用相同的直接闭环算法，`smooth` 用于观察带速度和加速度限制的轨迹。校准阶段若靶移出识别区域，减小 `calibration_probe_counts`；若测不到足够位移，可适当增大，配置限制不超过 200。

截屏边长默认 **0（整个客户区）**，避免漏掉远离准星的靶。若全画面处理较慢，可改为 800、1200 等中心区域；区域外的靶不会被检测，所有靶都在区域外时程序会等待，需要手动调整视角或扩大区域。

切换游戏灵敏度、FOV、视角预设、输入设置或分辨率后必须重新校准。程序会自动拦截客户区尺寸变化；游戏内部灵敏度变化无法通过窗口信息自动得知。GUI 修改 FOV 会清除旧校准。

## 命令行

```powershell
.venv\Scripts\python.exe -B run.py doctor --capture-test
.venv\Scripts\python.exe -B run.py preview
.venv\Scripts\python.exe -B run.py tune
.venv\Scripts\python.exe -B run.py calibrate
.venv\Scripts\python.exe -B run.py learn
.venv\Scripts\python.exe -B run.py run
.venv\Scripts\python.exe -B run.py run --headless
.venv\Scripts\python.exe -B run.py simulate
.venv\Scripts\python.exe -B run.py test
```

`doctor --capture-test` 验证桌面截图但不保存屏幕像素。`simulate` 只渲染合成靶场，不发送任何真实输入。`--headless` 隐藏运行预览窗口，可降低额外渲染负担；快捷键仍有效。

| 快捷键 | 含义 |
| --- | --- |
| F8 | 游戏前台启用/暂停控制；基础校准中一次启动全部 6 个探测 |
| F9 | 退出当前预览、控制或校准任务 |
| F10 | 预览/控制中保存当前 ROI 截图到 artifacts |
| S | 调色预览窗口内保存 HSV |
| Q / Esc | 预览窗口内退出 |

## 实现与边界

截屏 → HSV/轮廓检测 → 锁定目标 → 相对鼠标短段移动 → 等待移动后的画面 → 二次识别同一目标并微调 → 连续帧确认 → 点击 → 观察目标消失。

- 只接受配置中的游戏进程名及窗口标题；每次输入前确认游戏仍在前台、窗口几何未变。
- 自动控制默认未启用；失焦、窗口移动/缩放、缺少新帧、超时或点击多次无结果会暂停，需要 F8 重新启用。
- 目标消失记录为 `observed_disappearances`，不等同于游戏确认的命中。真实命中率以游戏结果为准。
- 日志的 `attempted_shots` 是控制器发出的射击请求数；输入失败也可能包含在内，需结合 `input_error` 事件判断。
- 坐标映射使用针孔相机透视投影：像素偏移先经过 `atan` 转为相机局部偏航角/俯仰角，因此已包含屏幕边缘的非线性透视关系。这里假设配置值确实是水平 FOV 且像素为方形；特殊拉伸比例或 Aimlabs 中不同的 FOV 约定需要重新验证。低速闭环学习会在每个短步后重新识别，能减少初始 FOV 或灵敏度误差造成的累积偏差。
- 先支持 Gridshot 等静止靶。Sixshot 的小靶需要实际调色与精度测量；移动靶预测、游戏结果 OCR 尚未实现。
- DXcam 捕获的是显示器上的游戏区域，不是可读取被遮挡内容的窗口后台截图；游戏被遮挡时不要启用控制。
- `SendInput` 成功只说明系统接收事件，不保证游戏处理或命中。若被拒绝，日志记录失败，程序不会自动改装驱动或切换输入路径。
- 显示器排列、DPI 缩放和负坐标通过客户区屏幕坐标与 DXGI 输出原点转换。游戏跨显示器时直接提示调整。
- 本工程未验证当前 Aimlabs 对自动化的检测或处罚机制，不提供免检测保证。

## 文件位置

```text
aimvision/          应用源码
config/default.json 默认设置（不含个人校准）
config/local.json   当前设置与校准结果
tests/              图像、控制、校准与模拟回归测试
scripts/            启动、安装、打包脚本
docs/               参考来源与验证记录
artifacts/          环境报告、截图、模拟报告
logs/               运行 JSONL、启动器输出、错误栈
.runtime/           临时文件、依赖缓存、构建中间产物
.venv/              工程独立 Python 环境
dist/               目录式 EXE
```

所有应用输出路径均限制在工程内；传入工程外 `--config` 会报错。复制完整 EXE 文件夹到新位置时，它会在该文件夹内创建自己的配置与运行目录。在当前工程内运行打包版时，继续使用工程根目录的配置和日志。

项目内 `temp/` 的参考截图可重新分析：

```powershell
.venv\Scripts\python.exe -B scripts\analyze_references.py
```

逐张标注图、颜色掩膜和坐标报告写入 `artifacts/reference-analysis/`。当前六张青色大圆靶截图无需训练神经网络；颜色、圆形几何、距离变换已能处理普通靶、枪械遮挡靶和两个相接的靶。

## 验证与打包

```powershell
.\scripts\start.ps1 test
.\scripts\start.ps1 simulate
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build.ps1
```

离线测试覆盖新旧帧、校准、目标保持、有限重试、尺寸变化、颜色识别和两种控制模式的合成场景收敛。它不能替代游戏内命中率、真实输入兼容性或防检测验证。

来源与复用范围见 [docs/REFERENCES.md](docs/REFERENCES.md)。
