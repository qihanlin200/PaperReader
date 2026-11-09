"""Paper list with a native favorite button at the end of each row."""
import json
import sys
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QMimeData, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QDrag, QIcon, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QToolButton, QWidget,
)


_STAR_SIZE = QSize(30, 26)
_STAR_MARGIN = 4
PAPER_ID_ROLE = Qt.ItemDataRole.UserRole
GROUP_ID_ROLE = Qt.ItemDataRole.UserRole + 1
PAPER_MIME = 'application/x-paperreader-paper-ids'
GROUP_MIME = 'application/x-paperreader-group-id'
MACOS = sys.platform == 'darwin'


class PaperRowDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setWidth(self.parent().viewport().width())
        return size

    def paint(self, painter, option, index):
        view = self.parent()
        row = QStyleOptionViewItem(option)
        self.initStyleOption(row, index)
        style = view.style()
        if index.data(GROUP_ID_ROLE) is not None:
            row.palette.setColor(QPalette.ColorRole.Text, row.palette.link().color())
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, row, painter, view)
            if index.row() == view.drop_target_row:
                painter.save()
                painter.setPen(QPen(row.palette.link().color(), 3 if view.drop_target_kind == 'group' else 2))
                if view.drop_target_kind == 'group':
                    y = row.rect.bottom() - 1 if view.drop_after else row.rect.top() + 1
                    painter.drawLine(row.rect.left() + 5, y, row.rect.right() - 5, y)
                else:
                    painter.drawRoundedRect(row.rect.adjusted(1, 1, -2, -2), 5, 5)
                painter.restore()
            return
        text_rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, row, view)
        title_width = max(0, text_rect.width() - _STAR_SIZE.width() - 2 * _STAR_MARGIN)
        row.text = row.fontMetrics.elidedText(row.text, Qt.TextElideMode.ElideRight, title_width)
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, row, painter, view)


class PaperList(QListWidget):
    favoriteRequested = Signal(int)
    paperDropped = Signal(object, object)
    groupDropped = Signal(int, int, bool)

    def __init__(self):
        super().__init__()
        assets = Path(__file__).resolve().parent.parent / "assets"
        self.document_icon = QIcon(str(assets / "paper-file.svg"))
        self.favorite_icon = QIcon(str(assets / "favorite-star.svg"))
        self.outline_icon = QIcon(str(assets / "favorite-outline.svg"))
        self.setObjectName("PaperList")
        self.setIconSize(QSize(15, 15))
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setItemDelegate(PaperRowDelegate(self))
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._visible_paper_ids = set()
        self._visible_group_ids = set()
        self._drag_origin = None
        self._group_press_pos = None
        self._group_dragged = False
        self._modifying_selection = False
        self.drop_target_row = -1
        self.drop_target_kind = None
        self.drop_after = False
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(False)
        self._drag_scroll_direction = 0
        self._drag_position = None
        self._dragging_group_id = None
        self._drag_scroll_timer = QTimer(self)
        self._drag_scroll_timer.setInterval(45)
        self._drag_scroll_timer.timeout.connect(self._auto_scroll_drag)

    def mousePressEvent(self, event):
        self._group_dragged = False
        self._drag_origin = self.itemAt(event.position().toPoint()) if event.button() == Qt.MouseButton.LeftButton else None
        group_id = self._drag_origin.data(GROUP_ID_ROLE) if self._drag_origin else None
        self._group_press_pos = event.position().toPoint() if group_id in self._visible_group_ids else None
        self._modifying_selection = bool(event.modifiers() &
                                         (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))
        # Qt maps the physical Control key to MetaModifier on macOS. A Control
        # click may also arrive as a right mouse press, so handle both forms.
        if (MACOS and event.modifiers() & Qt.KeyboardModifier.MetaModifier
                and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                and event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton)):
            item = self.itemAt(event.position().toPoint())
            if item and item.data(PAPER_ID_ROLE):
                self._modifying_selection = True
                index = self.indexFromItem(item)
                model = self.selectionModel()
                try:
                    model.setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
                    model.select(index, QItemSelectionModel.SelectionFlag.Toggle)
                finally:
                    self._modifying_selection = False
                event.accept()
                return
        try:
            super().mousePressEvent(event)
        finally:
            self._modifying_selection = False

    def mouseReleaseEvent(self, event):
        if self._group_dragged:
            event.accept()
        else:
            super().mouseReleaseEvent(event)
        self._drag_origin = None
        self._group_press_pos = None
        self._group_dragged = False

    def mouseMoveEvent(self, event):
        if (self._group_press_pos is not None and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self._group_press_pos).manhattanLength() >= QApplication.startDragDistance()):
            self._group_press_pos = None
            self._group_dragged = True
            self.startDrag(Qt.DropAction.MoveAction)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def startDrag(self, supported_actions):
        item = self._drag_origin or self.currentItem()
        group_id = item.data(GROUP_ID_ROLE) if item else None
        identifier = item.data(PAPER_ID_ROLE) if item else None
        if group_id not in self._visible_group_ids and not identifier:
            return
        mime = QMimeData()
        identifiers = []
        if group_id in self._visible_group_ids:
            mime.setData(GROUP_MIME, str(group_id).encode('ascii'))
        else:
            selected = [self.item(row).data(PAPER_ID_ROLE) for row in range(self.count())
                        if self.item(row).isSelected() and self.item(row).data(PAPER_ID_ROLE)]
            identifiers = selected if identifier in selected else [identifier]
            mime.setData(PAPER_MIME, json.dumps(identifiers).encode('ascii'))
        drag = QDrag(self)
        drag.setMimeData(mime)
        rect = self.visualItemRect(item).intersected(self.viewport().rect())
        if not rect.isEmpty():
            preview = self.viewport().grab(rect)
            if not preview.isNull():
                if len(identifiers) > 1:
                    painter = QPainter(preview)
                    badge = QRect(max(2, rect.width() - 38), 3, 32, min(24, rect.height() - 6))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(self.palette().link())
                    painter.drawRoundedRect(badge, 10, 10)
                    painter.setPen(self.palette().base().color())
                    painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(len(identifiers)))
                    painter.end()
                drag.setPixmap(preview)
                pointer = self.viewport().mapFromGlobal(QCursor.pos()) - rect.topLeft()
                drag.setHotSpot(QPoint(max(0, min(pointer.x(), rect.width() - 1)),
                                       max(0, min(pointer.y(), rect.height() - 1))))
        drag.exec(Qt.DropAction.MoveAction)
        self._drag_origin = None

    def _dragged_papers(self, event):
        if not event.mimeData().hasFormat(PAPER_MIME):
            return []
        try:
            identifiers = json.loads(bytes(event.mimeData().data(PAPER_MIME)).decode('ascii'))
        except (UnicodeDecodeError, ValueError):
            return []
        if not isinstance(identifiers, list) or not identifiers or any(
                not isinstance(identifier, str) or identifier not in self._visible_paper_ids for identifier in identifiers):
            return []
        return list(dict.fromkeys(identifiers))

    def _dragged_group(self, event):
        if not event.mimeData().hasFormat(GROUP_MIME):
            return None
        try:
            group_id = int(bytes(event.mimeData().data(GROUP_MIME)).decode('ascii'))
        except (UnicodeDecodeError, ValueError):
            return None
        return group_id if group_id in self._visible_group_ids else None

    def clear(self):
        super().clear()
        self._visible_paper_ids.clear()
        self._visible_group_ids.clear()

    def target_group_at(self, position):
        item = self.itemAt(position)
        if item is None:
            return False, None, -1
        for row in range(self.row(item), -1, -1):
            group_id = self.item(row).data(GROUP_ID_ROLE)
            if group_id is not None:
                return True, None if group_id == -1 else group_id, row
        return False, None, -1

    def reorder_target_at(self, position, moving_id):
        item = self.itemAt(position)
        if item is None:
            return False, None, -1, False
        valid, target_id, row = self.target_group_at(position)
        if not valid or target_id not in self._visible_group_ids or target_id == moving_id:
            return False, None, -1, False
        header_rect = self.visualItemRect(self.item(row))
        after = self.row(item) != row or position.y() >= header_rect.center().y()
        return True, target_id, row, after

    def _show_drop_target(self, row, kind=None, after=False):
        if (self.drop_target_row, self.drop_target_kind, self.drop_after) != (row, kind, after):
            self.drop_target_row = row
            self.drop_target_kind = kind
            self.drop_after = after
            self.viewport().update()

    def _set_drag_scroll(self, position):
        self._drag_position = position
        edge = 25
        self._drag_scroll_direction = (-1 if position.y() < edge else
                                       1 if position.y() > self.viewport().height() - edge else 0)
        if self._drag_scroll_direction:
            if not self._drag_scroll_timer.isActive():
                self._drag_scroll_timer.start()
        else:
            self._drag_scroll_timer.stop()

    def _auto_scroll_drag(self):
        bar = self.verticalScrollBar()
        before = bar.value()
        bar.setValue(before + self._drag_scroll_direction * 18)
        if bar.value() == before:
            self._drag_scroll_timer.stop()
            return
        if self._dragging_group_id is not None:
            valid, _target_id, row, after = self.reorder_target_at(self._drag_position, self._dragging_group_id)
            self._show_drop_target(row if valid else -1, 'group' if valid else None, after)
        else:
            valid, _group_id, row = self.target_group_at(self._drag_position)
            self._show_drop_target(row if valid else -1, 'paper' if valid else None)

    def _stop_drag_feedback(self):
        self._drag_scroll_timer.stop()
        self._drag_scroll_direction = 0
        self._drag_position = None
        self._dragging_group_id = None
        self._show_drop_target(-1)

    def dragEnterEvent(self, event):
        if self._dragged_group(event) is not None or self._dragged_papers(event):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        position = event.position().toPoint()
        moving_group = self._dragged_group(event)
        if moving_group is not None:
            valid, _target_id, row, after = self.reorder_target_at(position, moving_group)
            if valid:
                self._dragging_group_id = moving_group
                self._set_drag_scroll(position)
                self._show_drop_target(row, 'group', after)
                event.setDropAction(Qt.DropAction.MoveAction)
                event.accept()
                return
            self._stop_drag_feedback()
            event.ignore()
            return
        valid, _group_id, row = self.target_group_at(position)
        if self._dragged_papers(event) and valid:
            self._dragging_group_id = None
            self._set_drag_scroll(position)
            self._show_drop_target(row, 'paper')
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            self._stop_drag_feedback()
            event.ignore()

    def dragLeaveEvent(self, event):
        self._stop_drag_feedback()
        event.accept()

    def dropEvent(self, event):
        moving_group = self._dragged_group(event)
        if moving_group is not None:
            valid, target_id, _row, after = self.reorder_target_at(event.position().toPoint(), moving_group)
            self._stop_drag_feedback()
            if valid:
                self.groupDropped.emit(moving_group, target_id, after)
                event.setDropAction(Qt.DropAction.MoveAction)
                event.accept()
            else:
                event.ignore()
            return
        identifiers = self._dragged_papers(event)
        valid, group_id, _row = self.target_group_at(event.position().toPoint())
        self._stop_drag_feedback()
        if identifiers and valid:
            self.paperDropped.emit(identifiers, group_id)
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.ignore()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Qt lays out the items and their embedded widgets separately.
        self.updateEditorGeometries()

    def add_group(self, name, group_id, count, pinned=False, collapsed=False):
        marker = '▸' if collapsed else '▾'
        title = f"{marker}  {'↑  ' if pinned else ''}{name}  ({count})"
        item = QListWidgetItem(title)
        item.setData(GROUP_ID_ROLE, group_id)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        font = item.font(); font.setBold(True); item.setFont(font)
        item.setToolTip(f"点击{'展开' if collapsed else '收起'}；右击管理分组：{name}" if group_id != -1
                        else f"点击{'展开' if collapsed else '收起'}未分组论文")
        self.addItem(item)
        if group_id != -1:
            self._visible_group_ids.add(group_id)

    def add_paper(self, title, favorite, identifier=None):
        item = QListWidgetItem(self.document_icon, " ".join(title.split()))
        item.setData(PAPER_ID_ROLE, identifier)
        item.setToolTip(title)
        self.addItem(item)
        if identifier:
            self._visible_paper_ids.add(identifier)

        # Keep the title and selection painted by the list. Only the trailing
        # button owns mouse input, so clicking it cannot select or open a row.
        row_widget = QWidget()
        layout = QHBoxLayout(row_widget)
        layout.setContentsMargins(0, 0, _STAR_MARGIN, 0)
        layout.addStretch()
        star = QToolButton()
        star.setObjectName("PaperFavoriteButton")
        star.setFixedSize(_STAR_SIZE)
        star.setIconSize(QSize(16, 16))
        star.setIcon(self.favorite_icon if favorite else self.outline_icon)
        action = "取消收藏" if favorite else "收藏论文"
        star.setToolTip(action)
        star.setAccessibleName(f"{action}：{title}")
        star.setCursor(Qt.CursorShape.PointingHandCursor)
        star.clicked.connect(lambda: self.request_favorite(item))
        layout.addWidget(star)
        self.setItemWidget(item, row_widget)

    def request_favorite(self, item):
        row = self.row(item)
        if row >= 0:
            self.favoriteRequested.emit(row)
