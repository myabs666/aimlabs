# 参与贡献

感谢你改进 AimVision。提交代码前，请先说明要解决的问题，并尽量让改动保持小而明确。

## 开发环境

项目面向 Windows 10/11 与 Python 3.13 x64。所有依赖、缓存、日志和构建结果都应保留在工程目录内。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
.\scripts\start.ps1 test
```

不要提交 `.venv/`、`.runtime/`、`dist/`、`release/`、`logs/`、`artifacts/`、`temp/` 或 `config/local*.json`。不要在源码、文档或测试数据中写入本机绝对路径、账号令牌或个人校准数据。

## 修改流程

1. 从目标分支创建独立分支。
2. 修改前先复现问题，并记录分辨率、水平 FOV、游戏模式和控制模式。
3. 将平台相关操作保留在 `aimvision/win32.py`、`aimvision/capture.py` 等边界模块中。
4. 为控制状态机、坐标换算或检测逻辑的行为变化补充有意义的回归测试。
5. 运行测试和离线模拟；涉及打包流程时再执行完整构建。

```powershell
.\scripts\start.ps1 test
.\scripts\start.ps1 simulate
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build.ps1
```

## 提交与合并请求

- 提交信息应描述行为变化，例如“修复新帧确认期间的重复移动”。
- 合并请求应说明问题、修改后的行为、验证方式和仍存在的限制。
- 性能优化请附带相同输入下的前后数据，至少包含检测耗时、移动次数和重复修正率。
- 不要以真实命中率替代可重复的离线测试，也不要声称能够绕过检测或处罚机制。

## 项目范围

当前项目采用桌面画面捕获、OpenCV 检测和普通 Windows `SendInput`。请勿提交内核驱动、进程注入、内存读取或规避平台安全机制的实现。使用者应自行确认自动化是否符合游戏规则及适用条款。

## 报告问题

问题报告应包含复现步骤、预期行为、实际行为和经过脱敏的日志片段。提交日志前请删除用户名、绝对路径及其他个人信息。
