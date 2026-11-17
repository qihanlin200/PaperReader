"""Research evidence ordered by run, then by workflow subtask."""

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)


class EvidenceMatrix(QScrollArea):
    anchorClicked = Signal(QUrl)

    def __init__(self):
        super().__init__()
        self.setObjectName("ResearchEvidenceMatrix")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body.setObjectName("ResearchEvidenceBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(12, 12, 12, 12)
        self.body_layout.setSpacing(12)
        self.setWidget(self.body)
        self.groups = None
        self.group_rows = []
        self.collapsed = set()
        self._columns = 0
        self.set_groups([])

    def set_groups(self, groups):
        """Show newest task runs first. Each source entry ends with its kind."""
        if groups == self.groups:
            return
        self.groups = groups
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self.group_rows = []
        self.subtask_rows = []
        if not groups:
            empty = QLabel("暂无可展示的证据。")
            empty.setObjectName("ResearchEvidenceEmpty")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.body_layout.addWidget(empty, 1)
        else:
            for index, group in enumerate(groups):
                self._add_group(group, index)
            self.body_layout.addStretch()
        self._reflow_cards(force=True)
        self.verticalScrollBar().setValue(0)

    def _add_group(self, group, index):
        row = QWidget()
        row.setObjectName("ResearchEvidenceTaskRow")
        outer = QHBoxLayout(row)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        rail = QWidget()
        rail.setFixedWidth(27)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(0, 0, 0, 0)
        rail_layout.setSpacing(0)
        marker = QLabel(str(group.get("task_number") or "·"))
        marker.setObjectName("ResearchEvidenceTaskMarker")
        marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        marker.setFixedSize(25, 25)
        rail_layout.addWidget(marker, 0, Qt.AlignmentFlag.AlignHCenter)
        line = QFrame()
        line.setObjectName("ResearchEvidenceTaskLine")
        line.setFixedWidth(2)
        rail_layout.addWidget(line, 1, Qt.AlignmentFlag.AlignHCenter)
        if index == len(self.groups) - 1:
            line.hide()
            rail_layout.addStretch(1)
        outer.addWidget(rail)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 8)
        content_layout.setSpacing(10)
        header, arrow = self._header(group, "ResearchEvidenceTaskHeader", "ResearchEvidenceTaskTitle",
                                     "ResearchEvidenceTaskMeta", "ResearchEvidenceTaskStatus")
        header.clicked.connect(lambda checked=False, key=group["key"]: self.toggle_group(key))
        content_layout.addWidget(header)
        subtasks_widget = QWidget()
        subtasks_widget.setObjectName("ResearchEvidenceSubtasks")
        subtasks_layout = QVBoxLayout(subtasks_widget)
        subtasks_layout.setContentsMargins(10, 0, 0, 0)
        subtasks_layout.setSpacing(10)
        for subtask in group.get("subtasks", ()):
            self._add_subtask(subtask, subtasks_layout)
        content_layout.addWidget(subtasks_widget)
        outer.addWidget(content, 1)
        self.body_layout.addWidget(row)
        item = {"key": group["key"], "row": row, "header": header,
                "arrow": arrow, "content_widget": subtasks_widget}
        self.group_rows.append(item)
        self._apply_collapse(item)

    def _add_subtask(self, subtask, layout):
        row = QWidget()
        row.setObjectName("ResearchEvidenceSubtaskRow")
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        count = len(subtask.get("entries", ()))
        header, arrow = self._header(
            {"title": subtask.get("title", "子任务"), "subtitle": f"{count} 条引用",
             "status": subtask.get("status", "")},
            "ResearchEvidenceSubtaskHeader", "ResearchEvidenceSubtaskTitle",
            "ResearchEvidenceTaskMeta", "ResearchEvidenceTaskStatus")
        header.clicked.connect(lambda checked=False, key=subtask["key"]: self.toggle_group(key))
        row_layout.addWidget(header)
        cards_widget = QWidget()
        cards_widget.setObjectName("ResearchEvidenceCards")
        grid = QGridLayout(cards_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        cards = [self._card(entry) for entry in subtask.get("entries", ())]
        if not cards:
            no_entries = QLabel("该子任务暂无可展示的引用。")
            no_entries.setObjectName("ResearchEvidenceEmptyTask")
            cards.append(no_entries)
        row_layout.addWidget(cards_widget)
        layout.addWidget(row)
        item = {"key": subtask["key"], "row": row, "header": header,
                "arrow": arrow, "content_widget": cards_widget,
                "cards_widget": cards_widget, "grid": grid, "cards": cards}
        self.subtask_rows.append(item)
        self._apply_collapse(item)

    @staticmethod
    def _header(group, header_name, title_name, meta_name, status_name):
        header = QPushButton()
        header.setObjectName(header_name)
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header.setMinimumHeight(66 if header_name == "ResearchEvidenceTaskHeader" else 54)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 8, 12, 8)
        header_layout.setSpacing(8)
        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        title = QLabel(group.get("title", "研究任务"))
        title.setObjectName(title_name)
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        subtitle = QLabel(group.get("subtitle", ""))
        subtitle.setObjectName(meta_name)
        subtitle.setTextFormat(Qt.TextFormat.PlainText)
        subtitle.setWordWrap(True)
        text_column.addWidget(title)
        if subtitle.text():
            text_column.addWidget(subtitle)
        header_layout.addLayout(text_column, 1)
        status = QLabel(group.get("status", ""))
        status.setObjectName(status_name)
        header_layout.addWidget(status)
        arrow = QLabel()
        arrow.setObjectName("ResearchEvidenceTaskArrow")
        header_layout.addWidget(arrow)
        for child in (title, subtitle, status, arrow):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        return header, arrow

    def _card(self, entry):
        title, excerpt, metadata, url, kind = entry
        local = kind in ("paper", "text")
        card = QPushButton()
        card.setObjectName("ResearchEvidenceLocal" if local else "ResearchEvidenceWeb")
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setAccessibleName(title)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        card.setMinimumHeight(155)
        card.clicked.connect(lambda checked=False, target=url: self.anchorClicked.emit(QUrl(target)))
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        source = ("本地论文" if kind == "paper" else "本地资料" if kind == "text" else
                  "学术来源" if kind == "academic" else "网页检索")
        number, separator, headline = title.partition(" · ")
        source_row = QHBoxLayout()
        badge = QLabel(source)
        badge.setObjectName("ResearchEvidenceLocalBadge" if local else "ResearchEvidenceWebBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        source_row.addWidget(badge, 0, Qt.AlignmentFlag.AlignLeft)
        meta = " · ".join(part for part in (number if separator else "", metadata) if part)
        if meta:
            source_row.addWidget(self._label(meta, "ResearchEvidenceMeta"), 1)
        layout.addLayout(source_row)
        layout.addWidget(self._label(headline if separator else title, "ResearchEvidenceTitle"))
        excerpt = " ".join(excerpt.split())
        if len(excerpt) > 120:
            excerpt = excerpt[:120].rstrip() + "…"
        if excerpt:
            layout.addWidget(self._label(excerpt, "ResearchEvidenceMeta"))
        layout.addStretch()
        divider = QFrame()
        divider.setObjectName("ResearchEvidenceDivider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)
        layout.addWidget(self._label("查看本地原文 ›" if local else "查看来源 ›",
                                     "ResearchEvidenceLink"))
        return card

    @staticmethod
    def _label(value, name):
        label = QLabel(value)
        label.setObjectName(name)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        return label

    def toggle_group(self, key):
        if key in self.collapsed:
            self.collapsed.remove(key)
        else:
            self.collapsed.add(key)
        for item in self.group_rows + self.subtask_rows:
            if item["key"] == key:
                self._apply_collapse(item)
                break

    def _apply_collapse(self, item):
        expanded = item["key"] not in self.collapsed
        item["content_widget"].setVisible(expanded)
        item["arrow"].setText("⌄" if expanded else "›")
        item["header"].setAccessibleName("收起引用" if expanded else "展开引用")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow_cards()

    def _reflow_cards(self, *, force=False):
        if not hasattr(self, "group_rows"):
            return
        columns = 2 if self.viewport().width() >= 700 else 1
        if columns == self._columns and not force:
            return
        self._columns = columns
        for item in self.subtask_rows:
            grid = item["grid"]
            while grid.count():
                grid.takeAt(0)
            for index, card in enumerate(item["cards"]):
                grid.addWidget(card, index // columns, index % columns)
            for column in range(columns):
                grid.setColumnStretch(column, 1)
