# 安装脚本说明

一键安装与运行脚本位于工程根目录：`install.command` / `run.command` 用于 macOS，`install.bat` / `run.bat` 用于 Windows。均基于工程相对路径定位，不依赖用户当前工作目录。详见 docs/Python安装依赖.md。

打包脚本为根目录的 `build-macos.command` 和 `build-windows.bat`。Windows 脚本创建构建环境、安装 `requirements-build.txt`、运行打包程序和离屏冒烟检查，最后生成便携 ZIP。

## 重启已有实例

启动脚本通过 Python 入口统一执行：识别同一工程目录中以 `python -m paperreader` 启动的旧进程，先请求终止，3 秒未退出再强制结束，确认退出后启动新窗口。不会按 Python 进程名批量结束其他程序。同时启动的重复请求由启动锁拦截。macOS 收到终止信号时尝试保存笔记；Windows 终止和超时强杀无法保证保存尚未落盘的内容，后台 AI 请求可能被中断。升级前启动的旧版本未包含保存信号处理，只能保留已自动保存内容。新增 psutil 依赖，旧环境先重跑安装脚本。

安装脚本统一读取根目录 requirements.txt，包含公式渲染依赖 matplotlib。安装完成后执行 pip check，依赖不兼容则报告失败。
