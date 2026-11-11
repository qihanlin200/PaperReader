"""Reveal scrollbars only while the pointer is inside their scroll area."""
import weakref
from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QAbstractScrollArea, QGraphicsOpacityEffect, QWidget


class HoverScrollbars(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.areas = weakref.WeakSet()
        self.active = None
        # A Python application event filter receives Chromium's internal QObject
        # construction events before PySide can safely wrap those objects.
        self.timer = QTimer(self)
        self.timer.setInterval(80)
        self.timer.timeout.connect(self.refresh_pointer)
        self.timer.start()

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
        window = QApplication.activeWindow()
        if window is not None:
            for area in window.findChildren(QAbstractScrollArea):
                if area.isVisible():
                    self.register(area)
        area = self.owner(QApplication.widgetAt(QCursor.pos())) if window is not None else None
        if area is not None:
            self.register(area)
        if area is not self.active:
            self.set_active(area)


def install_hover_scrollbars(app):
    if not hasattr(app, '_paperreader_hover_scrollbars'):
        app._paperreader_hover_scrollbars = HoverScrollbars(app)
    return app._paperreader_hover_scrollbars
