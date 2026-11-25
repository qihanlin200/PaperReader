from datetime import datetime
import json
from html import escape
from pathlib import Path
from threading import Event
from urllib.parse import urlsplit
import uuid
from paperreader.services.lazy import fitz
from paperreader.services.lazy import keyring
from PySide6.QtCore import QObject, QPoint, QRunnable, QSize, QThreadPool, Signal, QSignalBlocker, QTimer, QUrl, QUrlQuery
from PySide6.QtGui import QIcon, QImage, QPixmap, QShortcut, QTextCursor
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QListView, QListWidget, QSplitter, QScrollArea, QTextBrowser, QTextEdit, QLineEdit, QLabel,
    QFileDialog, QInputDialog, QMessageBox, QDialog, QDialogButtonBox, QTabWidget, QStackedWidget, QApplication, QComboBox, QMenu, QProgressBar, QProgressDialog, QSpacerItem, QSizePolicy, QFrame, QButtonGroup)
from PySide6.QtCore import Qt
from paperreader.services.library import Library
from paperreader.services.network import complete, download
from paperreader.logger import get_logger
from paperreader.ui.reading_home import ContentButton, ReadingHome
from paperreader.ui.pdf import ContinuousPDF
from paperreader.ui.markdown import ChatBrowser, MarkdownBrowser, MarkdownEditor, link_analysis_pages, replace_citations
from paperreader.ui.paper_figures import FIGURE_REFERENCE, FIGURE_INSERT, figure_index, figure_excerpt, insert_figure_markers
from paperreader.ui.figure_preview import FigurePreview
from paperreader.ui.breathing import AnalysisBreathingFrame
from paperreader.ui.outline import AnalysisOutline
from paperreader.ui.paper_list import PaperList, PAPER_ID_ROLE, GROUP_ID_ROLE, MACOS
from paperreader.ui.splitter import ChatVerticalSplitter, PaneSplitter
from paperreader.ui.view_modes import ViewModeButton
from paperreader.ui.window_parts.jobs import Job
from paperreader.ui.window_parts.papers import PapersMixin
from paperreader.ui.window_parts.pdf_reading import PdfReadingMixin
from paperreader.ui.window_parts.followup import FollowupMixin
from paperreader.ui.window_parts.sessions_notes import SessionsNotesMixin
from paperreader.ui.window_parts.themes import ThemesMixin
from paperreader.ui.work_rail import WorkRailButton, menu_symbol_icon
from paperreader.services.themes import THEMES, get_theme
from paperreader.ui.theme import ThemeHeader, WorkspaceBackground, apply_theme
from paperreader.ui.typography import resize_fixed_text_controls, valid_font, valid_size
from paperreader.ui.settings import SettingsDialog, open_settings, build_model_settings
from paperreader.ui.composer import QuestionEdit
from paperreader.ui.questions import QuestionNavigation
from paperreader.ui.request_status import RequestStatus
from paperreader.ui.math_render import markdown_html
from paperreader.services.sessions import ensure_sessions, create_session
from paperreader.services.retrieval import CITATION, Passage, PassageIndex, asks_about_assistant
from paperreader.services.persona import assistant_name, with_persona
from paperreader.services.analysis import run_analysis, split_deep_response, supports_keyword
import json
from paperreader.services.profiles import normalize_profiles, active_profile


log = get_logger(__name__)






class ElidedLabel(QLabel):
    """Keep the full paper title available while fitting the reader header."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.full_text = ""
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set_full_text(self, text):
        self.full_text = text
        self.setToolTip(text)
        self.update_elision()

    def update_elision(self):
        self.setText(self.fontMetrics().elidedText(self.full_text, Qt.TextElideMode.ElideRight,
                                                   max(0, self.contentsRect().width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_elision()




class Window(PapersMixin, PdfReadingMixin, FollowupMixin, SessionsNotesMixin, ThemesMixin, QMainWindow):
    def __init__(self, library=None):
        super().__init__()
        self.library = library if library is not None else Library()
        saved_config = self.library.config()
        self.profile_config = normalize_profiles(saved_config)
        self.profile_config["theme"] = get_theme(saved_config.get("theme")).identifier
        from paperreader.research_agent.search import SEARCH_ENGINES
        engine = saved_config.get("brightdata_engine", "bing")
        self.profile_config["brightdata_engine"] = engine if engine in SEARCH_ENGINES else "bing"
        self.profile_config["font_family"] = valid_font(saved_config.get("font_family"))
        self.profile_config["font_size"] = valid_size(saved_config.get("font_size"))
        apply_theme(self.profile_config["theme"], self.profile_config["font_family"],
                    self.profile_config["font_size"])
        self.setWindowIcon(QApplication.instance().windowIcon())
        self.config = active_profile(self.profile_config)
        self.paper = None; self.doc = None; self.page = 0; self.quote = ""; self.busy = False
        self.passage_index = None
        self.quote_passage = None
        self.analysis_cancel = None
        self.chat_cancel = None
        self.pool = QThreadPool.globalInstance()
        self.summary_drafts = {}
        self.chat_drafts = {}
        self.collapsed_groups = set()
        self.search_collapsed_groups = set()
        self.setWindowTitle("PaperReader · 读起来不烧心"); self.resize(1500, 920)
        root = WorkspaceBackground(); self.setCentralWidget(root)
        layout = QVBoxLayout(root); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)

        def button(text, fn, style="Quiet"):
            widget = QPushButton(text); widget.setObjectName(style); widget.clicked.connect(fn)
            return widget

        def header(title, caption=""):
            widget = QWidget(); widget.setObjectName("PanelHeader"); widget.setFixedHeight(49)
            row = QHBoxLayout(widget); row.setContentsMargins(14, 0, 14, 0)
            label = QLabel(title); label.setObjectName("PanelTitle"); row.addWidget(label)
            row.addStretch()
            if caption:
                sub = QLabel(caption); sub.setObjectName("AccentLabel"); row.addWidget(sub)
            return widget, row

        top = ThemeHeader(); self.top_bar = top
        bar = QHBoxLayout(top); bar.setContentsMargins(18, 8, 16, 8); bar.setSpacing(12)
        brand = ContentButton(); brand.setObjectName("BrandMark")
        brand.setAccessibleName("返回阅读首页")
        brand.clicked.connect(self.show_reading_home)
        brand_row = QHBoxLayout(brand); brand_row.setContentsMargins(0, 0, 0, 0); brand_row.setSpacing(7)
        self.brand_icon = QLabel(); self.brand_icon.setFixedSize(24, 24)
        brand_row.addWidget(self.brand_icon)
        brand_label = QLabel("PaperReader"); brand_label.setObjectName("BrandLabel")
        brand_row.addWidget(brand_label)
        for child in (self.brand_icon, brand_label):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        bar.addWidget(brand)
        bar.addStretch()
        layout.addWidget(top)
        body = QWidget(); body.setObjectName("MainBody")
        body_row = QHBoxLayout(body); body_row.setContentsMargins(0, 0, 0, 0); body_row.setSpacing(0)
        rail = QWidget(); rail.setObjectName("WorkRail"); rail.setFixedWidth(48)
        rail_layout = QVBoxLayout(rail); rail_layout.setContentsMargins(5, 16, 5, 12); rail_layout.setSpacing(10)
        self.library_rail_button = WorkRailButton("library", "收起论文列表；再次点击展开")
        self.library_rail_button.clicked.connect(self.toggle_library)
        self.library_rail_button.set_active(True)
        rail_layout.addWidget(self.library_rail_button)
        self.research_rail_button = WorkRailButton("research", "研究模式")
        self.research_rail_button.clicked.connect(self.toggle_research)
        rail_layout.addWidget(self.research_rail_button)
        self.skills_rail_button = WorkRailButton("skills", "技能库")
        self.skills_rail_button.clicked.connect(self.toggle_skills)
        rail_layout.addWidget(self.skills_rail_button)
        self.research_workspace = None
        self.skill_library = None
        rail_layout.addStretch()
        self.settings_rail_button = WorkRailButton("settings", "系统设置")
        self.settings_rail_button.clicked.connect(self.settings)
        rail_layout.addWidget(self.settings_rail_button)
        self.work_rail = rail
        body_row.addWidget(rail)
        split = PaneSplitter(); self.splitter = split
        self.reading_content = QStackedWidget()
        self.reading_splitter = PaneSplitter()
        self.reading_content.addWidget(self.reading_splitter)
        self.workspace_stack = QStackedWidget()
        self.workspace_stack.addWidget(split)
        body_row.addWidget(self.workspace_stack, 1)
        layout.addWidget(body, 1)
        split.splitterMoved.connect(self.sync_library_rail)
        split.paneToggled.connect(self.sync_library_rail)

        library = QWidget(); library.setObjectName("LibraryPanel")
        library.setMinimumWidth(220); library.setMaximumWidth(280)
        self.library_panel = library
        ll = QVBoxLayout(library); ll.setContentsMargins(12, 18, 12, 12); ll.setSpacing(10)
        search_row = QHBoxLayout(); search_row.setContentsMargins(0, 0, 0, 0); search_row.setSpacing(6)
        self.paper_search = QLineEdit(); self.paper_search.setObjectName("PaperSearch")
        self.paper_search.setPlaceholderText("搜索我的论文…")
        self.paper_search.setClearButtonEnabled(True)
        self.paper_search.setFixedHeight(38)
        self.paper_search.setToolTip("输入标题或来源关键词，实时筛选论文")
        self.paper_search.textChanged.connect(self.search_papers)
        search_row.addWidget(self.paper_search, 1, Qt.AlignmentFlag.AlignVCenter)
        self.library_add_button = button("＋", self.show_library_add_menu, "AddPaperGroup")
        self.library_add_button.setToolTip("导入论文或创建分组")
        self.library_add_button.setAccessibleName("导入论文或创建分组")
        self.library_add_button.setFixedSize(38, 38)
        search_row.addWidget(self.library_add_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.library_add_menu = QMenu(self)
        self.library_add_menu.setObjectName("LibraryAddMenu")
        for label, symbol, handler in (
            ("本地论文导入", "pdf", self.import_file),
            ("网页链接导入", "link", self.import_link),
            ("创建分组", "group", self.create_paper_group),
        ):
            action = self.library_add_menu.addAction(label)
            action.setData(symbol)
            action.triggered.connect(handler)
        ll.addLayout(search_row)
        self.list = PaperList()
        self.list.favoriteRequested.connect(self.favorite_paper_at_row)
        self.list.paperDropped.connect(self.drop_papers_into_group)
        self.list.groupDropped.connect(self.reorder_paper_group)
        self.list.setWordWrap(False); self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight); self.list.currentRowChanged.connect(self.open_paper);
        self.list.itemClicked.connect(self.toggle_group_item)
        self.list.itemDoubleClicked.connect(lambda item: self.open_paper(self.list.row(item)))
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.paper_context_menu); ll.addWidget(self.list, 1)
        split.addWidget(library)

        reader = QWidget(); reader.setObjectName("ReaderPanel")
        reader.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        rl = QVBoxLayout(reader); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(0)
        head, reader_head = header("原文预览", "PDF")
        self.reader_title_divider = QLabel("·"); self.reader_title_divider.setObjectName("ReaderTitleDivider")
        self.reader_title_divider.hide(); reader_head.insertWidget(1, self.reader_title_divider)
        self.reader_paper_title = ElidedLabel(); self.reader_paper_title.setObjectName("ReaderPaperTitle")
        reader_head.insertWidget(2, self.reader_paper_title, 1)
        rl.addWidget(head)
        nav_widget = QWidget(); nav = QHBoxLayout(nav_widget); nav.setContentsMargins(10, 6, 10, 6); nav.setSpacing(5)
        nav.addWidget(button("‹", lambda: self.turn(-1), "NavButton"))
        page_counter = QWidget()
        page_counter.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        page_counter_layout = QHBoxLayout(page_counter)
        page_counter_layout.setContentsMargins(0, 0, 0, 0)
        page_counter_layout.setSpacing(4)
        self.pdf_page_input = self.pdf_number_input("当前页码", 42, self.apply_pdf_page)
        self.pdf_page_input.setPlaceholderText("—")
        self.pdf_page_input.setEnabled(False)
        page_counter_layout.addWidget(self.pdf_page_input)
        self.page_label = QLabel("/ —")
        self.page_label.setObjectName("Muted")
        page_counter_layout.addWidget(self.page_label)
        nav.addWidget(page_counter)
        nav.addWidget(button("›", lambda: self.turn(1), "NavButton"))
        self.pdf_nav = nav_widget
        nav.addStretch()
        self.pdf_layout_buttons = {}
        for columns in (1, 2, 3):
            control = button("", lambda checked=False, n=columns: self.set_pdf_columns(n), "PdfLayoutButton")
            control.setToolTip(f"显示 {columns} 页")
            control.setAccessibleName(f"显示 {columns} 页")
            control.setIconSize(QSize(20, 20))
            control.setCheckable(True)
            control.hide()
            nav.addWidget(control)
            self.pdf_layout_buttons[columns] = control
        self.pdf_fullscreen_button = button("", self.toggle_pdf_fullscreen, "NavButton")
        self.pdf_fullscreen_button.setToolTip("PDF 全屏")
        self.pdf_fullscreen_button.setAccessibleName("PDF 全屏")
        self.pdf_fullscreen_button.setEnabled(False)
        nav.insertWidget(3, self.pdf_fullscreen_button)
        self.pdf_color_button = button(
            "黑白色",
            lambda: self.change_pdf_follow_theme(not self.view.follow_theme),
            "NavButton",
        )
        self.pdf_color_button.setEnabled(False)
        self.pdf_color_button.setToolTip("切换 PDF 背景配色")
        nav.insertWidget(4, self.pdf_color_button)
        self.pdf_calibrate_button = button("校准", self.fit_width, "NavButton")
        nav.addWidget(self.pdf_calibrate_button)
        nav.addWidget(button("−", lambda: self.zoom(.85), "NavButton"))
        self.zoom_label = self.pdf_number_input("缩放百分比", 70, self.apply_pdf_zoom)
        self.zoom_label.setText("130%")
        self.zoom_label.setEnabled(False)
        nav.addWidget(self.zoom_label)
        nav.addWidget(button("＋", lambda: self.zoom(1.18), "NavButton")); rl.addWidget(nav_widget)
        self.view = ContinuousPDF()
        self.view.action.connect(self.pdf_action)
        self.view.pageChanged.connect(self.reading_page_changed)
        self.view.zoomChanged.connect(lambda scale: self.zoom_label.setText(f"{scale:.0%}"))
        self.pdf_reader_layout = rl
        self.pdf_fullscreen_state = None
        rl.addWidget(self.view, 1)
        self.reading_splitter.addWidget(reader)
        self.pdf_escape = QShortcut("Escape", self)
        self.pdf_escape.setEnabled(False)
        self.pdf_escape.activated.connect(self.toggle_pdf_fullscreen)

        workspace = QWidget(); workspace.setObjectName("WorkspacePanel")
        wl = QVBoxLayout(workspace); wl.setContentsMargins(0, 0, 0, 0); wl.setSpacing(0)
        head, row = header("学习工作台")
        self.analysis_mode = QComboBox(); self.analysis_mode.addItem("快读模式", "quick"); self.analysis_mode.addItem("精读模式", "deep")
        self.analysis_mode.setObjectName("AnalysisMode")
        self.analysis_mode.setFixedHeight(36)
        mode_view = QListView(self.analysis_mode)
        mode_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.analysis_mode.setView(mode_view)
        mode_view.ensurePolished()
        # Qt's popup margins can otherwise clip the last row in the compact control.
        rows_height = sum(mode_view.sizeHintForRow(i) for i in range(self.analysis_mode.count()))
        mode_view.setMinimumHeight(rows_height + 2 * mode_view.frameWidth())
        self.analysis_mode.currentIndexChanged.connect(lambda _: self.refresh_analysis())
        row.addWidget(self.analysis_mode)
        self.read_button = button("阅读", self.toggle_reading, "Primary")
        self.read_button.setProperty("analysisAction", True)
        self.read_button.setFixedHeight(36)
        row.addWidget(self.read_button); wl.addWidget(head)
        tabs = QTabWidget()
        self.analysis_frame = AnalysisBreathingFrame()
        analysis_frame_layout = QVBoxLayout(self.analysis_frame)
        analysis_frame_layout.setContentsMargins(1, 1, 1, 1)
        analysis_frame_layout.setSpacing(0)
        self.deep_view_bar = QWidget()
        self.deep_view_bar.setObjectName("AnalysisViewBar")
        deep_view_layout = QHBoxLayout(self.deep_view_bar)
        deep_view_layout.setContentsMargins(0, 0, 0, 0)
        deep_view_layout.setSpacing(0)
        self.deep_view_buttons = {}
        for view, label in (("segments", "分段报告"), ("report", "精读报告")):
            control = QPushButton(label)
            control.setObjectName("AnalysisViewButton")
            control.setProperty("analysisSide", "left" if view == "segments" else "right")
            control.setCheckable(True)
            control.setFixedHeight(26)
            control.clicked.connect(lambda checked=False, selected=view: self.select_deep_view(selected))
            deep_view_layout.addWidget(control, 1)
            self.deep_view_buttons[view] = control
        self.deep_view = "report"
        self.deep_view_buttons["report"].setChecked(True)
        self.deep_view_bar.hide()
        analysis_frame_layout.addWidget(self.deep_view_bar)
        self.analysis_pages = QStackedWidget()
        analysis_frame_layout.addWidget(self.analysis_pages)
        self.analysis_browsers = {}
        self.analysis_status = RequestStatus()
        self.analysis_status.finished.connect(self.save_analysis_request_status)
        for mode in ("quick", "deep", "deep_segments"):
            browser = MarkdownBrowser(reading_style=True, allow_followup=True)
            browser.setObjectName("AnalysisOutput")
            browser.setFrameShape(QFrame.Shape.NoFrame)
            browser.document().setDocumentMargin(7)
            browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            browser.followUpRequested.connect(self.ask_about_analysis)
            browser.figurePreviewRequested.connect(self.show_figure_preview)
            browser.anchorClicked.connect(self.continue_reading)
            browser.anchorClicked.connect(self.analysis_status.link_clicked)
            browser.anchorClicked.connect(self.open_analysis_page)
            self.analysis_browsers[mode] = browser
            self.analysis_pages.addWidget(browser)
        self.summary = self.analysis_browsers["quick"]
        self.analysis_status.setParent(self.analysis_pages)
        self.analysis_status.browser = self.summary
        tabs.addTab(self.analysis_frame, "AI 分析")
        tabs.setObjectName("AnalysisTabs")
        tabs.tabBar().setFixedHeight(26)
        self.outline_button = button("目录 ▾", self.show_analysis_outline, "Quiet")
        self.outline_button.setObjectName("AnalysisOutlineButton")
        self.outline_button.setFixedHeight(26)
        self.outline_button.setToolTip("查看当前 AI 分析的章节")
        tabs.setCornerWidget(self.outline_button, Qt.Corner.TopRightCorner)
        self.analysis_outline = AnalysisOutline(self)
        tabs.currentChanged.connect(lambda index: self.outline_button.setVisible(index == 0))
        tabs.currentChanged.connect(lambda _: self.analysis_outline.hide())
        self.notes = MarkdownEditor("记录你的理解与思考，支持 Markdown…"); tabs.addTab(self.notes, "笔记")
        marks_widget = QWidget(); ml = QVBoxLayout(marks_widget); ml.setContentsMargins(10, 10, 10, 10)
        self.marks = QListWidget(); ml.addWidget(self.marks)
        self.mark_preview = MarkdownBrowser(); ml.addWidget(self.mark_preview)
        self.marks.currentRowChanged.connect(self.preview_mark); self.marks.itemDoubleClicked.connect(self.goto_mark)
        for names in [[("编辑批注", self.edit_mark), ("取消高亮", lambda: self.remove_mark_part("取消高亮"))],
                      [("删除批注", lambda: self.remove_mark_part("删除批注")), ("全部移除", self.delete_mark)]]:
            actions = QHBoxLayout()
            for name, fn in names: actions.addWidget(button(name, fn, "Danger" if name.startswith("删除") or name == "全部移除" else "Quiet"))
            ml.addLayout(actions)
        tabs.addTab(marks_widget, "批注"); wl.addWidget(tabs, 1); self.reading_splitter.addWidget(workspace)

        chat = QWidget(); chat.setObjectName("ChatPanel")
        cl = QVBoxLayout(chat); cl.setContentsMargins(0, 0, 0, 0); cl.setSpacing(0)
        head = QWidget(); head.setObjectName("PanelHeader"); head.setFixedHeight(49)
        chat_header = QHBoxLayout(head); chat_header.setContentsMargins(10, 0, 8, 0); chat_header.setSpacing(4)
        title = QLabel("论文追问"); title.setObjectName("PanelTitle"); chat_header.addWidget(title)
        self.question_navigation = QuestionNavigation(); self.question_navigation.selected.connect(self.jump_question)
        chat_header.addWidget(self.question_navigation, 1)
        self.question_navigation.contextRequested.connect(self.question_context_menu)
        self.new_session_button = button("新建会话", self.new_session); chat_header.addWidget(self.new_session_button)
        self.history_button = button("历史", self.session_history); chat_header.addWidget(self.history_button)
        cl.addWidget(head)
        self.chat_splitter = ChatVerticalSplitter()
        output = QWidget(); output.setObjectName("ChatOutput")
        output_layout = QVBoxLayout(output)
        output_layout.setContentsMargins(0, 0, 0, 0); output_layout.setSpacing(0)
        output.setMinimumHeight(120)
        self.sage_card = QWidget(); self.sage_card.setObjectName("SageCard")
        sage_row = QHBoxLayout(self.sage_card)
        sage_row.setContentsMargins(14, 10, 14, 10)
        sage_row.setSpacing(12)
        self.sage_avatar = QLabel()
        sage_row.addWidget(self.sage_avatar)
        sage_details = QVBoxLayout()
        sage_details.setSpacing(4)
        self.sage_title = QLabel(); self.sage_title.setObjectName("SageTitle")
        self.sage_title.setTextFormat(Qt.TextFormat.PlainText)
        sage_details.addWidget(self.sage_title)
        self.sage_badge = QLabel(); self.sage_badge.setObjectName("SageBadge")
        self.sage_badge.setTextFormat(Qt.TextFormat.PlainText)
        sage_details.addWidget(self.sage_badge, alignment=Qt.AlignmentFlag.AlignLeft)
        sage_row.addLayout(sage_details, 1)
        output_layout.addWidget(self.sage_card)
        self.chat = ChatBrowser(); output_layout.addWidget(self.chat, 1)
        self.chat_reflow_timer = QTimer(self.chat)
        self.chat_reflow_timer.setSingleShot(True)
        self.chat_reflow_timer.timeout.connect(self.reflow_chat_viewport)
        self.chat_status = RequestStatus()
        self.chat_status.attach(self.chat, self.render_chat_status)
        self.chat_status.finished.connect(self.save_chat_request_status)
        self.chat.anchorClicked.connect(self.toggle_chat_status)
        self.chat.anchorClicked.connect(self.add_answer_to_notes)
        self.chat.anchorClicked.connect(self.open_citation)
        quote_box = QWidget(); self.quote_box = quote_box; ql = QVBoxLayout(quote_box); ql.setContentsMargins(0, 8, 0, 0); ql.setSpacing(4)
        composer = QWidget(); composer.setObjectName("ChatComposer")
        form = QVBoxLayout(composer); form.setContentsMargins(0, 8, 0, 0); form.setSpacing(0)
        quote_card = QWidget(); quote_card.setObjectName("QuoteCard")
        card_layout = QVBoxLayout(quote_card); card_layout.setContentsMargins(10, 7, 8, 6); card_layout.setSpacing(0)
        quote_header = QHBoxLayout(); quote_header.setSpacing(6)
        quote_title = QLabel("引用内容"); quote_title.setObjectName("AccentLabel")
        quote_header.addWidget(quote_title); quote_header.addStretch()
        self.clear_quote_button = QPushButton("×"); self.clear_quote_button.setObjectName("QuoteClose")
        self.clear_quote_button.setFixedSize(24, 24)
        self.clear_quote_button.setToolTip("清除选区引用")
        self.clear_quote_button.setAccessibleName("清除选区引用")
        self.clear_quote_button.clicked.connect(self.clear_quote)
        quote_header.addWidget(self.clear_quote_button); card_layout.addLayout(quote_header)
        self.quote_label = MarkdownBrowser(); self.quote_label.setObjectName("Quote")
        self.quote_label.setMaximumHeight(85); self.quote_label.set_markdown("选中文字后右键，可引用原文追问。")
        card_layout.addWidget(self.quote_label); ql.addWidget(quote_card); form.addWidget(quote_box)
        quote_box.hide()
        self.question = QuestionEdit()
        self.question.submitRequested.connect(self.ask)
        self.question.setMinimumHeight(104); form.addWidget(self.question, 1)
        self.model_selector = QComboBox(); self.model_selector.setMinimumWidth(0)
        self.model_selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.model_selector.setMinimumContentsLength(8)
        self.model_selector.setToolTip("选择本次使用的模型；在模型设置中管理多个配置")
        self.model_selector.setAccessibleName("选择模型")
        self.refresh_models()
        self.model_selector.currentIndexChanged.connect(self.select_model)
        self.question.footer_layout.addWidget(self.model_selector, 1)
        self.send_button = button("发送 ↑", self.toggle_ask, "Primary")
        self.question.footer_layout.addWidget(self.send_button)
        self.chat_splitter.addWidget(output)
        self.chat_splitter.addWidget(composer)
        self.chat_splitter.setStretchFactor(0, 1)
        self.chat_splitter.setStretchFactor(1, 0)
        self.chat_splitter.setSizes([600, 112])
        self.chat_resize_following = False
        self.chat_splitter.resizeStarted.connect(self.begin_chat_resize)
        self.chat_splitter.splitterMoved.connect(self.follow_chat_resize)
        self.chat_splitter.resizeFinished.connect(self.finish_chat_resize)
        cl.addWidget(self.chat_splitter, 1); self.reading_splitter.addWidget(chat)
        self.reading_panes = (reader, workspace, chat)
        self.reading_home = ReadingHome(self.import_file, self.reload)
        self.recent_path = self.library.root / "recent-reading.json"
        try:
            saved = json.loads(self.recent_path.read_text(encoding="utf-8"))
            self.recent_reading = saved if isinstance(saved, dict) else {}
        except (OSError, ValueError):
            self.recent_reading = {}
        self.reading_content.addWidget(self.reading_home)
        split.addWidget(self.reading_content)
        split.setCollapsible(1, False)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        self.update_theme_art()
        self.update_reading_home()
        split.setSizes([220, 1170])
        self.reading_splitter.setSizes([500, 335, 335])
        self.sync_library_rail()
        self.analysis_progress_widget = QWidget()
        self.analysis_progress_widget.setFixedSize(292, 18)
        self.analysis_progress_paper_id = None
        progress_row = QHBoxLayout(self.analysis_progress_widget)
        progress_row.setContentsMargins(4, 0, 8, 0)
        progress_row.setSpacing(6)
        self.analysis_progress_label = QLabel("0%")
        self.analysis_progress_label.setObjectName("AnalysisProgressLabel")
        self.analysis_progress_label.setFixedWidth(46)
        self.analysis_progress_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        progress_row.addWidget(self.analysis_progress_label)
        self.analysis_progress_bar = QProgressBar()
        self.analysis_progress_bar.setObjectName("AnalysisProgress")
        self.analysis_progress_bar.setRange(0, 100)
        self.analysis_progress_bar.setValue(0)
        self.analysis_progress_bar.setTextVisible(False)
        self.analysis_progress_bar.setFixedSize(120, 10)
        progress_row.addWidget(self.analysis_progress_bar)
        self.analysis_progress_state = QLabel("等待模型")
        self.analysis_progress_state.setObjectName("AnalysisProgressState")
        self.analysis_progress_state.setFixedWidth(100)
        progress_row.addWidget(self.analysis_progress_state)
        self.statusBar().insertWidget(0, self.analysis_progress_widget)
        self.analysis_progress_widget.hide()
        view_controls = QWidget()
        view_row = QHBoxLayout(view_controls)
        view_row.setContentsMargins(0, 0, 4, 0)
        view_row.setSpacing(3)
        self.view_mode_group = QButtonGroup(self)
        self.view_mode_group.setExclusive(True)
        self.view_mode_buttons = {}
        for mode, title in ((4, '四折叠'), (3, '三折叠'), (2, '双折叠')):
            control = ViewModeButton(mode, title)
            control.clicked.connect(lambda checked=False, selected=mode: self.set_view_mode(selected))
            self.view_mode_group.addButton(control)
            self.view_mode_buttons[mode] = control
            view_row.addWidget(control)
        self.view_mode_buttons[4].setChecked(True)
        self.current_view_mode = 4
        self.statusBar().addPermanentWidget(view_controls)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(500); self.timer.timeout.connect(self.save_notes)
        self.notes.textChanged.connect(lambda: self.timer.start())
        self.position_timer = QTimer(self); self.position_timer.setSingleShot(True)
        self.position_timer.setInterval(600); self.position_timer.timeout.connect(self.persist)
        for browser in self.findChildren(MarkdownBrowser): browser.async_math = True
        self.chat.external_math = True
        self.chat.mathUpdated.connect(self.render_chat)
        resize_fixed_text_controls(self)
        self.reload()
        self.statusBar().showMessage("学习记录仅保存在本机；AI 操作会将必要文本发送到配置的模型 API。")

    def update_reading_home(self):
        at_home = self.paper is None
        self.reading_content.setCurrentWidget(
            self.reading_home if at_home else self.reading_splitter)
        if at_home:
            titles = {paper["id"]: paper["title"] for paper in getattr(self, "all_papers", [])}
            recent = [(identifier, titles[identifier], stamp)
                      for identifier, stamp in self.recent_reading.items()
                      if identifier in titles and isinstance(stamp, str)]
            recent.sort(key=lambda entry: entry[2], reverse=True)
            self.reading_home.set_recent(recent[:3])

    def show_reading_home(self):
        if self.workspace_stack.currentWidget() is not self.splitter:
            return
        if self.paper:
            self.close_current_paper()
        with QSignalBlocker(self.list):
            self.list.setCurrentRow(-1)
        self.update_reading_home()

    def refresh_models(self):
        self.model_selector.blockSignals(True); self.model_selector.clear()
        for profile in self.profile_config["profiles"]:
            self.model_selector.addItem(profile["name"] + (" · " + profile["model"] if profile["model"] else ""), profile["id"])
        self.model_selector.setCurrentIndex(self.model_selector.findData(self.profile_config["active_id"]))
        self.model_selector.blockSignals(False)
        if self.research_workspace is not None:
            self.research_workspace.refresh_models()

    def select_model(self, index):
        identifier = self.model_selector.itemData(index)
        if not identifier: return
        previous = self.profile_config["active_id"]
        self.profile_config["active_id"] = identifier
        try: self.library.save_config(dict(self.library.config(), **self.profile_config))
        except Exception as exc:
            self.profile_config["active_id"] = previous; self.refresh_models(); self.error(str(exc)); return
        self.config = active_profile(self.profile_config)

    def error(self, text):
        log.warning("界面操作失败：{}", text)
        QMessageBox.warning(self, "操作失败", text)








    def toggle_research(self):
        if self.workspace_stack.currentWidget() is self.research_workspace and self.research_workspace is not None:
            self.show_reader()
            return
        if (self.skill_library is not None and
                self.workspace_stack.currentWidget() is self.skill_library and
                not self.skill_library.confirm_leave()):
            return
        if self.research_workspace is None:
            from paperreader.ui.research import ResearchWorkspace
            try:
                self.research_workspace = ResearchWorkspace(self)
            except (OSError, ValueError) as exc:
                self.error("无法打开研究空间：" + str(exc))
                return
            self.workspace_stack.addWidget(self.research_workspace)
        self.workspace_stack.setCurrentWidget(self.research_workspace)
        self.research_rail_button.set_active(True)
        self.skills_rail_button.set_active(False)
        self.library_rail_button.set_active(False)
        self.library_rail_button.setToolTip("返回论文阅读")

    def toggle_skills(self):
        if self.skill_library is not None and self.workspace_stack.currentWidget() is self.skill_library:
            self.show_reader()
            return
        if self.skill_library is None:
            from paperreader.ui.skill_library import SkillLibrary
            self.skill_library = SkillLibrary(self)
            self.workspace_stack.addWidget(self.skill_library)
        elif not (self.skill_library.editing or self.skill_library.creating):
            self.skill_library.reload(preferred=self.skill_library.current_key)
        self.workspace_stack.setCurrentWidget(self.skill_library)
        self.skills_rail_button.set_active(True)
        self.research_rail_button.set_active(False)
        self.library_rail_button.set_active(False)
        self.library_rail_button.setToolTip("返回论文阅读")

    def show_reader(self):
        if (self.skill_library is not None and
                self.workspace_stack.currentWidget() is self.skill_library and
                not self.skill_library.confirm_leave()):
            return False
        self.workspace_stack.setCurrentWidget(self.splitter)
        self.research_rail_button.set_active(False)
        self.skills_rail_button.set_active(False)
        self.sync_library_rail()
        return True


    def toggle_library(self):
        if self.workspace_stack.currentIndex():
            self.show_reader()
            return
        if self.splitter.sizes()[0] == 0:
            self.splitter.previous_widths.setdefault(0, 220)
        self.splitter.toggle(0)
        self.sync_library_rail()

    def set_view_mode(self, mode):
        """Apply a pane-width preset without changing later splitter interaction."""
        if not self.show_reader():
            self.view_mode_buttons[self.current_view_mode].setChecked(True)
            return
        if self.reading_content.currentWidget() is self.reading_home:
            self.reading_content.setCurrentWidget(self.reading_splitter)
        available = max(sum(self.splitter.sizes()), self.splitter.width())
        library_width = 220 if mode == 4 else 0
        self.splitter.setSizes([library_width, max(0, available - library_width)])
        self.splitter.previous_widths[0] = 220
        inner_width = max(sum(self.reading_splitter.sizes()), self.reading_splitter.width())
        if mode == 4:
            preview = min(500, max(0, inner_width - 2 * 180))
        elif mode == 3:
            # Keep every visible PDF toolbar control on one row with breathing room.
            preview = max(self.pdf_nav.sizeHint().width() + 32,
                          self.reading_panes[0].minimumSizeHint().width())
        else:
            preview = 0
        remainder = max(0, inner_width - preview)
        self.reading_splitter.setSizes([preview, remainder // 2, remainder - remainder // 2])
        self.reading_splitter.previous_widths[0] = 500
        self.sync_library_rail()
        self.view_mode_buttons[mode].setChecked(True)
        self.current_view_mode = mode
        if mode in (3, 4) and self.doc is not None:
            # Refit after the splitter has applied the new PDF viewport width.
            QTimer.singleShot(0, lambda: self.fit_width()
                              if self.current_view_mode == mode and self.doc is not None
                              and self.reading_splitter.sizes()[0] > 0 else None)

    def sync_library_rail(self, *_):
        if self.workspace_stack.currentIndex():
            return
        expanded = self.splitter.sizes()[0] > 0
        self.library_rail_button.set_active(expanded)
        self.library_rail_button.setToolTip("收起论文列表" if expanded else "展开论文列表")

    def set_reader_title(self, title):
        self.reader_paper_title.set_full_text(title)
        self.reader_title_divider.setVisible(bool(title))




















    def refresh(self):
        if not self.paper:
            self.analysis_status.set_context(None); self.chat_status.set_context(None)
            return
        self.view.set_marks(self.paper["marks"])
        self.update_pdf_page_counter()
        self.refresh_analysis()
        self.render_chat()
        self.marks.clear(); self.marks.addItems([f"P{m['page']+1} · {m['text'][:55]}\n{m['comment']}" for m in self.paper["marks"]])

    def refresh_analysis(self):
        if not self.paper:
            return
        mode = self.analysis_mode.currentData()
        self.deep_view_bar.setVisible(mode == "deep")
        browser_key = "deep_segments" if mode == "deep" and self.deep_view == "segments" else mode
        self.summary = self.analysis_browsers[browser_key]
        self.analysis_status.browser = self.summary
        self.analysis_status.set_context((self.paper['id'], mode))
        record = self.paper.get("analyses", {}).get(mode, {})
        saved = record.get("text")
        if mode == "quick" and saved is None: saved = self.paper["summary"]
        draft = self.summary_drafts.get(self.paper["id"]+":"+mode)
        self.analysis_frame.set_active(self.analysis_cancel is not None and draft is not None)
        if mode == "deep":
            if isinstance(draft, dict):
                text = draft[self.deep_view]
            elif record.get("report") is not None or record.get("segments_text") is not None:
                text = record.get("report" if self.deep_view == "report" else "segments_text", "")
            elif saved:
                marker = "\n\n---\n\n# 分段精读记录\n\n"
                parts = saved.split(marker, 1)
                text = parts[0] if self.deep_view == "report" else (
                    parts[1] if len(parts) > 1 else "这份旧报告没有单独保存分段记录。")
            else:
                text = "选择精读模式后点击“阅读”开始分析。"
        else:
            text = draft or saved or "选择快读模式后点击“阅读”开始分析。"
        footer = ""
        if not draft and record.get("stopped") and record.get("resume"):
            footer = '<hr><p align="left" style="-qt-block-indent:0;"><a href="paperreader-analysis:continue">继续阅读</a></p>'
        text = link_analysis_pages(text, self.paper['id'], len(self.doc))
        figure_cards = {}
        if FIGURE_REFERENCE.search(text) or FIGURE_INSERT.search(text):
            if self._figure_index is None:
                self._figure_index = figure_index(self.doc)
            text, figure_numbers = insert_figure_markers(text, self._figure_index)
            for number in figure_numbers:
                if number not in self._figure_images:
                    self._figure_images[number] = figure_excerpt(self.doc, self._figure_index[number])
                page_number = self._figure_index[number][0] + 1
                href = f'paperreader-page://open?paper={self.paper["id"]}&page={page_number}'
                figure_cards[f'PRPAPERFIGURE{number}END'] = (
                    self._figure_images[number], f'原文图 {number} · 第 {page_number} 页页面节选（点击查看原页）', href)
        self.summary.set_markdown(text, footer_html=footer, reuse=True,
                                  trusted_figures=figure_cards)
        self.analysis_status.restore((self.paper['id'], mode), record.get('request_status'))
        self.analysis_status.render_inline()
        self.analysis_pages.setCurrentWidget(self.summary)

    def select_deep_view(self, view):
        self.deep_view = view
        for name, control in self.deep_view_buttons.items():
            control.setChecked(name == view)
        self.analysis_outline.hide()
        self.refresh_analysis()

    def show_figure_preview(self, image, label):
        preview = FigurePreview(image, label, self)
        self.figure_preview = preview
        preview.finished.connect(preview.deleteLater)
        preview.show()
        preview.raise_()
        preview.setFocus()

    def show_analysis_outline(self):
        if self.paper:
            self.analysis_outline.show_for(self.outline_button, self.summary)















    def task(self, fn, done, on_chunk=None, on_error=None, request_status=None, request_label='模型请求',
             *, cancel=None, on_stop=None):
        if self.busy:
            self.error("已有后台任务，请等待完成。"); return False
        self.busy = True; self.model_selector.setEnabled(False); self.statusBar().showMessage("正在处理，请稍候…")
        self.inflight_paper = self.paper
        if request_status: request_status.begin(request_label, self.config['model'])
        job = Job(fn, streaming=on_chunk is not None); self.job = job
        if on_chunk is not None: job.signals.chunk.connect(on_chunk)
        def stopped():
            if cancel is None or not cancel.is_set():
                return False
            self.busy = False; self.model_selector.setEnabled(True)
            self.inflight_paper = None
            try:
                on_stop()
            except Exception as exc:
                self.error("保存已读内容失败：" + str(exc))
            if request_status: request_status.finish(stopped=True)
            self.statusBar().showMessage("已停止追问" if request_label == '论文追问' else "已停止阅读")
            return True
        def finish(value):
            if stopped(): return
            self.busy = False; self.model_selector.setEnabled(True)
            self.statusBar().showMessage("任务完成，学习记录保存在本地")
            try:
                done(value)
                if request_status: request_status.finish()
            except Exception as exc:
                log.error("后台任务结果处理失败：{}", type(exc).__name__, exc_info=True)
                if request_status: request_status.finish(False)
                self.statusBar().showMessage("任务失败，可重试")
                self.error(str(exc))
            self.inflight_paper = None
        def fail(text):
            if stopped(): return
            self.busy = False; self.model_selector.setEnabled(True); self.statusBar().showMessage("任务失败，可重试")
            if request_status: request_status.finish(False)
            if on_error:
                try: on_error(text)
                except Exception as exc: text += "\n部分结果保存失败：" + str(exc)
            self.error(text)
            self.inflight_paper = None
        job.signals.done.connect(finish); job.signals.error.connect(fail); self.pool.start(job)
        return True









    def ai(self, messages, done, on_chunk, on_error=None, request_status=None, request_label='模型请求',
           *, theme=None, cancel=None, on_stop=None):
        try: key = keyring.get_password("PaperReader", self.config.get("key_account", "api")) or ""
        except Exception as exc:
            if on_error: on_error(str(exc))
            self.error(str(exc)); return False
        config = dict(self.config)
        messages = with_persona(messages, theme=theme or self.profile_config["theme"])
        def progress(text):
            if request_status: request_status.received(text)
            on_chunk(text)
        def invoke(emit):
            kwargs = {'on_chunk': emit}
            if cancel is not None and supports_keyword(complete, 'cancel'):
                kwargs['cancel'] = cancel
            return complete(config, key, messages, **kwargs)
        return self.task(invoke, done, on_chunk=progress, on_error=on_error,
                         request_status=request_status, request_label=request_label,
                         cancel=cancel, on_stop=on_stop)

    def stream_render_timer(self, browser, render):
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(120)

        def display():
            if browser.is_user_scrolling():
                timer.start()
            else:
                render()

        timer.timeout.connect(display)
        return timer

    def toggle_reading(self):
        if self.analysis_cancel is None:
            self.analyze()
            return
        self.analysis_cancel.set()
        self.read_button.setText("停止中…")
        self.read_button.setEnabled(False)

    def continue_reading(self, url):
        if url.toString() == "paperreader-analysis:continue":
            self.analyze(resume_reading=True)

    def analyze(self, *, resume_reading=False):
        if not self.paper or self.busy: return
        mode = self.analysis_mode.currentData(); paper = self.paper
        record = paper.get('analyses', {}).get(mode, {})
        previous = record.get('text')
        if mode == 'quick' and not previous: previous = paper['summary']
        label = '快读模式' if mode == 'quick' else '精读模式'
        other_label = '精读模式' if mode == 'quick' else '快读模式'
        resume = record.get('resume') if resume_reading and record.get('stopped') else None
        if resume_reading and resume is None:
            return
        if previous and not record.get('stopped'):
            dialog = QMessageBox(self)
            dialog.setWindowTitle(f'重新阅读 · {label}')
            dialog.setTextFormat(Qt.TextFormat.RichText)
            dialog.setText(f'<b>重新阅读《{escape(paper["title"])}》并生成{label}？</b>')
            dialog.setInformativeText(
                f'将重新调用模型，并覆盖这篇论文已有的<b>{label}</b>内容。'
                f'<br><br><b>{other_label}、个人笔记、高亮批注和历史问答均会保留。</b>')
            cancel = dialog.addButton('取消', QMessageBox.ButtonRole.RejectRole)
            regenerate = dialog.addButton('重新阅读', QMessageBox.ButtonRole.AcceptRole)
            dialog.setDefaultButton(cancel)
            dialog.exec()
            if dialog.clickedButton() is not regenerate: return
        config = dict(self.config)
        profile = [config.get('id'), config['model']]
        if resume and resume['profile'][:2] != profile:
            self.error("继续阅读需要原来的模型配置。也可点击「阅读」从头开始。")
            return
        checkpoint_profile = resume['profile'] if resume else profile
        pack = get_theme(record['theme_id'] if resume else self.profile_config["theme"])
        try: key = keyring.get_password('PaperReader', config.get('key_account','api')) or ''
        except Exception as exc: self.error(str(exc)); return
        pages = [(i,p.get_text()) for i,p in enumerate(self.doc)]
        header = f"# {'快速概要' if mode == 'quick' else '精读报告'}\n\n模型：{config['model']}\n\n---\n\n"
        draft_key = paper['id']+':'+mode
        cancel = Event()
        completed = list(resume['completed']) if resume else []
        title = resume['title'] if resume else ""
        partial = resume['partial'] if resume else ""
        active_plan = resume.get('plan') if resume else 'v5'
        progress_total = 1
        progress_scale = max(1200, min(8000, sum(len(text) for _, text in pages) // 8))
        self.analysis_progress_paper_id = paper['id']
        self.analysis_progress_bar.setValue(0)
        self.analysis_progress_label.setText('0%')
        self.analysis_progress_state.setText('等待模型')
        self.analysis_progress_state.setToolTip('')
        self.analysis_progress_widget.show()

        def update_progress():
            value = round(100 * min(len(completed), progress_total) / progress_total)
            self.analysis_progress_bar.setValue(value)
            self.analysis_progress_label.setText(f'{value}%')

        def update_stream_progress():
            if not partial:
                return
            if mode == 'deep' and active_plan == 'v5':
                report_at = partial.find('# 精读报告')
                segments_at = partial.find('# 分段报告')
                if segments_at >= 0 and report_at > segments_at:
                    count = len(partial) - report_at - len('# 精读报告')
                    value = 50 + round(45 * count / (count + progress_scale))
                    self.analysis_progress_state.setText('精读报告')
                    self.analysis_progress_state.setToolTip('')
                else:
                    count = len(partial) - segments_at if segments_at >= 0 else len(partial)
                    value = round(45 * count / (count + progress_scale))
                    self.analysis_progress_state.setText('分段报告')
                    self.analysis_progress_state.setToolTip('')
            else:
                base = 100 * len(completed) / progress_total
                span = 100 / progress_total
                count = len(partial)
                value = round(base + .9 * span * count / (count + progress_scale))
            value = max(self.analysis_progress_bar.value(), min(95, value))
            if value != self.analysis_progress_bar.value():
                self.analysis_progress_bar.setValue(value)
                self.analysis_progress_label.setText(f'约 {value}%')

        def analysis_text():
            sections = [f"## {part['title']}\n\n{part['text']}" for part in completed]
            if title:
                sections.append(f"## {title}\n\n{partial}")
            return header + "\n\n".join(sections)

        def deep_draft():
            if active_plan in ('v3', 'v5'):
                output = partial or (completed[-1]['text'] if completed else '')
                report, segments = split_deep_response(output)
                return {
                    'report': header + (report or '正在读取论文原文…'),
                    'segments': '# 分段报告\n\n' + (segments or '模型生成分段报告时将在这里显示。'),
                }
            parts = completed + ([{"title": title, "text": partial}] if title else [])
            segments = [f"## {part['title']}\n\n{part['text']}" for part in parts
                        if part['title'].startswith('全文精读')]
            reports = [part['text'] for part in parts
                       if part['title'] == '生成全文精读总报告']
            return {
                'report': header + (reports[-1] if reports else '分段分析进行中，完成后生成精读报告。'),
                'segments': '# 分段报告\n\n' + ('\n\n'.join(segments) if segments else '正在读取论文原文…'),
            }

        def display_draft():
            draft = analysis_text() if mode == 'quick' else deep_draft()
            self.summary_drafts[draft_key] = draft
            if self.paper is paper and self.analysis_mode.currentData() == mode:
                self.refresh_analysis()
        if mode == 'deep':
            self.select_deep_view('segments')
        render_timer = self.stream_render_timer(self.summary, display_draft)
        self.summary_drafts[draft_key] = (analysis_text() + '\n\n等待模型响应…'
                                          if mode == 'quick' else deep_draft())
        self.refresh()

        def save_partial(*, stopped=False):
            status = '已停止阅读' if stopped else '阅读未完成'
            deep_parts = deep_draft() if mode == 'deep' else {}
            paper.setdefault('analyses', {})[mode] = dict(
                text=f'**{status}**\n\n'+analysis_text(), complete=False, stopped=stopped,
                **({'report': deep_parts['report'],
                    'segments_text': deep_parts['segments']} if deep_parts else {}),
                model=config['model'], theme_id=pack.identifier, assistant_name=pack.assistant_name,
                resume=dict(completed=completed.copy(), title=title, partial=partial,
                            profile=checkpoint_profile,
                            plan=active_plan),
            )
            self.library.save(paper)
        def progress(serialized):
            nonlocal title, partial, progress_total, active_plan
            event = json.loads(serialized)
            if event['kind'] == 'plan':
                active_plan = event.get('plan', active_plan)
                progress_total = max(1, event['total'])
                update_progress()
            elif event['kind'] == 'fallback':
                active_plan = 'v4'
                title = partial = ''
                self.analysis_progress_bar.setValue(0)
                self.analysis_progress_label.setText('0%')
                self.analysis_progress_state.setText('切换分段')
                self.analysis_progress_state.setToolTip('')
            elif event['kind'] == 'section':
                title, partial = event['title'], event['prefix']
                self.analysis_status.stage(title)
                stage = title.rsplit(' · ', 1)[-1]
                self.analysis_progress_state.setText(
                    self.analysis_progress_state.fontMetrics().elidedText(
                        stage, Qt.TextElideMode.ElideRight, self.analysis_progress_state.width()))
                self.analysis_progress_state.setToolTip(stage)
            elif event['kind'] == 'text':
                self.analysis_status.received(event['text'])
                partial += event['text']
                update_stream_progress()
            elif event['kind'] == 'model_call':
                self.analysis_status.model_call(event['title'], event['seconds'], event['usage'])
            elif event['kind'] == 'checkpoint':
                completed.append({"title": event['title'], "text": event['text']})
                title = partial = ""
                update_progress()
                save_partial()
            if not render_timer.isActive(): render_timer.start()

        def cleanup(*, keep_progress=False):
            render_timer.stop(); render_timer.deleteLater()
            self.analysis_cancel = None
            self.analysis_frame.set_active(False)
            self.read_button.setText("阅读")
            self.read_button.setEnabled(True)
            if not keep_progress:
                self.analysis_progress_widget.hide()
            self.summary_drafts.pop(draft_key, None)

        def done(result):
            saved = False
            try:
                text = header+'分析范围：'+result['scope']+'\n\n'+result['text']
                paper.setdefault('analyses', {})[mode] = dict(
                    text=text, complete=True, model=config['model'], segments=result['segments'],
                    **({'report': header+'分析范围：'+result['scope']+'\n\n'+result['report'],
                        'segments_text': '# 分段报告\n\n'+result['segments_text']} if mode == 'deep' else {}),
                    theme_id=pack.identifier, assistant_name=pack.assistant_name,
                )
                if mode == 'quick': paper['summary'] = text
                self.library.save(paper)
                saved = True
            finally:
                cleanup(keep_progress=saved and self.paper is paper)
            if self.paper is paper:
                self.analysis_progress_bar.setValue(100)
                self.analysis_progress_label.setText('100%')
                self.analysis_progress_state.setText('已完成')
                self.analysis_progress_state.setToolTip('')
                self.statusBar().clearMessage()
            if self.paper is paper: self.refresh()

        def failed(error):
            cleanup()
            if completed or title: save_partial()
            if self.paper is paper: self.refresh()

        def stopped():
            cleanup()
            save_partial(stopped=True)
            if self.paper is paper: self.refresh()

        self.analysis_cancel = cancel
        self.analysis_frame.set_active(True)
        self.read_button.setText("停止")
        if not self.task(
            lambda emit: run_analysis(pages, config, key, mode, complete, emit, theme=pack.identifier,
                                      cancel=cancel, resume=resume),
            done, progress, failed, request_status=self.analysis_status, request_label=label,
            cancel=cancel, on_stop=stopped,
        ):
            self.analysis_cancel = None
            self.analysis_frame.set_active(False)
            self.read_button.setText("阅读")
            self.analysis_progress_widget.hide()
        else:
            self.statusBar().clearMessage()





































    def closeEvent(self, event):
        if self.research_workspace and self.research_workspace.active:
            self.research_workspace.stop_run()
            self.statusBar().showMessage("正在保存研究检查点，请稍后退出。")
            event.ignore()
            return
        if self.busy:
            self.error("后台任务仍在运行，请等待结束后退出。"); event.ignore(); return
        if self.research_workspace:
            for limit in self.research_workspace.full_map_pending.values():
                limit.stop.set()
            self.research_workspace.clear_pdf()
            if self.research_workspace.pdf_downloader is not None:
                self.research_workspace.pdf_downloader.shutdown()
        self.save_notes(); self.position_timer.stop()
        self.view.clear_document()
        if self.doc: self.doc.close(); self.doc = None
        settings_dialog = getattr(self, "_settings_dialog", None)
        if settings_dialog is not None:
            settings_dialog.close()
        event.accept()
