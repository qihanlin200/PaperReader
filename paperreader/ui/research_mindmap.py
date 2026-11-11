"""Interactive canvas for a hierarchical research mind map."""
from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QTextOption
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from paperreader.ui.theme import theme_color


@dataclass
class Branch:
    text: object
    width: float
    height: float
    children: list = field(default_factory=list)
    span: float = 0
    key: tuple = ()
    expandable: bool = False


class MindmapCanvas(QGraphicsView):
    MIN_NODE_WIDTH = 112
    MAX_NODE_WIDTH = 280
    TEXT_PADDING = 10
    TOGGLE_SIZE = 18
    TOGGLE_GAP = 5
    COLUMN_GAP = 66
    ROW_GAP = 17

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setObjectName("ResearchMindmapCanvas")
        self.setAccessibleName("完整思维脑图")
        self.root = None
        self.collapsed = set()
        self.pressed_node = None

    def set_mindmap(self, root):
        if root is self.root:
            return
        self.root = root
        self.collapsed.clear()
        self.rebuild()
        self.reset_view()

    def rebuild(self):
        root = self.root
        scene = self.scene()
        scene.clear()
        scene.setBackgroundBrush(QColor(theme_color("#101824")))
        if not root:
            scene.setSceneRect(QRectF())
            return
        center = self.measure(root, center=True)
        groups = (center.children[::2], center.children[1::2])
        center_rect = QRectF(-center.width / 2, -center.height / 2, center.width, center.height)
        for direction, branches in zip((-1, 1), groups):
            total = self.group_span(branches)
            y = -total / 2
            for branch in branches:
                self.draw_branch(branch, center_rect, direction, y)
                y += branch.span + self.ROW_GAP
        self.draw_node(center, center_rect, 0)
        scene.setSceneRect(scene.itemsBoundingRect().adjusted(-28, -28, 28, 28))

    def group_span(self, branches):
        return sum(branch.span for branch in branches) + self.ROW_GAP * max(0, len(branches) - 1)

    def measure(self, node, *, center=False, key=()):
        expandable = bool(node["children"])
        label = self.scene().addText(node["label"])
        font = QFont(self.font())
        font.setBold(center)
        label.setFont(font)
        document = label.document()
        option = document.defaultTextOption()
        option.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        document.setDefaultTextOption(option)
        width = max(self.MIN_NODE_WIDTH, min(self.MAX_NODE_WIDTH,
                                            label.boundingRect().width() + 2 * self.TEXT_PADDING))
        label.setTextWidth(width - 2 * self.TEXT_PADDING)
        height = max(42, label.boundingRect().height() + 8)
        children = [] if key in self.collapsed else [
            self.measure(child, key=key + (index,)) for index, child in enumerate(node["children"])
        ]
        branch = Branch(label, width, height, children, key=key, expandable=expandable)
        branch.span = max(height, self.group_span(branch.children))
        return branch

    def draw_branch(self, branch, parent, direction, top, depth=1):
        x = parent.right() + self.COLUMN_GAP if direction > 0 else parent.left() - self.COLUMN_GAP - branch.width
        rect = QRectF(x, top + (branch.span - branch.height) / 2, branch.width, branch.height)
        start = QPointF(parent.right() if direction > 0 else parent.left(), parent.center().y())
        end = QPointF(rect.left() if direction > 0 else rect.right(), rect.center().y())
        middle = (start.x() + end.x()) / 2
        path = QPainterPath(start)
        path.lineTo(middle, start.y())
        path.lineTo(middle, end.y())
        path.lineTo(end)
        edge = self.scene().addPath(path, QPen(QColor(theme_color("#66ddda" if depth == 1 else "#64768d")), 1.5))
        edge.setZValue(-1)
        self.draw_node(branch, rect, depth)
        y = top + (branch.span - self.group_span(branch.children)) / 2
        for child in branch.children:
            self.draw_branch(child, rect, direction, y, depth + 1)
            y += child.span + self.ROW_GAP

    def draw_node(self, node, rect, depth):
        shape = QPainterPath()
        shape.addRoundedRect(rect, 12, 12)
        outline = QColor(theme_color("#66ddda" if depth == 0 else "#3c7180"))
        fill = QColor(theme_color("#17313c" if depth == 0 else "#223146"))
        scene = self.scene()
        scene.addPath(shape, QPen(outline, 2 if depth == 0 else 1), fill)
        if node.expandable:
            size = self.TOGGLE_SIZE
            x = rect.right() + self.TOGGLE_GAP
            y = rect.center().y() - size / 2
            control = scene.addEllipse(x, y, size, size, QPen(outline), fill)
            control.setZValue(2)
            control.setData(0, list(node.key))
            control.setCursor(Qt.CursorShape.PointingHandCursor)
            collapsed = node.key in self.collapsed
            control.setToolTip("点击展开" if collapsed else "点击折叠")
            pen = QPen(QColor(theme_color("#e4ebf5")), 1.4)
            glyph = scene.addLine(x + 5, y + size / 2, x + size - 5, y + size / 2, pen)
            glyph.setParentItem(control)
            if collapsed:
                glyph = scene.addLine(x + size / 2, y + 5, x + size / 2, y + size - 5, pen)
                glyph.setParentItem(control)
        node.text.setDefaultTextColor(QColor(theme_color("#e4ebf5")))
        node.text.setPos(rect.left() + self.TEXT_PADDING, rect.center().y() - node.text.boundingRect().height() / 2)
        node.text.setZValue(1)

    def zoom(self, factor):
        scale = self.transform().m11()
        if .18 <= scale * factor <= 3:
            self.scale(factor, factor)

    def reset_view(self):
        self.resetTransform()
        if not self.root:
            return
        bounds = self.sceneRect()
        factor = min(1, self.viewport().width() / bounds.width(), self.viewport().height() / bounds.height())
        self.scale(max(.55, factor), max(.55, factor))
        self.centerOn(0, 0)

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.NativeGesture:
            if event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
                position = event.position().toPoint()
                before = self.mapToScene(position)
                self.zoom(1 + event.value())
                offset = self.mapToScene(position) - before
                self.translate(offset.x(), offset.y())
                event.accept()
                return True
        return super().viewportEvent(event)

    def wheelEvent(self, event):
        delta = event.pixelDelta()
        if delta.isNull():
            delta = event.angleDelta() / 3
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
        event.accept()

    def node_at(self, position):
        for item in self.items(position):
            key = item.data(0)
            if key is not None:
                return tuple(key)
        return None

    def mousePressEvent(self, event):
        self.pressed_node = None
        if event.button() == Qt.MouseButton.LeftButton:
            position = event.position().toPoint()
            key = self.node_at(position)
            if key is not None:
                self.pressed_node = key, position
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        pressed = self.pressed_node
        self.pressed_node = None
        super().mouseReleaseEvent(event)
        if not pressed or event.button() != Qt.MouseButton.LeftButton:
            return
        key, start = pressed
        position = event.position().toPoint()
        if (position - start).manhattanLength() > 4 or self.node_at(position) != key:
            return
        center = self.mapToScene(self.viewport().rect().center())
        if key in self.collapsed:
            self.collapsed.remove(key)
        else:
            self.collapsed.add(key)
        self.rebuild()
        self.centerOn(center)
