# 主窗口功能模块

`Window` 在 `paperreader/ui/window.py` 中组装主界面并协调阅读主流程。以下模块以 mixin 形式提供原有窗口方法，保持信号连接和调用入口不变：

- `papers/`：论文导入、列表、分组、收藏、打开与移除。
- `pdf_reading/`：PDF 页码、缩放、全屏、校准及原文跳转。
- `followup/`：追问请求、证据检索和流式回答。
- `sessions_notes/`：会话历史、回答显示、笔记、批注和导出。
- `themes/`：主题切换、主题资源及设置入口。
- `jobs.py`：主窗口和设置界面共用的后台 Qt 任务包装。

追问指令放在 `paperreader/ui/prompts/followup.py`。各模块通过 `self` 使用主窗口已经建立的控件和状态；新建窗口控件及阅读分析主流程仍由 `Window` 管理。
