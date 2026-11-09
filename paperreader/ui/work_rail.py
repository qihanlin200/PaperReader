"""Fixed, theme-aware icon rail beside the resizable reading panes."""
from math import cos, pi, sin

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QToolButton

from paperreader.ui.theme import theme_color


def draw_symbol(painter, symbol, color):
    painter.setPen(QPen(color, 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                        Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if symbol == 'pdf':
        page = QPainterPath(QPointF(5, 2))
        page.lineTo(16, 2); page.lineTo(21, 7); page.lineTo(21, 18)
        page.moveTo(16, 2); page.lineTo(16, 7); page.lineTo(21, 7)
        page.moveTo(5, 2); page.lineTo(5, 23); page.lineTo(15, 23)
        painter.drawPath(page)
        painter.drawLine(8, 11, 15, 11); painter.drawLine(8, 15, 13, 15)
        painter.drawEllipse(QRectF(14, 16, 10, 10))
        painter.drawLine(19, 18.5, 19, 23.5); painter.drawLine(16.5, 21, 21.5, 21)
    elif symbol == 'link':
        painter.save()
        painter.translate(13, 13); painter.rotate(-42)
        painter.drawRoundedRect(QRectF(-11, -4, 13, 8), 4, 4)
        painter.drawRoundedRect(QRectF(-2, -4, 13, 8), 4, 4)
        painter.restore()
    elif symbol == 'group':
        folder = QPainterPath(QPointF(2, 7))
        folder.lineTo(10, 7); folder.lineTo(12, 10); folder.lineTo(24, 10)
        folder.lineTo(24, 22); folder.lineTo(2, 22); folder.closeSubpath()
        painter.drawPath(folder)
        painter.drawLine(13, 13, 13, 19)
        painter.drawLine(10, 16, 16, 16)
    elif symbol == 'library':
        book = QPainterPath(QPointF(13, 6))
        book.cubicTo(9, 3, 5, 3, 2, 5)
        book.lineTo(2, 20); book.cubicTo(6, 18, 10, 19, 13, 22)
        book.cubicTo(16, 19, 20, 18, 24, 20)
        book.lineTo(24, 5); book.cubicTo(20, 3, 17, 3, 13, 6)
        book.closeSubpath()
        painter.drawPath(book)
        painter.drawLine(13, 6, 13, 22)
    elif symbol == 'settings':
        center = QPointF(13, 13)
        painter.drawEllipse(center, 7, 7)
        painter.drawEllipse(center, 2.5, 2.5)
        for index in range(8):
            angle = index * pi / 4
            painter.drawLine(QPointF(13 + 8 * cos(angle), 13 + 8 * sin(angle)),
                             QPointF(13 + 11 * cos(angle), 13 + 11 * sin(angle)))


def menu_symbol_icon(symbol):
    """Use the same theme-colored artwork in menus and the fixed rail."""
    pixmap = QPixmap(26, 26)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_symbol(painter, symbol, QColor(theme_color('#a6b8ce')))
    painter.end()
    return QIcon(pixmap)


class WorkRailButton(QToolButton):
    ICON_SIZE = 21

    def __init__(self, symbol, label, parent=None):
        super().__init__(parent)
        self.symbol = symbol
        self.setObjectName("WorkRailButton")
        self.setFixedSize(38, 38)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(label)
        self.setAccessibleName(label)
        self.setProperty("active", False)

    def set_active(self, active):
        if self.property("active") == active:
            return
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate((self.width() - self.ICON_SIZE) / 2,
                          (self.height() - self.ICON_SIZE) / 2)
        painter.scale(self.ICON_SIZE / 26, self.ICON_SIZE / 26)
        draw_symbol(painter, self.symbol,
                    QColor(theme_color('#66ddda' if self.property('active') else '#a6b8ce')))
        painter.end()
