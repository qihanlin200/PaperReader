# macOS 应用包

## 运行

解压 `dist/PaperReader-macOS-arm64.zip`，将 `PaperReader.app` 拖到“应用程序”或其他可写目录，双击启动，不需要另装 Python 或第三方库。当前版本针对 Apple Silicon（M 系列）、macOS 13 或更新系统构建；未在 macOS 13 实机验证，Intel Mac 不适用。

这是本地自用构建，采用临时签名，没有 Apple Developer ID 签名及公证。跨设备下载时 macOS 可能阻止打开，需按系统提示自行确认信任；不自动绕过 Gatekeeper。若需正式分发，后续应增加 Developer ID 签名、公证及 Intel/通用构建。

模型配置、密钥和学习资料不包含在应用内。运行时沿用系统应用数据目录与钥匙串，现有用户资料可继续使用。新机器需自行设置模型接口和密钥。

## 重建

在 Apple Silicon Mac 安装 Python，然后双击根目录 `build-macos.command`。它创建/使用 `.venv`，安装 `requirements-build.txt`，使用 `PaperReader.spec` 构建 `.app` 并生成 ZIP。打包依赖与运行依赖分开维护。

- `PaperReader.spec`：包含程序、Qt、PDF、MathText、系统密钥库后端和应用图标，排除未使用的 WebEngine。
- `requirements-build.txt`：运行依赖 + PyInstaller。
- `build/` 与 `dist/`：构建产物，已加入 Git 忽略。
- `.app/Contents/MacOS/PaperReader --smoke-test`：使用临时资料库测试窗口、PDF、公式及图标，不读取实际学习记录。

打包应用只重启相同可执行文件路径的旧实例；开发版启动脚本仍按工程路径匹配 Python 进程。不同位置复制出的应用不保证互斥。
