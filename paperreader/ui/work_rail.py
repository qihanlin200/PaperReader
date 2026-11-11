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
    elif symbol == 'folder':
        folder = QPainterPath(QPointF(2, 7))
        folder.lineTo(10, 7); folder.lineTo(13, 10); folder.lineTo(24, 10)
        folder.lineTo(24, 21); folder.lineTo(2, 21); folder.closeSubpath()
        painter.drawPath(folder)
    elif symbol in ('document', 'text'):
        page = QPainterPath(QPointF(5, 2))
        page.lineTo(15, 2); page.lineTo(21, 8); page.lineTo(21, 24)
        page.lineTo(5, 24); page.closeSubpath()
        page.moveTo(15, 2); page.lineTo(15, 8); page.lineTo(21, 8)
        painter.drawPath(page)
        painter.drawLine(8, 13, 18, 13)
        painter.drawLine(8, 17, 18 if symbol == 'text' else 14, 17)
    elif symbol == 'discussion':
        bubble = QPainterPath(QPointF(4, 3))
        bubble.lineTo(22, 3); bubble.lineTo(24, 5); bubble.lineTo(24, 16)
        bubble.lineTo(22, 18); bubble.lineTo(11, 18); bubble.lineTo(5, 23)
        bubble.lineTo(5, 18); bubble.lineTo(2, 16); bubble.lineTo(2, 5)
        bubble.closeSubpath()
        painter.drawPath(bubble)
        painter.drawLine(7, 8, 19, 8); painter.drawLine(7, 13, 16, 13)
    elif symbol == 'matrix':
        painter.drawRoundedRect(QRectF(3, 3, 20, 20), 3, 3)
        painter.drawLine(3, 10, 23, 10)
        painter.drawLine(3, 16, 23, 16)
        painter.drawLine(11, 3, 11, 23)
    elif symbol == 'flow':
        painter.drawLine(13, 8, 13, 13)
        painter.drawLine(5, 13, 21, 13)
        painter.drawLine(5, 13, 5, 18); painter.drawLine(21, 13, 21, 18)
        for x, y in ((13, 5), (5, 21), (21, 21)):
            painter.drawEllipse(QPointF(x, y), 3, 3)
    elif symbol == 'pulse':
        pulse = QPainterPath(QPointF(2, 13))
        for x, y in ((8, 13), (11, 5), (15, 21), (18, 11), (21, 14), (24, 14)):
            pulse.lineTo(x, y)
        painter.drawPath(pulse)
    elif symbol == 'clipboard':
        painter.drawRoundedRect(QRectF(5, 5, 16, 19), 2, 2)
        painter.drawRoundedRect(QRectF(9, 2, 8, 6), 2, 2)
        for y in (12, 16, 20):
            painter.drawLine(9, y, 17, y)
    elif symbol == 'shield':
        shield = QPainterPath(QPointF(13, 2))
        shield.lineTo(22, 6); shield.lineTo(21, 15)
        shield.quadTo(19, 21, 13, 24); shield.quadTo(7, 21, 5, 15)
        shield.lineTo(4, 6); shield.closeSubpath()
        painter.drawPath(shield)
        painter.drawLine(9, 13, 12, 16); painter.drawLine(12, 16, 17, 10)
    elif symbol == 'download':
        painter.drawLine(13, 3, 13, 16)
        painter.drawLine(8, 11, 13, 16); painter.drawLine(13, 16, 18, 11)
        tray = QPainterPath(QPointF(4, 15))
        tray.lineTo(4, 22); tray.lineTo(22, 22); tray.lineTo(22, 15)
        painter.drawPath(tray)
    elif symbol == 'question':
        painter.drawEllipse(QRectF(2, 2, 22, 22))
        curve = QPainterPath(QPointF(9, 9))
        curve.cubicTo(9, 4, 18, 5, 17, 10)
        curve.cubicTo(17, 13, 13, 13, 13, 16)
        painter.drawPath(curve)
        painter.drawPoint(13, 20)
    elif symbol == 'info':
        painter.drawEllipse(QRectF(3, 3, 20, 20))
        painter.drawPoint(13, 8)
        painter.drawLine(13, 12, 13, 18)
    elif symbol == 'trace':
        painter.drawArc(QRectF(3, 3, 20, 20), 20 * 16, 300 * 16)
        painter.drawLine(13, 7, 13, 13); painter.drawLine(13, 13, 18, 15)
        painter.drawLine(3, 11, 3, 4); painter.drawLine(3, 11, 9, 11)
    elif symbol == 'target':
        painter.drawEllipse(QPointF(12, 14), 9, 9)
        painter.drawEllipse(QPointF(12, 14), 4, 4)
        painter.drawLine(12, 14, 23, 3)
        painter.drawLine(23, 3, 23, 8); painter.drawLine(23, 3, 18, 3)
    elif symbol == 'edit':
        pencil = QPainterPath(QPointF(4, 22))
        pencil.lineTo(5, 16); pencil.lineTo(17, 4); pencil.lineTo(22, 9)
        pencil.lineTo(10, 21); pencil.closeSubpath()
        painter.drawPath(pencil)
        painter.drawLine(15, 6, 20, 11)
    elif symbol == 'eraser':
        eraser = QPainterPath(QPointF(4, 16))
        eraser.lineTo(15, 5); eraser.lineTo(22, 12); eraser.lineTo(12, 22)
        eraser.lineTo(10, 22); eraser.closeSubpath()
        painter.drawPath(eraser)
        painter.drawLine(9, 11, 16, 18)
        painter.drawLine(12, 22, 23, 22)
    elif symbol == 'trash':
        painter.drawLine(4, 6, 22, 6)
        painter.drawLine(10, 3, 16, 3)
        painter.drawRoundedRect(QRectF(7, 6, 12, 17), 2, 2)
        painter.drawLine(11, 10, 11, 19); painter.drawLine(15, 10, 15, 19)
    elif symbol == 'research':
        painter.drawEllipse(QRectF(7, 3, 16, 16))
        painter.drawLine(9, 17, 3, 23)
        star = QPainterPath(QPointF(15, 7))
        for point in ((16.2, 9.8), (19, 11), (16.2, 12.2), (15, 15),
                      (13.8, 12.2), (11, 11), (13.8, 9.8)):
            star.lineTo(*point)
        star.closeSubpath()
        painter.drawPath(star)
    elif symbol == 'settings':
        center = QPointF(13, 13)
        painter.drawEllipse(center, 7, 7)
        painter.drawEllipse(center, 2.5, 2.5)
        for index in range(8):
            angle = index * pi / 4
            painter.drawLine(QPointF(13 + 8 * cos(angle), 13 + 8 * sin(angle)),
                             QPointF(13 + 11 * cos(angle), 13 + 11 * sin(angle)))


def menu_symbol_icon(symbol, *, color="#a6b8ce", size=26):
    """Use the same theme-colored artwork in menus and the fixed rail."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 26, size / 26)
    draw_symbol(painter, symbol, QColor(theme_color(color)))
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
