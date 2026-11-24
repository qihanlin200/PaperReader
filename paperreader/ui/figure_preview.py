"""Full-screen, local-only preview of a cited PDF figure."""
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QDialog


class FigurePreview(QDialog):
    def __init__(self, image, label, parent=None):
        super().__init__(parent)
        self.image = image
        self.label = label or '论文原图'
        self.zoom_level = 1.0
        self.pan = QPointF()
        self.drag_at = None
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.grabGesture(Qt.GestureType.PinchGesture)
        screen = parent.screen() if parent is not None else self.screen()
        self.setGeometry(screen.geometry())

    def image_rect(self):
        fit = min((self.width() - 80) / max(1, self.image.width()),
                  (self.height() - 130) / max(1, self.image.height()))
        scale = max(.01, fit) * self.zoom_level
        width, height = self.image.width() * scale, self.image.height() * scale
        return QRectF((self.width() - width) / 2 + self.pan.x(),
                      (self.height() - height) / 2 + self.pan.y(), width, height)

    def zoom(self, factor, anchor=None):
        before = self.image_rect()
        new_level = max(.5, min(8, self.zoom_level * factor))
        if abs(new_level - self.zoom_level) < .0001:
            return
        anchor = anchor or QPointF(self.width() / 2, self.height() / 2)
        relative_x = (anchor.x() - before.x()) / max(1, before.width())
        relative_y = (anchor.y() - before.y()) / max(1, before.height())
        self.zoom_level = new_level
        after = self.image_rect()
        self.pan += QPointF(anchor.x() - after.x() - relative_x * after.width(),
                            anchor.y() - after.y() - relative_y * after.height())
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 225))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(self.image_rect(), self.image)
        painter.setPen(QColor('#f4f0e8'))
        painter.drawText(QRectF(30, self.height() - 54, self.width() - 60, 38),
                         Qt.AlignmentFlag.AlignCenter,
                         f'{self.label}  ·  双指缩放 / 拖动移动  ·  Esc 或点击图片外关闭')

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if not self.image_rect().contains(event.position()):
                self.reject()
            else:
                self.drag_at = event.position()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_at is not None:
            self.pan += event.position() - self.drag_at
            self.drag_at = event.position()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.drag_at = None
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.pixelDelta().y() or event.angleDelta().y()
            if delta:
                self.zoom(2 ** (delta / 480), event.position())
        else:
            self.pan += QPointF(event.pixelDelta().x(), event.pixelDelta().y())
            self.update()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def event(self, event):
        if event.type() == QEvent.Type.NativeGesture and event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
            self.zoom(max(.1, 1 + event.value()) ** 1.5,
                      self.mapFromGlobal(event.globalPosition().toPoint()).toPointF())
            event.accept()
            return True
        if event.type() == QEvent.Type.Gesture:
            pinch = event.gesture(Qt.GestureType.PinchGesture)
            if pinch:
                previous = pinch.lastScaleFactor()
                self.zoom((pinch.scaleFactor() / previous if previous else 1) ** 1.5,
                          pinch.centerPoint())
                event.accept()
                return True
        return super().event(event)
