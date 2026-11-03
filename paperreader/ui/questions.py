"""Centered question markers, horizontally scrollable without a visible scrollbar."""
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtWidgets import QScrollArea, QWidget, QHBoxLayout, QPushButton


class QuestionNavigation(QScrollArea):
    selected = Signal(int)
    contextRequested = Signal(int, QPoint)

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(32)
        self.setMinimumWidth(20)
        self.items = []; self.current = -1
        self.viewport().installEventFilter(self)
        content = QWidget(); self.row = QHBoxLayout(content)
        self.row.setContentsMargins(0, 0, 0, 0); self.row.setSpacing(2)
        self.row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWidget(content)

    def update_questions(self, questions):
        if questions == self.items: return
        self.items = list(questions); self.current = len(questions)-1
        while self.row.count():
            item = self.row.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for index, text in enumerate(questions):
            button = QPushButton('●' if index == self.current else '·')
            button.setObjectName('QuestionMarker'); button.setFixedSize(22, 28)
            button.setToolTip(f'问题 {index+1}：{text}')
            button.setAccessibleName(f'跳到问题 {index+1}：{text}')
            button.clicked.connect(lambda _, i=index: self.choose(i))
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(lambda pos, i=index, b=button: self.contextRequested.emit(i, b.mapToGlobal(pos)))
            self.row.addWidget(button)
        self.widget().setMinimumWidth(max(0, len(questions)*24))

    def choose(self, index):
        self.current = index
        for i in range(self.row.count()): self.row.itemAt(i).widget().setText('●' if i == index else '·')
        self.ensureWidgetVisible(self.row.itemAt(index).widget(), 8, 0)
        self.selected.emit(index)

    def wheelEvent(self, event):
        pixels, angles = event.pixelDelta(), event.angleDelta()
        delta = pixels.x() or pixels.y() or angles.x() or angles.y()
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value()-delta)
        event.accept()
