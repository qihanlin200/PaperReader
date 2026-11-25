"""Application typography settings; PDF page rendering is intentionally separate."""

import re
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QComboBox, QLineEdit, QTabBar, QWidget,
)


FONT_OPTIONS = (
    ("system", "跟随系统", None),
    ("source-han-sans", "思源黑体 SC", "SourceHanSansSC-Regular.otf"),
    ("sarasa-ui", "更纱黑体 UI SC", "SarasaUI-SC-Regular.ttf"),
    ("source-han-serif", "思源宋体 SC", "SourceHanSerifSC-Regular.otf"),
    ("lxgw-wenkai", "霞鹜文楷屏幕阅读版", "LXGWWenKaiScreen.ttf"),
)
SIZE_OPTIONS = (
    ("standard", "标准 · 14 寸及以下", 1.0),
    ("medium", "中号 · 约 24 寸", 1.15),
    ("large", "大号 · 约 27 寸", 1.30),
    ("extra-large", "超大号 · 34 寸及以上", 1.50),
)
_FONT_FILES = {key: filename for key, _, filename in FONT_OPTIONS}
_SCALES = {key: scale for key, _, scale in SIZE_OPTIONS}
_CSS_SIZE = re.compile(r"(font-size\s*:\s*)(\d+(?:\.\d+)?)(px|pt)", re.I)
_loaded_families = {}
_system_font = None


def valid_font(value):
    return value if value in _FONT_FILES else "system"


def valid_size(value):
    return value if value in _SCALES else "standard"


def scale_factor():
    app = QApplication.instance()
    return _SCALES.get(app.property("paperreaderFontSize") if app else None, 1.0)


def pixels(value):
    return max(1, round(value * scale_factor()))


def scale_stylesheet(css):
    factor = scale_factor()
    if factor == 1:
        return css
    return _CSS_SIZE.sub(
        lambda match: f"{match[1]}{max(1, round(float(match[2]) * factor))}{match[3]}", css
    )


def current_family():
    app = QApplication.instance()
    return app.property("paperreaderFontFamily") if app else None


def apply_font(font_key="system", size_key="standard"):
    """Register only a selected font and update the inherited Qt font."""
    global _system_font
    app = QApplication.instance()
    if app is None:
        return
    if _system_font is None:
        _system_font = QFont(app.font())
    font_key, size_key = valid_font(font_key), valid_size(size_key)
    family = None
    filename = _FONT_FILES[font_key]
    if filename:
        if font_key not in _loaded_families:
            path = Path(__file__).resolve().parent.parent / "assets" / "fonts" / filename
            font_id = QFontDatabase.addApplicationFont(str(path))
            families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
            if not families:
                raise RuntimeError(f"无法加载字体文件：{filename}")
            _loaded_families[font_key] = families[0]
        family = _loaded_families[font_key]
    app.setProperty("paperreaderFontSize", size_key)
    app.setProperty("paperreaderFontFamily", family)
    font = QFont(_system_font)
    if family:
        font.setFamily(family)
    font.setPointSize(max(1, round(11 * _SCALES[size_key])))
    app.setFont(font)


def resize_fixed_text_controls(root):
    """Give fixed-height text controls room when a larger reading size is chosen."""
    factor = scale_factor()
    for widget in root.findChildren(QWidget):
        baseline = widget.property("paperreaderBaseHeight")
        if baseline is None and widget.maximumHeight() - widget.minimumHeight() > 2:
            continue
        if baseline is None and widget.height() < 24:
            continue
        has_text = (
            isinstance(widget, QAbstractButton) and bool(widget.text())
            and widget.objectName() != "QuestionMarker"
            or isinstance(widget, (QComboBox, QLineEdit, QTabBar))
            or widget.objectName() == "PanelHeader"
            or widget is getattr(root, "top_bar", None)
        )
        if not has_text:
            continue
        if baseline is None:
            baseline = widget.height()
            widget.setProperty("paperreaderBaseHeight", baseline)
        widget.setFixedHeight(round(baseline * factor))
