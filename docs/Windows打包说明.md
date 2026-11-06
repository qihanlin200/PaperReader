# Windows 便携版打包

在 64 位 Windows 上安装 Python 3.11（64 位），然后在工程根目录双击 `build-windows.bat`。首次构建会安装 `requirements-build.txt`，需要网络；后续可以复用 `.venv`。脚本使用 `PaperReader-windows.spec`，运行打包程序的离屏窗口、PDF 和公式冒烟检查，再生成 `dist/PaperReader-Windows-x64.zip`。

解压 ZIP 后，运行 `PaperReader/PaperReader.exe`。`PaperReader` 文件夹中的 `_internal` 及其他文件必须与 EXE 一起保留。用户的 PDF、笔记和模型配置保存在 Windows 用户资料目录中，API 密钥保存在 Windows 凭据管理器；打包产物不从这些目录收集个人数据。

GitHub Actions 的 `Build Windows app` 工作流在 Windows 环境中执行相同脚本，生成名为 `PaperReader-Windows-x64` 的构建产物，其中包含 ZIP。该包是便携版，不是安装器；暂未进行代码签名。首次运行时 Windows 可能显示未知发布者提示。

本地 macOS 构建不能生成可用的 Windows EXE。Windows 冒烟检查通过后，仍建议在目标 Windows 电脑上验证窗口交互、PDF 滚动与缩放、系统凭据存储和真实模型连接。
