"""Theme-aware progress nodes for the research workbench."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from paperreader.ui.theme import theme_color


class ResearchProgress(QWidget):
    STAGES = ("规划", "检索", "取证", "分析", "结论")

    def __init__(self):
        super().__init__()
        self.step = -1
        self.setFixedHeight(47)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName("研究进度")

    def set_step(self, step):
        self.step = step
        self.setAccessibleDescription(self.STAGES[step] if 0 <= step < len(self.STAGES) else "")
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cyan = QColor(theme_color("#66ddda"))
        muted = QColor(theme_color("#64768d"))
        foreground = QColor(theme_color("#e4ebf5"))
        background = QColor(theme_color("#101824"))
        spacing = self.width() / len(self.STAGES)
        y = 13
        points = [(i + .5) * spacing for i in range(len(self.STAGES))]
        painter.setPen(QPen(muted, 2))
        painter.drawLine(QPointF(points[0], y), QPointF(points[-1], y))
        if self.step >= 0:
            painter.setPen(QPen(cyan, 2))
            painter.drawLine(QPointF(points[0], y), QPointF(points[min(self.step, len(points) - 1)], y))
        for index, (x, label) in enumerate(zip(points, self.STAGES)):
            done, current = index < self.step, index == self.step
            painter.setPen(QPen(cyan if done or current else muted, 2))
            painter.setBrush(cyan if done else background)
            painter.drawEllipse(QPointF(x, y), 7, 7)
            if done:
                painter.setPen(QPen(background, 1.6))
                painter.drawLine(QPointF(x - 3, y), QPointF(x - 1, y + 2))
                painter.drawLine(QPointF(x - 1, y + 2), QPointF(x + 3, y - 3))
            elif current:
                painter.setBrush(cyan)
                painter.drawEllipse(QPointF(x, y), 3, 3)
            painter.setPen(cyan if current else foreground)
            painter.drawText(QRectF(x - spacing / 2, 25, spacing, 19), Qt.AlignmentFlag.AlignCenter, label)
