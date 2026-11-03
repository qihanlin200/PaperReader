"""Click to collapse a pane; hold to resize without accidental collapse."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSplitter, QSplitterHandle


class PaneHandle(QSplitterHandle):
    HOLD_MS = 450

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.pressed = False
        self.dragging = False
        self.origin = None
        self.initial_position = 0
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(self.HOLD_MS)
        self.timer.timeout.connect(self.begin_drag)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("点击收起/展开左侧栏；Shift+点击操作右侧栏。长按 0.45 秒后拖动调整栏宽。")

    def index(self):
        splitter = self.splitter()
        return next(i for i in range(1, splitter.count()) if splitter.handle(i) is self)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore(); return
        self.pressed = True; self.dragging = False
        self.origin = event.globalPosition().toPoint()
        self.initial_position = self.pos().x()
        self.right_side = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        self.timer.start(); event.accept()

    def begin_drag(self):
        if self.pressed:
            self.dragging = True
            self.setCursor(Qt.CursorShape.SplitHCursor)
            self.update()

    def mouseMoveEvent(self, event):
        if self.pressed and self.dragging:
            delta = event.globalPosition().toPoint().x() - self.origin.x()
            self.moveSplitter(self.initial_position + delta)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self.pressed:
            event.ignore(); return
        self.timer.stop()
        if not self.dragging:
            # A quick drag is neither a click nor an intentional long-press resize.
            distance = (event.globalPosition().toPoint() - self.origin).manhattanLength()
            if distance <= 6:
                self.splitter().toggle(self.index() if self.right_side else self.index()-1)
        self.pressed = False; self.dragging = False
        self.setCursor(Qt.CursorShape.PointingHandCursor); self.update(); event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#284d59' if self.dragging else '#131e2b'))
        painter.setPen(QColor('#66ddda' if self.dragging else '#567089'))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '⋮')


class PaneSplitter(QSplitter):
    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setHandleWidth(14)
        self.setChildrenCollapsible(True)
        self.previous_widths = {}

    def createHandle(self):
        return PaneHandle(self.orientation(), self)

    def toggle(self, index):
        sizes = self.sizes()
        if not 0 <= index < len(sizes): return
        if sizes[index] > 0:
            if sum(size > 0 for size in sizes) <= 1: return
            self.previous_widths[index] = sizes[index]
            freed = sizes[index]; sizes[index] = 0
            recipient = next((i for i in range(index+1, len(sizes)) if sizes[i] > 0), None)
            if recipient is None:
                recipient = next(i for i in range(index-1, -1, -1) if sizes[i] > 0)
            sizes[recipient] += freed
        else:
            restored = self.previous_widths.get(index, 300)
            # Ask Qt to redistribute available space while retaining collapsed panes.
            sizes[index] = restored
        self.setSizes(sizes)
