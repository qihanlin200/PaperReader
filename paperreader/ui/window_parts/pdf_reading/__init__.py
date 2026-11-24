"""Pdf Reading behavior for the main window."""
from paperreader.services.lazy import fitz
from PySide6.QtCore import QTimer, QUrlQuery
from PySide6.QtWidgets import QLineEdit
from PySide6.QtCore import Qt
from paperreader.ui.work_rail import menu_symbol_icon
from paperreader.services.sessions import ensure_sessions

class PdfReadingMixin:
    def open_research_paper(self, identifier, page=None, rects=()):
        try:
            path = self.library.pdf_path({"id": identifier})
            with fitz.open(path) as document:
                if document.needs_pass or not len(document) or (page is not None and not 0 <= page < len(document)):
                    raise ValueError("原文不可用")
            if not any(paper["id"] == identifier for paper in self.library.list_metadata()):
                raise ValueError("论文已移出资料库")
        except (OSError, RuntimeError, ValueError):
            self.error("引用的原文或页码已不可用。")
            return
        self.show_reader()
        if not self.paper or self.paper["id"] != identifier:
            self.reload(identifier)
        if page is not None and self.paper and self.paper["id"] == identifier:
            if self.reading_splitter.sizes()[0] == 0:
                self.reading_splitter.toggle(0)
            self.view.show_citation(page, rects)

    def pdf_number_input(self, name, width, apply):
        field = QLineEdit()
        field.setObjectName("PdfNumberInput")
        field.setAccessibleName(name)
        field.setToolTip(f"输入{name}，按回车应用")
        field.setAlignment(Qt.AlignmentFlag.AlignCenter)
        field.setFixedWidth(width)
        field.setMaxLength(12)
        field.returnPressed.connect(apply)
        return field

    def update_pdf_page_counter(self):
        total = len(self.doc) if self.paper and self.doc is not None else 0
        self.pdf_page_input.setEnabled(bool(total))
        self.zoom_label.setEnabled(bool(total))
        self.pdf_page_input.setText(str(self.page + 1) if total else "")
        self.page_label.setText(f"/ {total}" if total else "/ —")

    def apply_pdf_page(self):
        if self.doc is not None and len(self.doc):
            try:
                page = int(self.pdf_page_input.text())
            except ValueError:
                page = self.page + 1
            self.view.jump(max(0, min(page - 1, len(self.doc) - 1)))
        self.update_pdf_page_counter()
        self.pdf_page_input.selectAll()

    def apply_pdf_zoom(self):
        try:
            percent = float(self.zoom_label.text().strip().rstrip("%％"))
        except ValueError:
            percent = 0
        if self.doc is not None and 0 < percent < float("inf"):
            self.zoom(percent / 100 / self.view.scale)
        self.zoom_label.setText(f"{self.view.scale:.0%}")
        self.zoom_label.selectAll()

    def reading_page_changed(self, page):
        if not self.paper: return
        self.page = page; self.paper["page"] = page
        self.update_pdf_page_counter()
        self.position_timer.start()

    def pdf_action(self, page, action, text, rects):
        # Selection can be on a partially visible page, distinct from the top page.
        self.selection_action(action, text, rects, page=page)

    def turn(self, delta):
        if self.doc: self.view.jump(self.page + delta * self.view.columns)

    def zoom(self, factor):
        self.view.zoom(factor)

    def toggle_pdf_fullscreen(self):
        state = self.pdf_fullscreen_state
        root_layout = self.centralWidget().layout()
        if state is None:
            if self.doc is None:
                return
            hidden = [root_layout.itemAt(i).widget() for i in range(root_layout.count())]
            hidden = [widget for widget in hidden if widget and widget.isVisible()]
            self.pdf_fullscreen_state = (self.windowState(), self.view.scale, hidden, self.statusBar().isVisible())
            for widget in hidden:
                widget.hide()
            self.statusBar().hide()
            root_layout.addWidget(self.pdf_nav)
            self.pdf_nav.show()
            for columns, control in self.pdf_layout_buttons.items():
                control.setChecked(columns == 1)
                control.show()
            root_layout.addWidget(self.view, 1)
            self.view.show()
            self.showFullScreen()
            self.pdf_fullscreen_button.setIcon(menu_symbol_icon("contract", size=18))
            self.pdf_fullscreen_button.setToolTip("退出 PDF 全屏（Esc）")
            self.pdf_fullscreen_button.setAccessibleName("退出 PDF 全屏")
            self.pdf_escape.setEnabled(True)
            QTimer.singleShot(0, self.set_fullscreen_pdf_zoom)
        else:
            window_state, scale, hidden, status_visible = state
            self.pdf_fullscreen_state = None
            self.pdf_reader_layout.addWidget(self.pdf_nav)
            self.pdf_nav.show()
            for control in self.pdf_layout_buttons.values():
                control.hide()
            self.view.set_columns(1, self.page)
            self.pdf_reader_layout.addWidget(self.view, 1)
            for widget in hidden:
                widget.show()
            self.statusBar().setVisible(status_visible)
            self.setWindowState(window_state)
            self.view.zoom(scale / self.view.scale)
            self.pdf_fullscreen_button.setIcon(menu_symbol_icon("expand", size=18))
            self.pdf_fullscreen_button.setToolTip("PDF 全屏")
            self.pdf_fullscreen_button.setAccessibleName("PDF 全屏")
            self.pdf_escape.setEnabled(False)

    def set_fullscreen_pdf_zoom(self):
        if self.pdf_fullscreen_state is not None:
            self.view.zoom(1.5 / self.view.scale)

    def set_pdf_columns(self, columns):
        self.view.set_columns(columns, self.page)
        for number, control in self.pdf_layout_buttons.items():
            control.setChecked(number == columns)
        self.fit_width()

    def fit_width(self):
        if self.doc:
            columns = self.view.columns
            start = self.page - self.page % columns
            widths = [self.view.pages[i].base_size[0]
                      for i in range(start, min(start + columns, len(self.view.pages)))]
            available = self.view.viewport().width() - 28 - 16 * (len(widths) - 1)
            target = max(.5 / columns, min(4, available / sum(widths)))
            self.view.zoom(target/self.view.scale)

    def open_analysis_page(self, url):
        if url.scheme() != "paperreader-page" or url.host() != "open" or not self.paper or not self.doc:
            return
        query = QUrlQuery(url)
        if query.queryItemValue("paper") != self.paper["id"]:
            return
        try:
            page = int(query.queryItemValue("page"))
        except ValueError:
            return
        if not 1 <= page <= len(self.doc):
            return
        if self.reading_splitter.sizes()[0] == 0:
            self.reading_splitter.toggle(0)
        self.view.show_citation(page - 1, ())
        self.statusBar().showMessage(f"已跳转到原文第 {page} 页", 3000)

    def open_citation(self, url):
        if url.scheme() != "paperreader-cite" or url.host() != "open" or not self.paper or not self.doc:
            return
        query = QUrlQuery(url)
        session = ensure_sessions(self.paper)
        if query.queryItemValue("session") != session["id"]:
            return
        try:
            index = int(query.queryItemValue("message"))
        except ValueError:
            return
        entries = session["messages"]
        if 0 <= index < len(entries) and entries[index]["role"] == "assistant":
            sources = entries[index].get("citations", {})
        elif index == len(entries) + 1 and self.paper["id"] in self.chat_drafts:
            sources = self.chat_drafts[self.paper["id"]][3]
        else:
            return
        source = sources.get(query.queryItemValue("source"))
        if source and 0 <= source["page"] < len(self.doc):
            if self.reading_splitter.sizes()[0] == 0:
                self.reading_splitter.toggle(0)
            self.view.show_citation(source["page"], source["rects"])
