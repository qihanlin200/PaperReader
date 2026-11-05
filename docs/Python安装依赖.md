# Python 安装与依赖

## 环境

建议 Python 3.11（64 位）。macOS 和 Windows 都需要支持当前 PySide6 二进制包的系统版本和架构；旧系统安装失败时先检查 PySide6 wheel 兼容性，不承诺所有历史系统可用。安装脚本不负责安装 Python 本身。

## 依赖清单

版本范围统一在根目录 `requirements.txt` 维护。

| 库 | 用途 |
| --- | --- |
| PySide6 >=6.6,<7 | 跨平台 Qt 桌面界面、线程任务及图像显示 |
| PyMuPDF >=1.24,<2 | PDF 校验、渲染、提取单词及页面文本 |
| httpx >=0.27,<1 | PDF 下载及云端模型 HTTP 请求 |
| platformdirs >=4,<5 | 跨平台本地应用数据目录 |
| keyring >=25,<26 | 系统密钥库保存 API Key |
| psutil >=6,<8 | 精确识别本工程实例、终止并等待旧进程退出 |
| matplotlib >=3.8,<4 | MathText 本地数学公式渲染，无需 LaTeX 程序或联网 |

sqlite3、json、unittest 等使用 Python 标准库。PyMuPDF 存在 AGPL/商业许可选项，若未来分发产品，应确认适用许可。

## 一键安装

macOS：在工程目录执行 `./install.command`。Windows：双击 `install.bat`。脚本创建 `.venv`，升级虚拟环境内 pip，然后安装 requirements。安装失败时不会打印“安装完成”，可解决网络/版本问题后重跑。

## 手动安装

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m paperreader
```

Windows 对应：

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m paperreader
```

## 故障排查

- 无 Python 命令：先安装 Python，Windows 确保存在 `py` 启动器。
- 下载失败：检查网络或按所在网络要求配置 pip 镜像，然后重跑安装脚本。
- 找不到兼容版本：检查 Python 版本、CPU 架构和操作系统；建议 Python 3.11 64 位。
- Keyring 失败：检查系统钥匙串/凭据服务权限；应用不会将密钥回退保存为明文。
- API 失败：地址需要是 API 基础地址，而非网页聊天地址或完整 `/chat/completions` 路径。

当前使用版本范围而非跨平台统一锁文件；不同 Python 版本可能解析出不同的兼容版本。发布前需在两端固定并验证依赖版本。

## 更新已有环境

新增的 `matplotlib>=3.8,<4` 已统一纳入 requirements.txt，两个安装脚本均自动安装，无需单独执行 pip install matplotlib。其 NumPy、Pillow 等间接依赖由 pip 自动解析安装。旧环境重新运行 install.command 或 install.bat 即可补齐，脚本随后执行 pip check 验证依赖兼容性。这里只提供联网一键安装，不是离线依赖包。

## 打包依赖

`requirements-build.txt` 引用运行依赖并添加 `pyinstaller>=6.11,<7`。macOS 一键构建脚本为根目录 build-macos.command，生成可独立运行的 .app 与 ZIP；普通源码运行只需 requirements.txt。
