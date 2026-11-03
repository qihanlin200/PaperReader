# 测试

运行 `python -m unittest discover -s tests -v`。使用临时资料库与生成的 PDF，验证重复导入、记录恢复、来源识别及模拟模型 API；不消耗真实模型费用。窗口可用 Qt offscreen 冒烟测试，不能替代 macOS/Windows 人工交互验收。

`test_ui.py` 默认使用 offscreen 模式，验证 Markdown 编辑预览、问答和翻译流式界面，以及中断回答保存；不调用真实服务。
