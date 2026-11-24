# 测试

日常运行 `python scripts/run_tests.py`，默认只执行不创建 `QApplication` 的快速用例；修改桌面交互时运行 `python scripts/run_tests.py --suite qt`，视觉布局单独运行 `python scripts/run_tests.py --suite visual`，发布前运行 `python scripts/run_tests.py --suite all`。也可在命令后附上具体用例 ID。测试发现只解析源码，不导入 Qt。每个用例在独立进程中运行，默认限时 20 秒；超时后会结束该进程及其子进程，记录耗时并继续其他用例，最后列出最慢的五例。默认同时运行 2 例，可用 `--jobs 1` 串行排查，或用 `--timeout 30` 调整限时。测试使用临时资料库与生成的 PDF，不消耗真实模型费用。Qt 测试默认 offscreen，不能替代 macOS/Windows 人工交互验收。

`test_ui.py` 默认使用 offscreen 模式，验证 Markdown 编辑预览、问答和翻译流式界面，以及中断回答保存；不调用真实服务。
