"""Paper list with a native favorite button at the end of each row."""
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout, QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QToolButton, QWidget,
)


_STAR_SIZE = QSize(30, 26)
_STAR_MARGIN = 4


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
        text_rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, row, view)
        title_width = max(0, text_rect.width() - _STAR_SIZE.width() - 2 * _STAR_MARGIN)
        row.text = row.fontMetrics.elidedText(row.text, Qt.TextElideMode.ElideRight, title_width)
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, row, painter, view)


class PaperList(QListWidget):
    favoriteRequested = Signal(int)

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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Qt lays out the items and their embedded widgets separately.
        self.updateEditorGeometries()

    def add_paper(self, title, favorite):
        item = QListWidgetItem(self.document_icon, " ".join(title.split()))
        item.setToolTip(title)
        self.addItem(item)

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
