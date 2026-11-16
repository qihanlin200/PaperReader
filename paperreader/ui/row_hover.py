"""Theme-aware hover animation shared by list rows."""
from PySide6.QtCore import QEasingCurve, QEvent, QPersistentModelIndex, QRectF, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from paperreader.ui.theme import theme_color


class RowHoverDelegate(QStyledItemDelegate):
    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.current = QPersistentModelIndex()
        self.previous = QPersistentModelIndex()
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(160)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(lambda _: view.viewport().update())
        view.viewport().installEventFilter(self)
        view.viewport().setMouseTracking(True)

    def eventFilter(self, watched, event):
        index = self.current
        if event.type() == QEvent.Type.MouseMove:
            index = QPersistentModelIndex(self.view.indexAt(event.position().toPoint()))
        elif event.type() == QEvent.Type.Leave:
            index = QPersistentModelIndex()
        if index != self.current:
            self.previous, self.current = self.current, index
            self.animation.stop()
            self.animation.start()
        return super().eventFilter(watched, event)

    def paint(self, painter, option, index):
        option.state &= ~QStyle.StateFlag.State_MouseOver
        super().paint(painter, option, index)
        self.paint_highlight(painter, option, index)

    def paint_highlight(self, painter, option, index):
        progress = self.animation.currentValue()
        opacity = progress if self.current == index else 1 - progress if self.previous == index else 0
        if opacity <= 0:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = QColor(theme_color("#66ddda"))
        accent.setAlphaF(0.7 * opacity)
        painter.setPen(QPen(accent, 1))
        tint = QColor(accent)
        tint.setAlphaF(0.08 * opacity)
        painter.setBrush(tint)
        painter.drawRoundedRect(QRectF(option.rect).adjusted(1, 1, -1, -1), 5, 5)
        painter.restore()
