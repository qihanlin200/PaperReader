# PaperReader 应用图标

选用方案一「书本星芒」。深蓝灰底、银青色书页、青色 AI 星芒，与深色工作台一致。

- `app-icon-source.png`：内置图像生成工具生成的原始图片，保留透明背景。
- `icon-16.png` 至 `icon-1024.png`：应用使用的多尺寸 PNG。
- `PaperReader.icns`：macOS 图标，供后续应用打包使用。
- `PaperReader.ico`：Windows 多尺寸图标，供后续应用打包使用。

应用入口通过 QApplication.setWindowIcon 设置 PNG，主窗口继承该图标，macOS 运行时程序坞由 Qt 提供。尚未构建独立 .app 或 Windows 安装包；未来打包需同时在 bundle/可执行文件资源中配置图标。

生成方式：内置 image_gen，未使用 API CLI。

提示词：为个人论文 AI 阅读器 PaperReader 制作 macOS Dock 图标；深蓝灰 #0b1019/#101824 圆角方块，银青色打开的书本，中央上方一颗青色 #66ddda 四角 AI 星芒，克制的立体材质与柔和边缘光，小尺寸清晰，无文字、无水印，图标外背景透明。

`dropdown-arrow.svg` 为界面模型选择器使用的原生矢量箭头，与应用图标无关。
