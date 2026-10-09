# Changelog

本项目的主要变化记录在此。版本号遵循 [Semantic Versioning](https://semver.org/)。

## [Unreleased]

## [0.1.0] - 2026-10-09

### Added

- Windows 中文图形界面以及预览、调色、环境检查和命令行入口。
- 基于 DXcam、OpenCV HSV 分割与轮廓几何的静止圆靶识别。
- 针孔相机透视映射、水平 FOV 配置和 X/Y 双轴鼠标计数校准。
- 低速闭环学习，用于根据移动后的新画面估计有效控制比例。
- 普通高速控制：多目标保存、三目标最短访问顺序、移动后新帧确认和有限残差修正。
- 实验性极高速控制：当前帧三目标路线规划、一步移动和输入后画面响应保护。
- F8 启用/暂停、F9 退出、前台窗口校验、窗口几何校验和无视觉响应自动暂停。
- JSONL 运行日志、错误报告、离线模拟和参考图分析工具。
- 项目内隔离的 Python 环境、PyInstaller Windows 目录式打包脚本和自动化测试。

### Known limitations

- 主要面向 Aimlabs 静止圆靶场景；移动靶预测和结果界面 OCR 尚未实现。
- 不同分辨率、FOV、灵敏度或输入设置需要重新校准。
- Windows 可运行包为目录式分发，必须保留 `AimlabVision.exe` 同目录下的 `_internal`。
- 项目不保证与所有输入环境兼容，也不提供规避检测或处罚的保证。

[Unreleased]: https://github.com/myabs666/aimlabs/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/myabs666/aimlabs/releases/tag/v0.1.0
