"""Research space, conversation and on-demand source details."""
from copy import deepcopy
from datetime import datetime
from html import escape
from hashlib import sha256
import json
import re
from pathlib import Path
import shutil
from uuid import uuid4

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QRunnable, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QTabBar,
    QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QTabWidget, QTreeWidget, QTreeWidgetItem, QStyle, QStyleOptionButton, QVBoxLayout, QWidget,
)

from paperreader.services.lazy import fitz, keyring
from paperreader.services.research import CITATION, RunLimit, execute, expand_mindmap, space_title
from paperreader.services.research_pdf import PDFDownloadBlocked, download_citation_pdf
from paperreader.ui.composer import QuestionEdit
from paperreader.ui.pdf import ContinuousPDF
from paperreader.ui.research_cards import ResearchCards, ResearchConclusions, conclusion_markdown, draw_mindmap, link, plain, position
from paperreader.ui.research_evidence import EvidenceMatrix
from paperreader.ui.research_overview import EvidenceOverview, SubtaskOverview
from paperreader.ui.research_mindmap import MindmapCanvas
from paperreader.ui.research_progress import ResearchProgress
from paperreader.ui.research_trace import ResearchTrace
from paperreader.ui.theme import theme_color
from paperreader.ui.work_rail import menu_symbol_icon


class DiscussionScroll(QScrollArea):
    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel:
            self.wheelEvent(event)
            return event.isAccepted()
        return super().eventFilter(watched, event)

    def wheelEvent(self, event):
        bar = self.verticalScrollBar()
        pixels = event.pixelDelta().y()
        if event.pixelDelta().isNull():
            angle = event.angleDelta().y()
            pixels = round(angle * QApplication.wheelScrollLines() * bar.singleStep() / 120)
        if pixels:
            bar.setValue(bar.value() - pixels)
        # QScrollArea's default wheel handler redispatches to a scrollbar.
        # Handle the event here so propagation cannot re-enter a card's filter.
        event.accept()


class DiscussionMindmap(QWidget):
    def __init__(self):
        super().__init__()
        self.mindmap = None
        self.image = None
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def set_mindmap(self, mindmap):
        if self.mindmap != mindmap:
            self.mindmap = mindmap
            self.refresh_image()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self.refresh_image()

    def refresh_image(self):
        if self.mindmap is not None and self.width() > 0:
            self.image = draw_mindmap(self.mindmap, min(760, self.width()))
            self.setFixedHeight(self.image.height() // 2)
            self.update()

    def paintEvent(self, event):
        if self.image is None:
            return
        width = self.image.width() / 2
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(QRectF((self.width() - width) / 2, 0, width, self.height()), self.image)
        painter.end()


class ResearchCheckBox(QCheckBox):
    def __init__(self, text):
        super().__init__(text)
        self.setObjectName("ResearchCheckBox")

    def hitButton(self, point):
        return self.rect().contains(point)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.isChecked():
            return
        option = QStyleOptionButton()
        self.initStyleOption(option)
        rect = self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(theme_color("#092426")), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        x, y = rect.center().x(), rect.center().y()
        painter.drawLine(QPointF(x - 4, y), QPointF(x - 1, y + 3))
        painter.drawLine(QPointF(x - 1, y + 3), QPointF(x + 5, y - 4))
        painter.end()


class ResearchEvents(QObject):
    update = Signal(str, object)


class ResearchJob(QRunnable):
    def __init__(self, args):
        super().__init__()
        self.args = args
        self.events = ResearchEvents()

    def run(self):
        self.events.update.emit("done", execute(*self.args, self.events.update.emit))


class MindmapJob(QRunnable):
    def __init__(self, run, config, key, limit):
        super().__init__()
        self.run_record = run
        self.config, self.key, self.limit = config, key, limit
        self.events = ResearchEvents()

    def run(self):
        try:
            result = expand_mindmap(self.run_record["answer"], self.config, self.key, self.limit)
            error = ""
        except Exception:
            result = None
            error = "完整脑图生成失败，可重试。"
        self.events.update.emit("mindmap", (self.run_record, result, error))


class ResearchPDFJob(QRunnable):
    def __init__(self, token, source, local, load, *, report_progress=False):
        super().__init__()
        self.token = token
        self.source = source
        self.local = local
        self.load = load
        self.report_progress = report_progress
        self.events = ResearchEvents()

    def run(self):
        try:
            if self.report_progress:
                data = self.load(lambda size, total: self.events.update.emit(
                    "progress", (self.token, size, total)))
            else:
                data = self.load()
        except PDFDownloadBlocked:
            data = "blocked"
        except Exception:
            data = None
        self.events.update.emit("pdf", (self.token, self.source, self.local, data))


def button(label, callback, style="Quiet"):
    widget = QPushButton(label)
    widget.setObjectName(style)
    widget.clicked.connect(callback)
    return widget


def heading(label):
    widget = QLabel(label)
    widget.setObjectName("PanelTitle")
    return widget


class ResearchWorkspace(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.path = window.library.root / "research-spaces.json"
        self.spaces = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []
        self.active = None
        self.detail_run = None
        self.expanded_trace = set()
        self.conclusion_cache = {}
        self.drafts = {}
        self.visible_space = None
        recovered = False
        for space in self.spaces:
            for run in space["runs"]:
                if run["status"] == "运行中":
                    run["status"] = "已中断"
                    recovered = True
        if recovered:
            self.save()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 0)
        self.split = QSplitter()
        self.split.setChildrenCollapsible(False)
        layout.addWidget(self.split)
        left, left_layout = self.pane("LibraryPanel")
        left.setMinimumWidth(220)
        row = QHBoxLayout()
        row.addWidget(heading("研究空间"), 1)
        add = button("＋", self.create_space)
        add.setAccessibleName("新建课题")
        row.addWidget(add)
        left_layout.addLayout(row)
        self.topic_search = QLineEdit()
        self.topic_search.setPlaceholderText("搜索课题…")
        left_layout.addWidget(self.topic_search)
        self.space_list = QListWidget()
        self.space_list.setObjectName("ResearchTopicList")
        self.space_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.space_list.customContextMenuRequested.connect(self.topic_menu)
        self.topic_search.textChanged.connect(self.filter_spaces)
        self.space_list.setMaximumHeight(220)
        left_layout.addWidget(self.space_list, 1)
        for space in self.spaces:
            self.add_space_item(space["name"])

        self.knowledge = QWidget()
        knowledge = QVBoxLayout(self.knowledge)
        knowledge.setContentsMargins(0, 8, 0, 0)
        row = QHBoxLayout()
        row.addWidget(heading("知识库"), 1)
        import_button = QPushButton("＋")
        import_button.setObjectName("Quiet")
        import_button.setAccessibleName("导入知识库资料")
        import_menu = QMenu(import_button)
        import_menu.addAction(menu_symbol_icon("library"), "从论文库导入", self.import_papers)
        import_menu.addAction(menu_symbol_icon("document"), "从本地导入", self.import_local)
        import_button.setMenu(import_menu)
        row.addWidget(import_button)
        knowledge.addLayout(row)
        self.sources = QListWidget()
        self.sources.setObjectName("ResearchSourceList")
        self.sources.itemDoubleClicked.connect(self.preview_source)
        knowledge.addWidget(self.sources, 1)
        left_layout.addWidget(self.knowledge, 2)
        left_layout.addStretch()

        center, work = self.pane("ResearchWorkbench")
        center.setMinimumWidth(320)
        work.setSpacing(8)
        self.work_tabs = QTabBar()
        self.work_tabs.setObjectName("ResearchTabs")
        self.work_tabs.setExpanding(False)
        self.work_tabs.setUsesScrollButtons(True)
        for symbol, label in (("discussion", "研究讨论"), ("matrix", "引用矩阵"),
                              ("flow", "思维脑图"), ("target", "最终结论"), ("trace", "执行记录")):
            self.work_tabs.addTab(menu_symbol_icon(symbol), label)
        work.addWidget(self.work_tabs)
        self.discussion_space = DiscussionScroll()
        self.discussion_space.setObjectName("ResearchDiscussionScroll")
        self.discussion_space.setWidgetResizable(True)
        self.discussion_space.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        discussion_panel = QWidget()
        discussion_panel.setObjectName("ResearchDiscussionPanel")
        discussion = QGridLayout(discussion_panel)
        discussion.setContentsMargins(0, 0, 0, 0)
        discussion.setSpacing(8)
        discussion.setColumnStretch(0, 1)
        discussion.setColumnStretch(1, 1)
        discussion.setRowStretch(4, 1)
        self.discussion_space.setWidget(discussion_panel)
        work.addWidget(self.discussion_space, 1)
        self.task_header = QWidget()
        self.task_header.setObjectName("ResearchOverview")
        task_layout = QVBoxLayout(self.task_header)
        task_layout.setContentsMargins(14, 10, 14, 8)
        task_row = QHBoxLayout()
        task_row.setSpacing(10)
        self.task_trace = QLabel()
        self.task_trace.setTextFormat(Qt.TextFormat.RichText)
        self.task_trace.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse |
                                                Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self.task_trace.linkActivated.connect(lambda target: self.open_detail(QUrl(target)))
        target = QLabel()
        target.setPixmap(menu_symbol_icon("target").pixmap(20, 20))
        task_row.addWidget(target)
        task_row.addWidget(heading("研究任务"), 1)
        task_row.addWidget(self.task_trace, 0, Qt.AlignmentFlag.AlignVCenter)
        self.status = QLabel()
        self.status.setObjectName("ResearchStatus")
        task_row.addWidget(self.status)
        self.task_percentage = QLabel()
        self.task_percentage.setObjectName("ResearchPercentage")
        task_row.addWidget(self.task_percentage)
        task_layout.addLayout(task_row)
        self.task_title = heading("")
        self.task_title.setObjectName("ResearchTaskTitle")
        self.task_title.setTextFormat(Qt.TextFormat.PlainText)
        self.task_title.setWordWrap(True)
        task_layout.addWidget(self.task_title)
        self.task_subtitle = QLabel()
        self.task_subtitle.setObjectName("ResearchTaskSubtitle")
        self.task_subtitle.setTextFormat(Qt.TextFormat.PlainText)
        self.task_subtitle.setWordWrap(True)
        task_layout.addWidget(self.task_subtitle)
        self.task_steps = ResearchProgress()
        task_layout.addWidget(self.task_steps)
        self.task_actions = QLabel()
        self.task_actions.setTextFormat(Qt.TextFormat.RichText)
        self.task_actions.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse |
                                                  Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self.task_actions.linkActivated.connect(lambda target: self.open_detail(QUrl(target)))
        task_layout.addWidget(self.task_actions)
        discussion.addWidget(self.task_header, 0, 0, 1, 2)
        self.subtask_overview = SubtaskOverview(self.discussion_space, self.open_detail)
        self.evidence_overview = EvidenceOverview(self.discussion_space, self.open_detail,
                                                  lambda: self.work_tabs.setCurrentIndex(1))
        discussion.addWidget(self.subtask_overview, 1, 0)
        discussion.addWidget(self.evidence_overview, 1, 1)
        self.discussion_mindmap = DiscussionMindmap()
        self.discussion_mindmap_card = self.discussion_card("flow", "思维脑图", self.discussion_mindmap)
        self.full_map_button = button("打开完整脑图 ↗", self.open_full_mindmap)
        self.discussion_mindmap_card.layout().itemAt(0).layout().addWidget(self.full_map_button)
        discussion.addWidget(self.discussion_mindmap_card, 2, 0, 1, 2)
        self.discussion_summary = QLabel()
        self.discussion_summary.setWordWrap(True)
        self.discussion_summary.setTextFormat(Qt.TextFormat.RichText)
        self.discussion_summary.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse |
                                                        Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self.discussion_summary.linkActivated.connect(lambda url: self.open_detail(QUrl(url)))
        self.discussion_summary_card = self.discussion_card("target", "任务总结", self.discussion_summary)
        discussion.addWidget(self.discussion_summary_card, 3, 0, 1, 2)
        for child in discussion_panel.findChildren(QWidget):
            child.installEventFilter(self.discussion_space)
        self.chat = ResearchCards()
        self.chat.setObjectName("ResearchConversation")
        self.chat.anchorClicked.connect(self.open_detail)
        self.work_tabs.currentChanged.connect(self.switch_work_tab)
        work.addWidget(self.chat, 1)
        self.evidence_matrix = EvidenceMatrix()
        self.evidence_matrix.anchorClicked.connect(self.open_detail)
        work.addWidget(self.evidence_matrix, 1)
        self.conclusions = ResearchConclusions(line_height=170)
        self.conclusions.setObjectName("ResearchConversation")
        self.conclusions.anchorClicked.connect(self.open_detail)
        work.addWidget(self.conclusions, 1)
        self.full_map_run = None
        self.full_map_pending = {}
        self.full_map_error = {}
        self.full_map_panel = QWidget()
        map_layout = QVBoxLayout(self.full_map_panel)
        map_layout.setContentsMargins(0, 0, 0, 0)
        map_header = QHBoxLayout()
        self.full_map_status = QLabel()
        self.full_map_status.setWordWrap(True)
        map_header.addWidget(self.full_map_status, 1)
        self.full_map_retry = button("重试生成", self.open_full_mindmap)
        map_header.addWidget(self.full_map_retry)
        map_layout.addLayout(map_header)
        self.full_map_canvas = MindmapCanvas()
        for label, callback in (("−", lambda: self.full_map_canvas.zoom(1 / 1.2)),
                                ("＋", lambda: self.full_map_canvas.zoom(1.2)),
                                ("居中", self.full_map_canvas.reset_view)):
            map_header.addWidget(button(label, callback))
        map_layout.addWidget(self.full_map_canvas, 1)
        work.addWidget(self.full_map_panel, 1)
        self.composer = QuestionEdit(footer_height=32)
        self.composer.footer_layout.setContentsMargins(4, 2, 4, 2)
        self.composer.setObjectName("ResearchComposer")
        self.composer.setPlaceholderText("向研究 Agent 提问，或让它继续研究…")
        self.composer.setMaximumHeight(150)
        self.composer.submitRequested.connect(self.start)
        self.send = button("发送 ↑", self.send_or_stop, "Primary")
        self.models = QComboBox()
        self.models.setAccessibleName("研究使用的模型")
        self.models.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.models.setMinimumContentsLength(8)
        self.models.setMaximumWidth(220)
        self.refresh_models()
        self.composer.footer_layout.addWidget(self.models)
        self.academic = QPushButton("深度检索")
        self.academic.setObjectName("ResearchSearchToggle")
        self.academic.setCheckable(True)
        self.academic.setToolTip("开启后将当前问题发送给 Crossref，查询论文题名与 DOI。")
        self.composer.footer_layout.addWidget(self.academic)
        self.composer.footer_layout.addStretch()
        for control in (self.models, self.academic, self.send):
            control.setFixedHeight(28)
        self.composer.footer_layout.addWidget(self.send)
        work.addWidget(self.composer)

        self.detail_slot = QStackedWidget()
        self.detail_slot.setMinimumWidth(265)
        self.split.addWidget(self.detail_slot)
        self.detail = QWidget()
        self.detail.setObjectName("ChatPanel")
        self.detail_slot.addWidget(self.detail)
        details = QVBoxLayout(self.detail)
        details.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self.detail_tab_menu)
        self.content = ResearchConclusions()
        self.subtask_timer = QTimer(self)
        self.subtask_timer.setSingleShot(True)
        self.subtask_timer.setInterval(16)
        self.subtask_timer.timeout.connect(self.render_subtask)
        self.subtask_cache = None
        self.content.anchorClicked.connect(self.open_pdf)
        self.trace = ResearchTrace()
        self.trace.toggle_requested.connect(self.toggle_trace)
        self.trace.export_requested.connect(self.export_trace)
        self.tabs.addTab(self.trace, menu_symbol_icon("pulse"), "执行追踪")
        self.tabs.addTab(self.content, menu_symbol_icon("document"), "引用")
        self.pdf_panel = QWidget()
        pdf_layout = QVBoxLayout(self.pdf_panel)
        pdf_layout.setContentsMargins(2, 4, 2, 2)
        self.pdf_status = QLabel()
        self.pdf_status.setTextFormat(Qt.TextFormat.PlainText)
        self.pdf_status.setWordWrap(True)
        pdf_layout.addWidget(self.pdf_status)
        self.pdf_view = ContinuousPDF()
        pdf_layout.addWidget(self.pdf_view, 1)
        self.pdf_document = None
        self.pdf_request = None
        self.pdf_downloader = None
        self.pdf_source = None
        self.pdf_download_only = False
        self.pdf_view.hide()
        details.addWidget(self.tabs)
        self.download_status = QLabel()
        self.download_status.setTextFormat(Qt.TextFormat.PlainText)
        self.download_status.setWordWrap(True)
        self.download_status.setContentsMargins(8, 4, 8, 5)
        self.download_status.hide()
        details.addWidget(self.download_status)
        self.tabs.currentChanged.connect(self.refresh_detail_tab)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([260, 680, 340])
        self.close_detail()
        self.space_list.currentRowChanged.connect(self.switch_space)
        if self.space_list.count():
            self.space_list.setCurrentRow(0)
        else:
            self.switch_space()

    def refresh_models(self):
        selected = self.models.currentData()
        self.models.clear()
        for profile in self.window.profile_config["profiles"]:
            if profile["model"].strip():
                self.models.addItem(profile["model"], profile["id"])
                self.models.setItemData(self.models.count() - 1, profile["name"], Qt.ItemDataRole.ToolTipRole)
        index = self.models.findData(selected)
        self.models.setCurrentIndex(max(0, index))
        self.models.setPlaceholderText("请配置模型")

    def detail_tab_menu(self, point):
        bar = self.tabs.tabBar()
        index = bar.tabAt(point)
        if index < 0:
            return
        menu = QMenu(bar)
        menu.addAction("关闭页签", lambda: self.close_detail_tab(index))
        menu.exec(bar.mapToGlobal(point))

    def close_detail_tab(self, index):
        pane = self.tabs.widget(index)
        if pane is self.pdf_panel:
            self.clear_pdf()
        elif pane is not None:
            self.tabs.setTabVisible(index, False)
        if not any(self.tabs.isTabVisible(i) for i in range(self.tabs.count())):
            self.close_detail()

    def select_detail_tab(self, pane):
        index = self.tabs.indexOf(pane)
        if index >= 0:
            self.tabs.setTabVisible(index, True)
            self.tabs.setCurrentWidget(pane)

    def close_detail(self):
        self.clear_pdf()
        self.download_status.hide()
        self.detail_slot.setCurrentWidget(self.detail)
        self.trace.show_events("", "", [])
        self.content.show_cards([], "请选择证据。")

    def clear_pdf(self):
        self.pdf_request = None
        if self.pdf_downloader is not None:
            self.pdf_downloader.cancel()
            self.pdf_downloader.hide()
        if self.pdf_document is not None:
            self.pdf_view.clear_document()
            self.pdf_document.close()
            self.pdf_document = None
        index = self.tabs.indexOf(self.pdf_panel)
        if index >= 0:
            self.tabs.removeTab(index)

    def pane(self, style):
        panel = QWidget()
        panel.setObjectName(style)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        self.split.addWidget(panel)
        return panel, layout

    def add_space_item(self, name):
        QListWidgetItem(menu_symbol_icon("folder"), name, self.space_list)

    def filter_spaces(self, text):
        words = text.casefold().split()
        for row in range(self.space_list.count()):
            item = self.space_list.item(row)
            item.setHidden(not all(word in item.text().casefold() for word in words))

    def save(self):
        temp = self.path.with_suffix(".tmp")
        try:
            temp.write_text(json.dumps(self.spaces, ensure_ascii=False), encoding="utf-8")
            temp.replace(self.path)
        except OSError:
            self.window.statusBar().showMessage("研究数据保存失败，请检查存储空间。")
            return False
        return True

    def selected(self):
        row = self.space_list.currentRow()
        return self.spaces[row] if row >= 0 else None

    def ask_topic_name(self, title, initial=""):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setMinimumWidth(380)
        dialog.resize(440, dialog.sizeHint().height())
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("课题名称"))
        name = QLineEdit(initial)
        name.setPlaceholderText("例如：比较论文中的研究方法")
        layout.addWidget(name)
        actions = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        confirm = actions.button(QDialogButtonBox.StandardButton.Ok)
        confirm.setText("保存" if initial else "创建")
        confirm.setEnabled(bool(initial.strip()))
        name.textChanged.connect(lambda text: confirm.setEnabled(bool(text.strip())))
        layout.addWidget(actions)
        return name.text().strip() if dialog.exec() else ""

    def create_space(self):
        title = self.ask_topic_name("新建课题")
        if title:
            self.spaces.append(dict(id=uuid4().hex, name=title, sources=[], runs=[]))
            if not self.save():
                self.spaces.pop()
                return
            self.topic_search.clear()
            self.add_space_item(title)
            self.space_list.setCurrentRow(len(self.spaces) - 1)

    def topic_menu(self, point):
        item = self.space_list.itemAt(point)
        if item is None:
            return
        space = self.spaces[self.space_list.row(item)]
        menu = QMenu(self.space_list)
        menu.addAction(menu_symbol_icon("edit"), "修改课题名称", lambda: self.rename_space(item, space))
        clear = menu.addAction(menu_symbol_icon("eraser"), "清空分析内容", lambda: self.clear_analysis(space))
        clear.setEnabled(bool(space["runs"]) and (not self.active or self.active[0] is not space))
        remove = menu.addAction(menu_symbol_icon("trash"), "删除课题", lambda: self.delete_space(space))
        remove.setEnabled(not self.active or self.active[0] is not space)
        menu.exec(self.space_list.viewport().mapToGlobal(point))

    def rename_space(self, item, space):
        previous = space["name"]
        title = self.ask_topic_name("修改课题名称", previous)
        if title and title != previous:
            space["name"] = title
            if not self.save():
                space["name"] = previous
                return
            item.setText(title)
            self.filter_spaces(self.topic_search.text())

    def clear_analysis(self, space):
        if not space["runs"] or (self.active and self.active[0] is space):
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle("清空分析内容")
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(f"清空「{space['name']}」的研究记录和已下载的论文缓存？课题、知识库和阅读列表中的论文将保留。")
        dialog.setIconPixmap(menu_symbol_icon("eraser", color="#66ddda", size=44).pixmap(44, 44))
        confirm = dialog.addButton("清空", QMessageBox.ButtonRole.DestructiveRole)
        cancel = dialog.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(cancel)
        dialog.exec()
        if dialog.clickedButton() is not confirm:
            return
        runs = space["runs"]
        space["runs"] = []
        if not self.save():
            space["runs"] = runs
            return
        if self.visible_space is space:
            self.composer.clear()
            self.evidence_matrix.set_entries([])
            self.full_map_canvas.set_mindmap(None)
            self.switch_space()
        self.drafts.pop(space["id"], None)
        ids = {run["id"] for run in runs}
        for identifier in ids:
            limit = self.full_map_pending.get(identifier)
            if limit:
                limit.stop.set()
            self.full_map_error.pop(identifier, None)
        for key in list(self.conclusion_cache):
            if key[0] in ids:
                del self.conclusion_cache[key]
        self.remove_download_cache(dict(space, runs=runs))
        self.window.statusBar().showMessage("已清空分析内容，知识库已保留。", 4000)

    def delete_space(self, space=None):
        space = self.selected() if space is None else space
        if space is None or (self.active and self.active[0] is space):
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle("删除课题")
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(f"删除「{space['name']}」及其研究记录和已下载的论文缓存？阅读列表中的论文将保留。")
        dialog.setIconPixmap(menu_symbol_icon("question", color="#66ddda", size=44).pixmap(44, 44))
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        if dialog.exec() != QMessageBox.StandardButton.Yes:
            return
        row = self.spaces.index(space)
        self.spaces.pop(row)
        if not self.save():
            self.spaces.insert(row, space)
            return
        if self.visible_space is space:
            self.close_detail()
        for run in space["runs"]:
            limit = self.full_map_pending.get(run["id"])
            if limit:
                limit.stop.set()
        self.remove_download_cache(space)
        self.space_list.takeItem(row)
        self.conclusion_cache.clear()
        self.drafts.pop(space["id"], None)
        self.switch_space()

    def download_directory(self, space):
        return self.window.library.root / "research-downloads" / sha256(space["id"].encode()).hexdigest()

    def download_path(self, source, *, existing=False):
        filename = sha256(source["id"].encode()).hexdigest() + ".pdf"
        path = self.download_directory(self.selected()) / filename
        if existing and not path.is_file():
            return path.parent.parent / filename
        return path

    def remove_download_cache(self, space):
        def academic_ids(topic):
            return {item["id"] for run in topic["runs"] for item in run["evidence"]
                    if item["kind"] == "academic"}

        directory = self.download_directory(space)
        try:
            if directory.exists():
                shutil.rmtree(directory)
            remaining = set().union(*(academic_ids(topic) for topic in self.spaces))
            for identifier in academic_ids(space) - remaining:
                filename = sha256(identifier.encode()).hexdigest() + ".pdf"
                (directory.parent / filename).unlink(missing_ok=True)
        except OSError:
            self.window.statusBar().showMessage("部分论文缓存未能删除。")

    def switch_space(self):
        self.full_map_run = None
        self.subtask_timer.stop()
        self.subtask_cache = None
        if self.visible_space:
            self.drafts[self.visible_space["id"]] = self.composer.toPlainText()
        self.visible_space = self.selected()
        self.composer.setPlainText(self.drafts.get(self.visible_space["id"], "") if self.visible_space else "")
        self.detail_run = None
        self.discussion_space.verticalScrollBar().setValue(0)
        self.close_detail()
        self.refresh_sources()
        if self.visible_space and self.visible_space["runs"]:
            self.show_detail((self.visible_space["runs"][-1], None, None), self.trace)
        self.render()

    def refresh_sources(self):
        space = self.selected()
        self.knowledge.setVisible(space is not None)
        self.sources.clear()
        if space:
            for source in space["sources"]:
                icon = "document" if source["kind"] == "paper" else "text"
                item = QListWidgetItem(menu_symbol_icon(icon), source["title"], self.sources)
                item.setToolTip(source["title"])

    def import_papers(self):
        space = self.selected()
        if not space:
            return
        linked = {source["id"] for source in space["sources"]}
        dialog = QDialog(self)
        dialog.setWindowTitle("从论文库导入")
        dialog.resize(520, 380)
        layout = QVBoxLayout(dialog)
        choices = QTreeWidget()
        choices.setHeaderHidden(True)
        layout.addWidget(choices)
        groups = self.window.library.list_groups()
        by_group = {group["id"]: [] for group in groups}
        ungrouped = []
        for paper in self.window.library.list_metadata():
            if paper["id"] not in linked:
                by_group.get(paper["group_id"], ungrouped).append(paper)
        sections = [(group["name"], by_group[group["id"]]) for group in groups]
        sections.append(("未分组" if groups else "", ungrouped))
        checkboxes = []
        for title, papers in sections:
            parent = choices.invisibleRootItem()
            if title:
                parent = QTreeWidgetItem(choices, [f"{title}（{len(papers)}）"])
                parent.setIcon(0, menu_symbol_icon("folder"))
                parent.setExpanded(True)
            for paper in papers:
                item = QTreeWidgetItem(parent)
                check = ResearchCheckBox(paper["title"])
                check.setToolTip(paper["title"])
                choices.setItemWidget(item, 0, check)
                checkboxes.append((check, paper))
        if not checkboxes:
            layout.addWidget(QLabel("没有可添加的论文。"))
        actions = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        layout.addWidget(actions)
        if dialog.exec():
            previous = len(space["sources"])
            space["sources"].extend(dict(kind="paper", id=paper["id"], title=paper["title"])
                                    for check, paper in checkboxes if check.isChecked())
            if len(space["sources"]) != previous and not self.save():
                del space["sources"][previous:]
            self.refresh_sources()
            self.render()

    def import_local(self):
        from paperreader.services.research_import import read_knowledge_file

        space = self.selected()
        if not space:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "从本地导入", "",
            "知识库文件 (*.docx *.xlsx *.xls *.txt *.pdf *.md *.markdown *.json *.rst *.csv *.tsv *.log)")
        failures = []
        sources = list(space["sources"])
        for name in paths:
            path = Path(name)
            try:
                data = read_knowledge_file(path)
                if isinstance(data, bytes):
                    paper = self.window.library.import_pdf(data, path.stem)
                    source = dict(kind="paper", id=paper["id"], title=paper["title"])
                    if any(entry["id"] == source["id"] for entry in sources):
                        continue
                    self.window.reload(self.window.paper["id"] if self.window.paper else None, reopen=False)
                else:
                    if any(entry.get("text") == data and entry["title"] == path.name for entry in sources):
                        continue
                    source = dict(kind="text", id=uuid4().hex, title=path.name, text=data)
                sources.append(source)
            except Exception as exc:
                failures.append(f"{path.name}：{exc}")
        if sources != space["sources"]:
            previous = space["sources"]
            space["sources"] = sources
            if not self.save():
                space["sources"] = previous
            self.refresh_sources()
            self.render()
        if failures:
            self.window.error("\n".join(failures))

    def preview_source(self, item):
        self.subtask_cache = None
        source = self.selected()["sources"][self.sources.row(item)]
        self.detail_run = None
        if source["kind"] == "paper":
            self.window.open_research_paper(source["id"])
        else:
            self.trace.show_events("", "", [])
            self.content.show_text(source["title"], source["text"], "文本")
            self.select_detail_tab(self.content)
            self.detail_slot.setCurrentWidget(self.detail)

    def start(self, *, resume=None):
        space = self.selected()
        if self.active or (resume is not None and not space):
            return
        old = space["runs"][resume] if resume is not None else None
        if old and old["status"] in ("已完成", "运行中", "等待补充"):
            return
        question = old["question"] if old else self.composer.toPlainText().strip()
        if not question:
            return
        profile_id = self.models.currentData()
        profile = next((item for item in self.window.profile_config["profiles"] if item["id"] == profile_id),
                       self.window.config)
        config = dict(profile)
        if not config.get("model", "").strip():
            self.window.error("请在系统设置中配置研究使用的模型。")
            return
        plan = old["plan"] if old else ""
        academic = old.get("academic", False) if old else self.academic.isChecked()
        try:
            key = keyring.get_password("PaperReader", config.get("key_account", "api")) or ""
        except Exception:
            self.window.error("无法读取模型密钥。")
            return
        if space is None and self.spaces:
            self.topic_search.clear()
            self.space_list.setCurrentRow(len(self.spaces) - 1)
            space = self.selected()
        if space is None:
            space = dict(id=uuid4().hex, name=space_title(question), sources=[], runs=[])
            self.spaces.append(space)
            self.add_space_item(space["name"])
            self.space_list.setCurrentRow(len(self.spaces) - 1)
        sources = deepcopy(space["sources"])
        for source in sources:
            if source["kind"] == "paper":
                source["path"] = str(self.window.library.pdf_path(source))
        identifiers = [source["id"] for source in sources]
        reuse = old and old["sources"] == identifiers and old["plan"] == plan
        previous = space["runs"][:resume] if old else space["runs"]
        history = "\n".join(f"问：{run['question'][:400]}\n答：{run['answer'][-650:]}" for run in previous[-3:])
        workflow = (deepcopy(old.get("workflow")) if reuse else None) or {"phase": "规划", "tasks": []}
        if workflow["tasks"]:
            workflow["phase"] = "执行"
        run = dict(workflow=workflow, id=uuid4().hex, question=question, plan=plan, query=f"{question}\n{plan}",
                   history=history, sources=identifiers, status="运行中", answer="",
                   evidence=deepcopy(old["evidence"]) if reuse else [], scanned=old["scanned"] if reuse else 0,
                   academic=academic, academic_done=bool(reuse and old.get("academic_done")),
                   trace=[], parent=old["id"] if old else None)
        self.append_trace(run, "开始处理提问")
        space["runs"].append(run)
        if not self.save():
            space["runs"].pop()
            return
        limit = RunLimit()
        self.active = (space, run, limit)
        job = ResearchJob((deepcopy(run), sources, config, key, self.window.profile_config["theme"], limit))
        job.events.update.connect(self.on_event, Qt.ConnectionType.QueuedConnection)
        if resume is None:
            self.composer.clear()
        self.detail_run = (run, None, None)
        self.select_detail_tab(self.trace)
        self.detail_slot.setCurrentWidget(self.detail)
        self.window.pool.start(job)
        self.render()

    @staticmethod
    def append_trace(run, message):
        run["trace"].append([datetime.now().isoformat(timespec="seconds"), message])

    def send_or_stop(self):
        if self.active:
            self.stop_run()
        else:
            self.start()

    def stop_run(self):
        if self.active:
            self.active[2].stop.set()
            self.render()

    @Slot(str, object)
    def on_event(self, kind, value):
        space, run, limit = self.active
        if kind == "chunk":
            return
        if kind == "workflow":
            run["workflow"], run["evidence"] = value
        elif kind == "checkpoint":
            run["evidence"] = value
            run["scanned"] += 1
        elif kind == "academic":
            run["evidence"] = value
            run["academic_done"] = True
        elif kind == "trace":
            self.append_trace(run, value)
        elif kind == "full_mindmap":
            run["full_mindmap"] = value
        elif kind == "done":
            status, answer = value
            if limit.stop.is_set():
                status, answer = "已停止", ""
            run["status"] = status
            if status in ("已停止", "失败", "达到时间上限") and run.get("workflow"):
                for task in run["workflow"]["tasks"]:
                    if task["status"] == "执行中":
                        task["status"] = status
            run["answer"] = answer or run["answer"]
            self.append_trace(run, status)
            self.active = None
            if (answer and not run.get("workflow", {}).get("tasks") and self.selected() is space
                    and self.detail_run == (run, None, None) and self.tabs.currentWidget() is self.trace
                    and self.detail_slot.currentWidget() is self.detail):
                self.show_detail((run, None, "answer"), self.content)
        self.save()
        if kind == "trace":
            if self.selected() is space and self.work_tabs.currentIndex() == 0:
                self.update_subtasks(run, len(space["runs"]) - 1)
            if (self.detail_run and self.detail_run[0] is run and self.detail_slot.currentWidget() is self.detail
                    and self.tabs.currentWidget() is self.trace):
                self.render_trace(run)
        elif self.selected() is space or kind == "done":
            self.render()

    def switch_work_tab(self):
        space = self.selected()
        runs = space["runs"] if space else []
        self.update_task_header(runs[-1] if runs else None)
        self.render_chat()

    def render(self):
        space = self.selected()
        runs = space["runs"] if space else []
        here = bool(self.active and self.active[0] is space)
        stopping = bool(self.active and self.active[2].stop.is_set())
        self.send.setText("正在停止…" if stopping else "停止 ■" if self.active else "发送 ↑")
        self.send.setEnabled(not stopping)
        status = runs[-1]["status"] if runs else ""
        if here:
            status = "正在停止…" if self.active[2].stop.is_set() else "Agent 正在研究…"
        elif self.active:
            status = "其他空间正在运行"
        self.status.setText(status)
        self.update_task_header(runs[-1] if runs else None)
        self.render_chat()
        if self.detail_run and self.detail_slot.currentWidget() is self.detail:
            self.render_detail()

    def update_task_header(self, run):
        state = run.get("workflow") if run else None
        discussion = self.work_tabs.currentIndex() == 0
        show_task = run is not None
        self.task_header.setVisible(discussion and show_task)
        self.subtask_overview.setVisible(bool(discussion and state and state.get("tasks")))
        self.evidence_overview.setVisible(bool(discussion and run and (run["evidence"] or (state and state.get("tasks")))))
        if not show_task:
            return
        state = state or {}
        phase = state.get("phase", "")
        tasks = state.get("tasks", [])
        finished = sum(task["status"] == "已完成" for task in tasks)
        if phase == "执行":
            stage = 2 if run["evidence"] or finished else 1
            progress = 20 + int(50 * finished / max(1, len(tasks)))
        else:
            stage, progress = {"规划": (0, 0), "总结": (3, 78), "制图": (4, 90),
                               "完成": (5, 100)}.get(phase, (-1, 0))
        goal = state.get("goal") or run["question"]
        mindmap = self.mindmap_for(run)
        title = mindmap["title"] if mindmap else space_title(goal)
        self.task_title.setText(title)
        subtitle = goal if goal != title else ""
        self.task_subtitle.setText(subtitle[:160] + ("…" if len(subtitle) > 160 else ""))
        self.task_subtitle.setToolTip(escape(goal))
        self.task_subtitle.setVisible(bool(subtitle))
        self.task_steps.set_step(stage)
        self.task_percentage.setText(f"{progress}%" if stage >= 0 else "")
        if run["status"] == "运行中":
            self.status.setText("进行中 · " + (ResearchProgress.STAGES[stage] if 0 <= stage < 5 else phase))
        index = len(self.selected()["runs"]) - 1
        self.task_trace.setText(link("查看 Trace", f"research-trace:{index}"))
        actions = []
        if not self.active and run["status"] not in ("已完成", "运行中", "等待补充"):
            actions.append(link("续跑", f"research-resume:{index}"))
        if run["answer"]:
            if not tasks:
                actions.append(link("查看回答", f"research-answer:{index}"))

        self.task_actions.setText("　".join(actions))
        self.task_actions.setVisible(bool(actions))
        if discussion:
            self.update_subtasks(run, index)
            self.evidence_overview.set_evidence(index, run["evidence"])

    def update_subtasks(self, run, index):
        tasks = run.get("workflow", {}).get("tasks", [])
        latest = run["trace"][-1][1].partition(" · ")[0] if run["trace"] else ""
        activity = latest if latest and latest not in ("任务规划", "执行子任务") else "正在执行子任务"
        if not any(task["status"] == "执行中" for task in tasks):
            activity = ""
        self.subtask_overview.set_tasks(index, tasks, activity)

    @staticmethod
    def mindmap_for(run):
        state = run.get("workflow", {})
        if state.get("mindmap"):
            return state["mindmap"]
        if state.get("diagram"):
            labels = [task["title"] for task in state.get("tasks", [])] or state["diagram"]
            return dict(title=space_title(state.get("goal") or run["question"])[:18],
                        branches=[dict(label=label[:20], points=[]) for label in labels[:4]])
        return None

    @staticmethod
    def mindmap_card(mindmap):
        return ("研究思维脑图", mindmap, False, f"{len(mindmap['branches'])} 个分支", "", False)

    @staticmethod
    def discussion_card(symbol, title, content):
        panel = QWidget()
        panel.setObjectName("ResearchOverview")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 8, 12, 10)
        row = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(menu_symbol_icon(symbol).pixmap(18, 18))
        row.addWidget(icon)
        row.addWidget(heading(title), 1)
        layout.addLayout(row)
        layout.addWidget(content)
        return panel

    def open_full_mindmap(self):
        self.work_tabs.setCurrentIndex(2)
        self.render_chat(retry_map=True)

    def ensure_full_mindmap(self, run, *, retry=False):
        identifier = run["id"]
        if (run.get("full_mindmap") or identifier in self.full_map_pending
                or (identifier in self.full_map_error and not retry)):
            self.render_full_mindmap()
            return
        config = next((profile for profile in self.window.profile_config["profiles"]
                       if profile["id"] == self.models.currentData()), self.window.config)
        try:
            if not config.get("model", "").strip():
                raise ValueError("请先配置模型。")
            key = keyring.get_password("PaperReader", config.get("key_account", "api")) or ""
        except Exception:
            self.full_map_error[identifier] = "请检查模型配置和 API 密钥后重试。"
            self.render_full_mindmap()
            return
        self.full_map_error.pop(identifier, None)
        limit = RunLimit()
        self.full_map_pending[identifier] = limit
        job = MindmapJob(run, dict(config), key, limit)
        job.events.update.connect(self.finish_full_mindmap, Qt.ConnectionType.QueuedConnection)
        self.window.pool.start(job)
        self.render_full_mindmap()

    @Slot(str, object)
    def finish_full_mindmap(self, _kind, value):
        run, result, error = value
        identifier = run["id"]
        self.full_map_pending.pop(identifier, None)
        if not any(run is item for space in self.spaces for item in space["runs"]):
            return
        if result:
            run["full_mindmap"] = result
            if not self.save():
                self.full_map_error[identifier] = "脑图已生成，本地保存失败。"
        elif error:
            self.full_map_error[identifier] = error
        if self.full_map_run is run:
            self.render_full_mindmap()

    def render_full_mindmap(self):
        run = self.full_map_run
        if run is None:
            return
        identifier = run["id"]
        pending = identifier in self.full_map_pending
        root = run.get("full_mindmap")
        error = self.full_map_error.get(identifier, "")
        self.full_map_status.setText("正在根据最终结论生成多级脑图…" if pending else error or "完整思维脑图")
        self.full_map_retry.setVisible(bool(error and not root and not pending))
        self.full_map_canvas.set_mindmap(root)

    def render_discussion(self, space):
        runs = space["runs"] if space else []
        run = runs[-1] if runs else None
        mindmap = self.mindmap_for(run) if run else None
        self.discussion_mindmap_card.setVisible(bool(mindmap))
        self.discussion_mindmap.set_mindmap(mindmap)
        self.full_map_button.setEnabled(bool(run and run.get("answer")))
        show_summary = bool(run and run["status"] not in ("运行中", "等待补充"))
        self.discussion_summary_card.setVisible(show_summary)
        if show_summary:
            status = run["status"]
            answer = run["answer"]
            actions = ""
            state = run.get("workflow", {})
            if status in ("已完成", "部分完成") and answer:
                sentences = []
                for line in answer.splitlines():
                    clean = re.sub(r"^[#>*\-\s]+", "", line).strip()
                    if clean and not line.lstrip().startswith(("#", "`", "|")):
                        sentences.append(clean)
                    if sum(map(len, sentences)) >= 140:
                        break
                summary = " ".join(sentences) or answer
                summary = re.sub(r"[*_`]+", "", summary)
                if state.get("phase") == "完成":
                    index = len(runs) - 1
                    actions = link("查看最终结论 ›", f"research-conclusion:{index}")
            else:
                fallback = {"已停止": "研究运行已手动停止。", "达到时间上限": "研究未能在运行时间上限内完成。",
                            "已中断": "应用退出时研究尚未完成。"}
                summary = next((message for _, message in reversed(run["trace"])
                                if message != status and any(word in message for word in ("失败", "超时", "未完成"))),
                               fallback.get(status, "研究未生成可用结论，可查看执行追踪了解失败阶段。"))
            excerpt = summary[:180].strip() + ("…" if len(summary) > 180 else "")
            self.discussion_summary_card.findChild(QLabel, "PanelTitle").setText("最终结论" if actions else "任务总结")
            self.discussion_summary.setText(
                f"<p><b>{escape(status)}</b></p><p>{plain(excerpt)}</p>" +
                (f"<p>{actions}</p>" if actions else ""))

    def render_chat(self, *, retry_map=False):
        space = self.selected()
        blocks = []
        tab = self.work_tabs.currentIndex()
        full_map = tab == 2
        if full_map:
            self.full_map_run = next((run for run in reversed(space["runs"])
                                      if run.get("answer") or run.get("full_mindmap")), None) if space else None
        self.full_map_panel.setVisible(full_map)
        self.chat.setVisible(tab == 4)
        self.evidence_matrix.setVisible(tab == 1)
        self.conclusions.setVisible(tab == 3)
        self.discussion_space.setVisible(tab == 0)
        if full_map:
            if self.full_map_run is not None:
                self.ensure_full_mindmap(self.full_map_run, retry=retry_map)
            else:
                self.full_map_status.setText("研究生成最终结论后将在这里显示完整脑图。")
                self.full_map_retry.hide()
                self.full_map_canvas.set_mindmap(None)
            return
        if tab == 0:
            self.render_discussion(space)
            return
        if tab == 1:
            self.evidence_matrix.set_entries([
                (f"E{number} · {source['title']}", source["text"][:180], position(source),
                 f"research-content:{index}-{number}")
                for index, run in enumerate(space["runs"] if space else [])
                for number, source in enumerate(run["evidence"], 1)
            ])
            return
        for index, run in enumerate(space["runs"] if space else []):
            state = run.get("workflow", {})
            if tab == 3:
                if state.get("phase") == "完成" and run["answer"]:
                    key = (run["id"], index)
                    cached = self.conclusion_cache.get(key)
                    if not cached or cached[0] != run["answer"]:
                        answer = CITATION.sub(
                            lambda match: f"[{match[0]}](research-content:{index}-{match[1]})", run["answer"])
                        answer = conclusion_markdown(answer)
                        self.conclusion_cache[key] = (run["answer"], answer)
                    else:
                        answer = cached[1]
                    actions = link("查看引用", f"research-content:{index}")
                    blocks.append(("最终结论", answer, True, run["status"], actions, True))
                continue
            if tab == 4:
                blocks.append((run["question"][:90], "", False, run["status"],
                               link("打开执行 Trace ›", f"research-trace:{index}"), True))
                continue
        empty = ("直接提问即可开始。没有研究空间时，将用首条消息创建空间。"
                 if not space else "向研究 Agent 提问，也可以添加资料或开启学术检索。")
        if tab:
            empty = ("", "暂无可展示的证据。", "研究完成后将在这里显示思维脑图。", "暂无最终结论。研究总结完成后将在这里显示。", "暂无执行记录。")[tab]
        view = self.conclusions if tab == 3 else self.chat
        view.anchor_prefix = "research-content:" if tab == 1 else ""
        view.show_cards(blocks, empty)

    def open_detail(self, url):
        scheme = url.scheme()
        if scheme not in ("research-content", "research-trace", "research-export",
                          "research-resume", "research-subtask", "research-conclusion", "research-answer"):
            return
        index, _, reference = url.path().partition("-")
        space = self.selected()
        if not space or not index.isdigit() or int(index) >= len(space["runs"]):
            return
        index = int(index)
        run = space["runs"][index]
        if scheme == "research-conclusion":
            self.work_tabs.setCurrentIndex(3)
        elif scheme == "research-export":
            self.export_report(run)
        elif scheme == "research-resume":
            self.start(resume=index)
        elif scheme == "research-subtask":
            tasks = run.get("workflow", {}).get("tasks", [])
            if reference.isdigit() and 0 < int(reference) <= len(tasks):
                self.show_detail((run, None, int(reference) - 1), self.content)
        elif scheme == "research-answer":
            self.show_detail((run, None, "answer"), self.content)
        else:
            pane = self.trace if scheme == "research-trace" else self.content
            self.show_detail((run, int(reference) if reference.isdigit() else None, None), pane)

    def show_detail(self, selection, pane):
        if self.detail_run != selection:
            self.subtask_cache = None
            self.subtask_timer.stop()
            self.detail_run = selection
        self.detail_slot.setCurrentWidget(self.detail)
        already_current = self.tabs.currentWidget() is pane
        self.select_detail_tab(pane)
        if already_current:
            self.render_detail()

    def refresh_detail_tab(self):
        if self.detail_run and self.detail_slot.currentWidget() is self.detail:
            self.render_detail()

    def toggle_trace(self, index):
        if not self.detail_run:
            return
        run = self.detail_run[0]
        key = (run["id"], index)
        if key in self.expanded_trace:
            self.expanded_trace.remove(key)
        else:
            self.expanded_trace.add(key)
        self.render_trace(run)

    def render_trace(self, run):
        events = []
        last = len(run["trace"]) - 1
        for index, (timestamp, message) in enumerate(run["trace"]):
            stage, _, details = message.partition(" · ")
            active = run["status"] == "运行中" and index == last
            terminal = index == last and not active and run["status"] != "已完成"
            pieces = details.split(" · ") if details else []
            elapsed = ""
            if pieces and pieces[-1].endswith(" 秒"):
                duration = pieces.pop()
                try:
                    seconds = float(duration.removesuffix(" 秒"))
                    elapsed = f"{seconds * 1000:.0f} ms" if seconds < 1 else f"{seconds:g} s"
                except ValueError:
                    elapsed = duration
            symbol = "trace"
            for keyword, candidate in (("核对", "shield"), ("检索", "research"), ("读取", "library"),
                                       ("规划", "clipboard"), ("生成", "flow"), ("总结", "flow")):
                if keyword in stage:
                    symbol = candidate
                    break
            if stage == "生成回答" and pieces:
                stage = "模型分析 · " + pieces.pop(0)
            details = " · ".join(pieces)
            expanded = (run["id"], index) in self.expanded_trace
            events.append((stage, timestamp[11:], elapsed, details, expanded, symbol, active, terminal))
        self.trace.show_events(f"Run {run['id'][:8]}", run["status"], events,
                               run["trace"][0][0] if events else "", run["trace"][-1][0] if events else "")

    def export_trace(self):
        if not self.detail_run:
            return
        run = self.detail_run[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 Trace", f"trace-{run['id'][:8]}.json", "JSON (*.json)")
        if not path:
            return
        payload = {"run_id": run["id"], "status": run["status"], "question": run["question"],
                   "events": [{"timestamp": stamp, "message": message} for stamp, message in run["trace"]]}
        try:
            Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            self.window.error(f"无法导出 Trace：{exc}")

    def render_detail(self):
        run, reference, subtask = self.detail_run
        if self.tabs.currentWidget() is self.pdf_panel:
            return
        if self.tabs.currentWidget() is self.trace:
            self.render_trace(run)
            return
        if subtask == "answer":
            self.content.show_cards([("研究 Agent", run["answer"], True, run["status"], "", True)])
            return
        if subtask is not None:
            if self.subtask_cache is self.detail_run:
                return
            if not self.subtask_timer.isActive():
                self.content.show_cards([], "正在加载子任务结果…")
                self.subtask_timer.start()
            return
        entries = []
        for index, source in enumerate(run["evidence"], 1):
            if reference is not None and index != reference:
                continue
            action = ""
            if source["kind"] == "academic":
                actions = [link("在浏览器中打开", f"research-browser:{index}")]
                if self.download_path(source, existing=True).is_file():
                    actions.extend((link("预览", f"research-preview:{index}"),
                                    link("在阅读列表打开", f"research-reader:{index}")))
                else:
                    actions.append(link("下载到本地", f"research-download:{index}"))
                action = "　　".join(actions)
            elif source["kind"] == "paper":
                action = "　　".join((link("预览", f"research-pdf:{index}"),
                                     link("在阅读列表打开", f"research-paper-reader:{index}")))
            entries.append((f"E{index} · {source['title']}", f"<p>{plain(source['text'])}</p>",
                            False, position(source), action, reference is not None))
        self.content.show_cards(entries, "暂无可定位证据。")

    def render_subtask(self):
        if not self.detail_run or self.detail_slot.currentWidget() is not self.detail or self.tabs.currentWidget() is not self.content:
            return
        run, _, subtask = self.detail_run
        if not isinstance(subtask, int):
            return
        task = run["workflow"]["tasks"][subtask]
        index = self.selected()["runs"].index(run)
        answer = CITATION.sub(lambda match: f"[{match[0]}](research-content:{index}-{match[1]})", task["answer"])
        answer = conclusion_markdown(answer)
        self.content.show_cards([(task["title"], answer, True, task["status"], "", True)])
        self.subtask_cache = self.detail_run

    def open_pdf(self, url):
        if url.scheme() == "research-content":
            self.open_detail(url)
            return
        scheme = url.scheme()
        if scheme not in ("research-pdf", "research-browser", "research-download",
                          "research-preview", "research-reader", "research-paper-reader") or not self.detail_run or not url.path().isdigit():
            return
        evidence = self.detail_run[0]["evidence"]
        index = int(url.path()) - 1
        if not 0 <= index < len(evidence):
            return
        source = evidence[index]
        if source["kind"] == "paper":
            if scheme == "research-pdf":
                self.open_inline_pdf(source, local=True)
            elif scheme == "research-paper-reader":
                self.window.open_research_paper(source["id"], source["page"], source.get("rects", ()))
        elif source["kind"] == "academic":
            if scheme == "research-browser":
                target = QUrl(source["url"])
                if target.scheme() == "https" and target.host():
                    QDesktopServices.openUrl(target)
            elif scheme == "research-download":
                self.begin_download(source)
            elif scheme == "research-preview":
                self.open_inline_pdf(source)
            elif scheme == "research-reader":
                try:
                    data = self.download_path(source, existing=True).read_bytes()
                    paper = self.window.library.import_pdf(data, source["title"], source["url"])
                    self.window.open_research_paper(paper["id"])
                except (OSError, RuntimeError, ValueError) as exc:
                    self.window.error(f"无法导入阅读列表：{exc}")

    def set_download_status(self, message):
        self.download_status.setText(message)
        self.download_status.show()

    def begin_download(self, source):
        if self.pdf_download_only and (self.pdf_request is not None or
                                       (self.pdf_downloader and self.pdf_downloader.current is not None)):
            return
        if self.download_path(source, existing=True).is_file():
            self.download_ready()
            return
        target = QUrl(source["url"])
        if target.scheme() != "https" or not target.host():
            self.set_download_status("下载失败，论文链接无效。")
            return
        self.clear_pdf()
        self.pdf_download_only = True
        self.pdf_source = dict(source)
        self.pdf_target = self.download_path(source)
        try:
            self.pdf_target.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.set_download_status("下载失败，无法创建本地缓存目录。")
            return
        self.set_download_status("正在查找 PDF 下载地址…")
        if (source["id"].lower().startswith(("10.2139/ssrn.", "10.20944/preprints"))
                or target.host() in ("www.preprints.org", "preprints.org", "papers.ssrn.com")):
            self.start_browser_download(source)
            return
        token = self.pdf_request = object()
        job = ResearchPDFJob(token, source, False, lambda progress: download_citation_pdf(
            source, progress=progress), report_progress=True)
        job.events.update.connect(self.finish_inline_pdf, Qt.ConnectionType.QueuedConnection)
        self.window.pool.start(job)

    def open_inline_pdf(self, source, *, local=False):
        self.clear_pdf()
        self.pdf_download_only = False
        self.pdf_status.setText("正在加载 PDF…")
        self.pdf_status.show()
        self.pdf_view.hide()
        self.tabs.addTab(self.pdf_panel, menu_symbol_icon("document"), "PDF")
        self.tabs.setCurrentWidget(self.pdf_panel)
        self.detail_slot.setCurrentWidget(self.detail)
        token = self.pdf_request = object()
        path = self.window.library.pdf_path(source) if local else self.download_path(source, existing=True)
        job = ResearchPDFJob(token, source, local, path.read_bytes)
        job.events.update.connect(self.finish_inline_pdf, Qt.ConnectionType.QueuedConnection)
        self.window.pool.start(job)

    @Slot(str, object)
    def finish_inline_pdf(self, kind, result):
        if kind == "progress":
            token, size, total = result
            if token is self.pdf_request:
                message = f"正在下载 PDF · {size / 1048576:.1f} MB"
                if total:
                    message += f" / {total / 1048576:.1f} MB"
                self.set_download_status(message)
            return
        token, source, local, data = result
        if token is not self.pdf_request:
            return
        self.pdf_request = None
        document = None
        if isinstance(data, bytes) and data:
            try:
                document = fitz.open(stream=data, filetype="pdf")
                if document.needs_pass or not len(document):
                    raise ValueError("PDF 无法阅读")
                if self.pdf_download_only:
                    document.close()
                    document = None
                    self.pdf_target.parent.mkdir(parents=True, exist_ok=True)
                    temp = self.pdf_target.with_name(uuid4().hex + ".part")
                    try:
                        temp.write_bytes(data)
                        temp.replace(self.pdf_target)
                    except OSError:
                        self.set_download_status("下载失败，无法保存 PDF。")
                        return
                    finally:
                        temp.unlink(missing_ok=True)
                    self.download_ready()
                    return
                self.pdf_view.set_follow_theme(self.window.profile_config["pdf_follow_theme"])
                width = max(100, self.pdf_panel.width() - 34)
                self.pdf_view.scale = width / document[0].rect.width
                self.pdf_view.load(document, source.get("page", 0))
                self.pdf_document = document
                self.pdf_view.show()
                self.pdf_status.hide()
                if local and source.get("rects"):
                    self.pdf_view.show_citation(source["page"], source["rects"])
                return
            except (OSError, RuntimeError, ValueError):
                self.pdf_view.clear_document()
                if document is not None:
                    document.close()
                self.pdf_document = None
        if self.pdf_download_only:
            self.start_browser_download(source)
        else:
            self.pdf_status.setText("原文 PDF 无法读取。")

    def start_browser_download(self, source):
        if self.pdf_downloader is None:
            from paperreader.ui.research_download import ResearchDownload
            self.pdf_downloader = ResearchDownload(self.window.library.root, self.pdf_panel)
            self.pdf_downloader.hide()
            self.pdf_downloader.ready.connect(self.browser_pdf_ready)
            self.pdf_downloader.status_changed.connect(self.set_download_status)
            self.pdf_downloader.failed.connect(self.set_download_status)
        self.pdf_downloader.start(source, self.pdf_target)

    @Slot(object)
    def browser_pdf_ready(self, path):
        source = self.pdf_source
        if (source is None or Path(path) != self.pdf_target
                or self.detail_slot.currentWidget() is not self.detail):
            return
        self.download_ready()

    def download_ready(self):
        self.clear_pdf()
        self.select_detail_tab(self.content)
        self.refresh_detail_tab()
        self.set_download_status("PDF 已下载到本地。")

    def export_report(self, run):
        space = self.selected()
        if not space:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出研究报告", "research.md", "Markdown (*.md)")
        if not path:
            return
        sections = [f"# {space['name']}"]
        sections.append(f"## {run['question']}\n\n{run['status']}")
        state = run.get("workflow", {})
        for task in state.get("tasks", []):
            sections.append(f"### {task['title']}\n\n{task['question']}\n\n{task['answer']}")
        mindmap = self.mindmap_for(run)
        if mindmap:
            outline = ["### 研究思维脑图", mindmap["title"]]
            for branch in mindmap["branches"]:
                outline.append(f"- {branch['label']}")
                outline.extend(f"  - {point}" for point in branch["points"])
            sections.append("\n".join(outline))
        sections.append(f"### 回答\n\n{run['answer']}")
        if "draft" in run:
            sections.append(f"### 结论草稿\n\n{run['draft']}")
        sections.append("### 证据")
        for index, source in enumerate(run["evidence"], 1):
            if source["kind"] == "academic":
                position = f"学术元数据 · {source['url']}"
            elif source["kind"] == "paper":
                position = f"PDF 第 {source['page'] + 1} 页"
            else:
                position = f"第 {source['line']} 行"
            sections.append(f"- 【E{index}】{source['title']} · {position}\n\n{source['text']}")
        try:
            Path(path).write_text("\n\n".join(sections) + "\n", encoding="utf-8")
        except OSError as exc:
            self.window.error(str(exc))
