# 参考与复用边界

调研日期：2026-09-16。该工程的控制状态机、输入封装、窗口校验、运动控制、校准、界面与测试为独立实现。没有复制其他自动打靶仓库的源文件，也没有捆绑其模型、驱动或二进制。

| 来源 | 查看或参考的部分 | 本工程采用方式 |
| --- | --- | --- |
| https://github.com/ruali-dev/aimlab-gridshot-with-opencv-python | vision.py、controller.py、main.py 与 README；HSV 分割、轮廓过滤、残影问题、模块划分 | 参考思路，重新实现。其开环流程改为每次移动后读取新画面的闭环。未复制 MIT 源码 |
| https://github.com/Gnay11111/autoaim | autoaim.py 与 README 中屏幕投影、灵敏度换算方法 | 根据标准透视投影公式独立实现；未复制源码 |
| https://github.com/Hjjj0918/Aimlab-sixshot | README 的截屏 / 检测 / 控制结构 | 仅参考分层；未采用 Interception、MiniUNet 或模型权重 |
| https://github.com/ra1nty/DXcam | 官方 API 和安装后的 0.3.0 源码 | 直接依赖；同步 grab(new_frame_only=True)，不使用旧帧回放；读取 output.desc 以处理显示器桌面原点 |
| https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput | SendInput、返回值、UIPI | 通过 ctypes 定义完整 INPUT 联合体，检查返回值 |
| https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-mouseinput | 相对移动与鼠标按钮事件 | 普通用户态输入，不操作注入标记 |

DXcam 的 `_output.desc` 为内部接口，所以固定版本并在运行时检查。升级前需重新做窗口几何和截屏测试。

平滑轨迹用于控制稳定性。普通 SendInput 的注入来源仍可能被系统识别；本工程没有反检测、隐藏进程、驱动或反作弊绕过模块，也没有对应效果承诺。

第三方发行包自带的许可证仍适用。打包时应保留依赖许可证，不能因为应用代码为独立实现而移除它们。
