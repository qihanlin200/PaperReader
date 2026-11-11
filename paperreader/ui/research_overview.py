"""Cards for the research discussion overview."""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from paperreader.ui.work_rail import menu_symbol_icon


class WrappedOverviewLabel(QLabel):
    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = event.size().width()
        if width > 0 and width != event.oldSize().width():
            self.setMinimumHeight(self.heightForWidth(width))


def label(value, style="", *, wrap=False):
    widget = WrappedOverviewLabel(value) if wrap else QLabel(value)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setObjectName(style)
    widget.setWordWrap(wrap)
    widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    if wrap:
        widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
    return widget


def divider():
    line = QFrame()
    line.setObjectName("ResearchOverviewDivider")
    line.setFixedHeight(1)
    return line


class OverviewCard(QFrame):
    def __init__(self, title, symbol, wheel_filter):
        super().__init__()
        self.setObjectName("ResearchOverview")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.snapshot = None
        self.wheel_filter = wheel_filter
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        header = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(menu_symbol_icon(symbol, color="#66ddda").pixmap(22, 22))
        header.addWidget(icon)
        header.addWidget(label(title, "ResearchOverviewTitle"), 1)
        self.count = label("", "ResearchOverviewAccent")
        header.addWidget(self.count)
        layout.addLayout(header)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        layout.addLayout(self.body)
        layout.addStretch()

    def replace(self, snapshot):
        if snapshot == self.snapshot:
            return False
        self.snapshot = snapshot
        while self.body.count():
            widget = self.body.takeAt(0).widget()
            widget.hide()
            widget.deleteLater()
        return True

    def add(self, widget):
        self.body.addWidget(widget)
        widget.installEventFilter(self.wheel_filter)
        for child in widget.findChildren(QWidget):
            child.installEventFilter(self.wheel_filter)


class OverviewButton(QPushButton):
    """Size the clickable surface using its wrapped labels."""
    def __init__(self):
        super().__init__()
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def sizeHint(self):
        return self.layout().sizeHint() if self.layout() else super().sizeHint()

    def minimumSizeHint(self):
        return self.layout().minimumSize() if self.layout() else super().minimumSizeHint()

    def heightForWidth(self, width):
        layout = self.layout()
        if layout and layout.hasHeightForWidth():
            return layout.totalHeightForWidth(width)
        return self.sizeHint().height()


def clickable(style, accessible, callback):
    button = OverviewButton()
    button.setObjectName(style)
    button.setAccessibleName(accessible)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.clicked.connect(callback)
    return button


class SubtaskOverview(OverviewCard):
    def __init__(self, wheel_filter, open_detail):
        super().__init__("子任务", "group", wheel_filter)
        self.open_detail = open_detail

    def set_tasks(self, index, tasks, activity):
        entries = [(task["title"], task["status"], task.get("question", ""), len(task.get("refs", [])))
                   for task in tasks]
        if not self.replace((index, entries, activity)):
            return
        self.count.setText(f"{sum(entry[1] == '已完成' for entry in entries)}/{len(entries)} 已完成")
        for number, (title, status, question, refs) in enumerate(entries, 1):
            running = status == "执行中"
            target = QUrl(f"research-subtask:{index}-{number}")
            card = clickable("ResearchSubtaskRunning" if running else "ResearchSubtaskRow",
                             f"{title}，{status}", lambda _, url=target: self.open_detail(url))
            layout = QVBoxLayout(card)
            layout.setContentsMargins(9, 9, 9, 9)
            layout.setSpacing(7)
            row = QHBoxLayout()
            row.setSpacing(7)
            mark = {"已完成": "✓", "执行中": "◉", "待执行": "○"}.get(status, "!")
            marker = label(mark, "ResearchTaskMark" if status == "已完成" else
                           "ResearchOverviewAccent" if running else "ResearchOverviewMuted")
            marker.setFixedSize(18, 18)
            marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(marker, 0, Qt.AlignmentFlag.AlignTop)
            content = QVBoxLayout()
            content.setSpacing(4)
            content.addWidget(label(f"{number:02d}  {title}", "ResearchTaskName", wrap=True))
            if running and question:
                content.addWidget(label(question, "ResearchOverviewMuted", wrap=True))
            elif refs:
                content.addWidget(label(f"{refs} 条证据", "ResearchOverviewMuted"))
            row.addLayout(content, 1)
            status_style = ("ResearchOverviewAccent" if status == "已完成" else
                            "ResearchTaskActiveBadge" if running else "ResearchTaskBadge")
            row.addWidget(label(status, status_style), 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(label("›", "ResearchOverviewMuted"))
            layout.addLayout(row)
            if running:
                layout.addWidget(divider())
                footer = QHBoxLayout()
                footer.addWidget(label("◌", "ResearchOverviewAccent"))
                footer.addWidget(label(activity, "ResearchOverviewMuted", wrap=True), 1)
                footer.addWidget(label("查看详情 ›", "ResearchOverviewAccent"))
                layout.addLayout(footer)
            self.add(card)


class EvidenceOverview(OverviewCard):
    def __init__(self, wheel_filter, open_detail, open_matrix):
        super().__init__("证据要点", "clipboard", wheel_filter)
        self.open_detail = open_detail
        self.open_matrix = open_matrix

    def set_evidence(self, index, sources):
        entries = [(source["title"], " ".join(source["text"].split())) for source in sources[:3]]
        if not self.replace((index, entries, len(sources))):
            return
        if not entries:
            self.add(label("等待取证", "ResearchOverviewMuted"))
            return
        for number, (title, excerpt) in enumerate(entries, 1):
            self.add(divider())
            target = QUrl(f"research-content:{index}-{number}")
            card = clickable("ResearchEvidencePoint", title, lambda _, url=target: self.open_detail(url))
            layout = QHBoxLayout(card)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(label("●", "ResearchOverviewAccent"), 0, Qt.AlignmentFlag.AlignTop)
            summary = excerpt[:96] + ("…" if len(excerpt) > 96 else "")
            layout.addWidget(label(summary or title, wrap=True), 1)
            self.add(card)
        self.add(divider())
        footer = clickable("ResearchEvidencePoint", "查看引用矩阵", self.open_matrix)
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label(f"共 {len(sources)} 条证据要点", "ResearchOverviewMuted"), 1)
        layout.addWidget(label("›", "ResearchOverviewAccent"))
        self.add(footer)
