"""Compact, theme-aware view preset buttons for the status bar."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QToolButton

from paperreader.ui.theme import theme_color


class ViewModeButton(QToolButton):
    def __init__(self, panels, title, parent=None):
        super().__init__(parent)
        self.panels = panels
        self.setCheckable(True)
        self.setFixedSize(38, 25)
        self.setToolTip(title)
        self.setAccessibleName(title)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = self.isChecked()
        hovered = self.underMouse()
        background = '#305663' if selected else '#101824'
        border = '#66ddda' if selected or hovered else '#567089'
        ink = '#eaf4ff' if selected else '#91aabd'
        painter.setPen(QPen(QColor(theme_color(border)), 1))
        painter.setBrush(QColor(theme_color(background)))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 5, 5)

        frame = self.rect().adjusted(6, 6, -6, -6)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(theme_color(ink)), 1.4))
        painter.drawRoundedRect(frame, 2, 2)
        if self.panels == 4:
            fractions = (0.16, 0.45, 0.73)
        elif self.panels == 3:
            fractions = (0.20, 0.60)
        else:
            fractions = (0.50,)
        for fraction in fractions:
            x = round(frame.left() + frame.width() * fraction)
            painter.drawLine(x, frame.top() + 1, x, frame.bottom() - 1)
        if self.panels == 3:
            painter.drawLine(frame.left() + 2, frame.top() + 3,
                             frame.left() + 2, frame.bottom() - 3)
