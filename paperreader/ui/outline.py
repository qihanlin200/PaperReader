"""Compact, searchable outline for the AI analysis pane."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QFrame, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout


class AnalysisOutline(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("AnalysisOutline")
        self.browser = None
        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(True)
        self.update_timer.setInterval(250)
        self.update_timer.timeout.connect(self.refresh_items)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)
        self.search = QLineEdit()
        self.search.setPlaceholderText("查找章节…")
        self.search.textChanged.connect(self.filter_items)
        layout.addWidget(self.search)
        self.items = QListWidget()
        self.items.setObjectName("AnalysisOutlineList")
        self.items.itemActivated.connect(self.go_to_item)
        self.items.itemClicked.connect(self.go_to_item)
        layout.addWidget(self.items)

    def show_for(self, button, browser):
        if self.browser is not browser:
            if self.browser is not None:
                self.browser.headingsChanged.disconnect(self.queue_refresh)
            self.browser = browser
            browser.headingsChanged.connect(self.queue_refresh)
        self.search.clear()
        self.refresh_items()
        height = min(360, 66 + min(self.items.count(), 8) * 38)
        self.resize(300, height)
        screen = button.screen().availableGeometry()
        point = button.mapToGlobal(button.rect().bottomLeft())
        self.move(max(screen.left(), min(point.x(), screen.right() - self.width())),
                  max(screen.top(), min(point.y(), screen.bottom() - self.height())))
        self.show()
        self.search.setFocus()

    def queue_refresh(self):
        if self.isVisible() and not self.update_timer.isActive():
            self.update_timer.start()

    def refresh_items(self):
        if self.browser is None:
            return
        self.items.clear()
        headings = self.browser.headings()
        for level, title, position in headings:
            item = QListWidgetItem("  " * (level - 1) + title)
            item.setData(Qt.ItemDataRole.UserRole, position)
            item.setToolTip(title)
            self.items.addItem(item)
        if not headings:
            item = QListWidgetItem("分析内容尚无标题")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.items.addItem(item)
        self.filter_items(self.search.text())

    def filter_items(self, query):
        query = query.casefold().strip()
        for index in range(self.items.count()):
            item = self.items.item(index)
            item.setHidden(bool(query) and query not in item.text().casefold())

    def go_to_item(self, item):
        position = item.data(Qt.ItemDataRole.UserRole)
        if position is None or self.browser is None:
            return
        cursor = QTextCursor(self.browser.document())
        cursor.setPosition(position)
        self.browser.setTextCursor(cursor)
        self.browser.ensureCursorVisible()
        self.hide()
