"""Theme-aware breathing outline for active reading analysis."""
from PySide6.QtCore import QEasingCurve, QRectF, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from paperreader.ui.theme import theme_color


class AnalysisBreathingFrame(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AnalysisBreathingFrame")
        self.active = False
        self.phase = 0.0
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(2200)
        self.animation.setStartValue(0.0)
        self.animation.setKeyValueAt(0.5, 1.0)
        self.animation.setEndValue(0.0)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.animation.setLoopCount(-1)
        self.animation.valueChanged.connect(self._advance)

    def _advance(self, value):
        self.phase = float(value)
        self.update()

    def set_active(self, active):
        active = bool(active)
        if self.active == active:
            return
        self.active = active
        if active and self.isVisible():
            self.animation.start()
        else:
            self.animation.stop()
            self.phase = 0.0
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if self.active and self.animation.state() != QVariantAnimation.State.Running:
            self.animation.start()

    def hideEvent(self, event):
        self.animation.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.active:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = QColor(theme_color("#66ddda"))
        strength = 0.35 + 0.65 * self.phase
        for inset, width, opacity in ((0.8, 2.4, 0.16), (2.1, 2.0, 0.34), (3.4, 1.5, 0.82)):
            color = QColor(accent)
            color.setAlphaF(opacity * strength)
            painter.setPen(QPen(color, width))
            painter.setBrush(QColor(0, 0, 0, 0))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(inset, inset, -inset, -inset), 8, 8)
