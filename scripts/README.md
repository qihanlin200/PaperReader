# 安装脚本说明

一键安装与运行脚本位于工程根目录：`install.command` / `run.command` 用于 macOS，`install.bat` / `run.bat` 用于 Windows。均基于工程相对路径定位，不依赖用户当前工作目录。详见 docs/Python安装依赖.md。

打包脚本为根目录的 `build-macos.command` 和 `build-windows.bat`。Windows 脚本创建构建环境、安装 `requirements-build.txt`、运行打包程序和离屏冒烟检查，最后生成便携 ZIP。

## 重启已有实例

启动脚本通过 Python 入口统一执行：识别同一工程目录中以 `python -m paperreader` 启动的旧进程，先请求终止，3 秒未退出再强制结束，确认退出后启动新窗口。不会按 Python 进程名批量结束其他程序。同时启动的重复请求由启动锁拦截。macOS 收到终止信号时尝试保存笔记；Windows 终止和超时强杀无法保证保存尚未落盘的内容，后台 AI 请求可能被中断。升级前启动的旧版本未包含保存信号处理，只能保留已自动保存内容。新增 psutil 依赖，旧环境先重跑安装脚本。

安装脚本统一读取根目录 requirements.txt，包含公式渲染依赖 matplotlib。安装完成后执行 pip check，依赖不兼容则报告失败。
# GitHub 发布流水线

`.github/workflows/build-macos.yml` 与 `.github/workflows/build-windows.yml` 分别在 macOS arm64 和 Windows x64 Runner 上构建应用。两条流水线均可从 GitHub Actions 手动运行，手动运行只生成可下载的 Actions Artifact。

推送 `v*` 版本标签时，两条流水线独立运行；构建和打包应用自检通过后，分别把 ZIP 上传为 Actions Artifact，并附加到同名 GitHub Release。两个 ZIP 共享一个版本标签与 Release，分别下载使用。macOS 构建使用 `build-macos.command`，Windows 构建使用 `build-windows.bat`。

发布命令示例：

```bash
git tag v0.1.0
git push origin v0.1.0
```

若任何一条流水线失败，不应将缺失平台的 Release 视为完整发布；先查看对应 Actions 日志并重跑失败任务。发布包未做 Apple 公证或 Windows 代码签名。
