"""Reveal scrollbars only while the pointer is inside their scroll area."""
import weakref
from PySide6.QtCore import QObject, QEvent, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QAbstractScrollArea, QGraphicsOpacityEffect, QWidget


class HoverScrollbars(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.areas = weakref.WeakSet()
        self.active = None
        app.installEventFilter(self)

    def register(self, area):
        if area in self.areas: return
        self.areas.add(area)
        for bar in (area.verticalScrollBar(), area.horizontalScrollBar()):
            effect = QGraphicsOpacityEffect(bar)
            effect.setOpacity(0)
            bar.setGraphicsEffect(effect)
        if area is self.active: self.set_active(area)

    def set_active(self, area):
        self.active = area
        for candidate in list(self.areas):
            try:
                for bar in (candidate.verticalScrollBar(), candidate.horizontalScrollBar()):
                    effect = bar.graphicsEffect()
                    if effect: effect.setOpacity(1 if candidate is area else 0)
            except RuntimeError:
                self.areas.discard(candidate)

    def owner(self, widget):
        while isinstance(widget, QWidget):
            if isinstance(widget, QAbstractScrollArea): return widget
            widget = widget.parentWidget()
        return None

    def refresh_pointer(self):
        self.set_active(self.owner(QApplication.widgetAt(QCursor.pos())))

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind in (QEvent.Type.Polish, QEvent.Type.Show) and isinstance(watched, QAbstractScrollArea):
            self.register(watched)
        elif kind == QEvent.Type.Enter and isinstance(watched, QWidget):
            area = self.owner(watched)
            if area: self.register(area)
            self.set_active(area)
        elif kind in (QEvent.Type.Leave, QEvent.Type.WindowDeactivate):
            QTimer.singleShot(0, self.refresh_pointer)
        return False


def install_hover_scrollbars(app):
    if not hasattr(app, '_paperreader_hover_scrollbars'):
        app._paperreader_hover_scrollbars = HoverScrollbars(app)
    return app._paperreader_hover_scrollbars
