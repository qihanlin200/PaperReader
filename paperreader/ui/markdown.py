"""Markdown display for untrusted model output, without HTML or image loading."""
import time
from PySide6.QtCore import Signal, Qt, QObject, QSignalBlocker, QTimer
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtGui import QTextDocument, QTextCursor, QTextBlockFormat, QTextCharFormat, QTextFormat, QTextTable, QColor, QBrush
from PySide6.QtWidgets import QTextBrowser
from paperreader.services.themes import get_theme
from paperreader.services.retrieval import CITATION
from paperreader.ui.theme import ACCENT, current_theme, document_stylesheet, theme_color
from paperreader.ui.math_render import TOKENS, markdown_html, render_formula

# MathText imports/font discovery and rasterization must not block Qt's event loop.
# One worker also serializes matplotlib's process-wide rendering state.
_math_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='paperreader-math')

_ANALYSIS_SECTION_LABELS = {
    "一句话概括", "研究问题", "核心方法", "方法骨架", "主要贡献",
    "关键证据", "关键结果", "实验结果", "局限与适用范围", "局限性", "阅读建议",
}


def replace_citations(text, replacements):
    def replace(match):
        return replacements.get(match.group(1), match.group(0))

    parts = []
    offset = 0
    for protected in TOKENS.finditer(text):
        parts.extend((CITATION.sub(replace, text[offset:protected.start()]), protected.group()))
        offset = protected.end()
    parts.append(CITATION.sub(replace, text[offset:]))
    return "".join(parts)


class MathResult(QObject):
    ready = Signal(object)


class MarkdownBrowser(QTextBrowser):
    normalize_tables = True
    followUpRequested = Signal(str)
    mathUpdated = Signal()
    headingsChanged = Signal()

    def __init__(self, parent=None, reading_style=False, allow_followup=False):
        super().__init__(parent)
        self.math_resources = {}
        self.math_sources = {}
        self._status_html = ''
        self._body_html = ''
        self._wheel_scrolling_until = 0
        self.reading_style = reading_style
        self.allow_followup = allow_followup
        self.async_math = False
        self.external_math = False
        self._formula_images = {}
        self._math_running = False
        self._markdown_text = ''
        self._markdown_footer = ''
        self._math_result = MathResult(self)
        self._math_result.ready.connect(self._math_ready)
        self._math_render_timer = QTimer(self)
        self._math_render_timer.setSingleShot(True)
        self._math_render_timer.setInterval(120)
        self._math_render_timer.timeout.connect(self._render_math)
        self.document().setDefaultStyleSheet(document_stylesheet())
        self.document().setDocumentMargin(10)
        # The first level only needs room for the marker. Deeper levels add one step each.
        self.document().setIndentWidth(20)
        self.setOpenExternalLinks(False)
        self.setOpenLinks(False)

    def setHtml(self, text):
        self._body_html = text
        super().setHtml(self._status_html + text)
        if not self.normalize_tables:
            return

        def visit(frame):
            for child in frame.childFrames():
                if isinstance(child, QTextTable):
                    fmt = child.format()
                    fmt.setAlignment(Qt.AlignmentFlag.AlignLeft)
                    fmt.setLeftMargin(0); fmt.setRightMargin(0)
                    fmt.setCellPadding(7); fmt.setCellSpacing(0)
                    fmt.setBorderBrush(QBrush(QColor(theme_color('#34465a'))))
                    child.setFormat(fmt)
                    for row in range(child.rows()):
                        for column in range(child.columns()):
                            cell = child.cellAt(row, column)
                            cell_fmt = cell.format()
                            cell_fmt.setBackground(QColor(theme_color('#213243' if row == 0 else '#101824')))
                            cell.setFormat(cell_fmt)
                            cursor = cell.firstCursorPosition()
                            end = cell.lastCursorPosition().position()
                            while cursor.position() <= end:
                                block_fmt = cursor.blockFormat()
                                block_fmt.setAlignment(Qt.AlignmentFlag.AlignLeft)
                                block_fmt.setLeftMargin(0); block_fmt.setTextIndent(0)
                                cursor.setBlockFormat(block_fmt)
                                if not cursor.movePosition(QTextCursor.MoveOperation.NextBlock): break
                visit(child)
        visit(self.document().rootFrame())

    def refresh_theme(self):
        position = self.verticalScrollBar().value()
        self.document().setDefaultStyleSheet(document_stylesheet())
        self.setHtml(self._body_html)
        if self.reading_style:
            self.format_reading_text()
        self.verticalScrollBar().setValue(position)

    def wheelEvent(self, event):
        self._wheel_scrolling_until = time.monotonic() + 0.18
        super().wheelEvent(event)

    def is_user_scrolling(self):
        return self.verticalScrollBar().isSliderDown() or time.monotonic() < self._wheel_scrolling_until

    def set_status_html(self, html):
        if html == self._status_html: return
        scrollbar = self.verticalScrollBar()
        position = scrollbar.value()
        following = position == scrollbar.maximum()
        self._status_html = html
        self.setHtml(self._body_html)
        if self.reading_style: self.format_reading_text()
        scrollbar.setValue(scrollbar.maximum() if following else position)

    def selected_source(self):
        selection = self.textCursor()
        output = []
        for position in range(selection.selectionStart(), selection.selectionEnd()):
            cursor = QTextCursor(self.document()); cursor.setPosition(position)
            cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
            text = cursor.selectedText().replace("\u2029", "\n")
            if text == "\ufffc":
                source = self.math_sources.get(cursor.charFormat().toImageFormat().name())
                text = "\\(" + source + "\\)" if source else text
            output.append(text)
        return "".join(output)

    def headings(self):
        """Return currently rendered headings, including partial streamed reports."""
        result = []
        block = self.document().begin()
        while block.isValid():
            level = block.blockFormat().headingLevel()
            title = block.text().strip()
            if not level and not block.textList() and title.rstrip("：:") in _ANALYSIS_SECTION_LABELS:
                level = 3
            if level and title:
                result.append((level, title, block.position()))
            block = block.next()
        return result

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        if self.allow_followup:
            text = self.selected_source().strip()
            menu.addSeparator()
            action = menu.addAction("针对所选内容提问")
            action.setEnabled(bool(text))
            action.triggered.connect(lambda: self.followUpRequested.emit(text))
        menu.exec(event.globalPos())
        menu.deleteLater()

    def loadResource(self, resource_type, name):
        # Only internally rendered math images; never external or local-file images.
        return self.math_resources.get(name.toString()) if name is not None else None

    def set_markdown(self, text, *, footer_html=""):
        self._markdown_text = text
        self._markdown_footer = footer_html
        scrollbar = self.verticalScrollBar()
        previous = scrollbar.value()
        following = previous == scrollbar.maximum()
        self.math_resources.clear(); self.math_sources.clear()
        self.setHtml(self.html_fragment(text) + footer_html)
        if self.reading_style:
            self.format_reading_text()
        scrollbar.setValue(scrollbar.maximum() if following else previous)
        self.headingsChanged.emit()

    def html_fragment(self, text):
        pending = set()
        def cached_formula(source):
            if source not in self._formula_images:
                pending.add(source)
                raise LookupError(source)
            image = self._formula_images[source]
            if image is None: raise ValueError(source)
            return image
        result = markdown_html(text, self.math_resources, self.math_sources, self.viewport().width()-32,
                               renderer=cached_formula if self.async_math else render_formula)
        if pending and not self._math_running:
            self._math_running = True
            signal = self._math_result
            def work():
                images = {}
                for source in pending:
                    try: images[source] = render_formula(source)
                    except Exception: images[source] = None
                try: signal.ready.emit(images)
                except RuntimeError: pass  # The window may have been closed.
            _math_executor.submit(work)
        return result

    def _math_ready(self, images):
        self._math_running = False
        self._formula_images.update(images)
        # Bound retained images while keeping the current batch available.
        if len(self._formula_images) > 512: self._formula_images = dict(images)
        self._render_math()

    def _render_math(self):
        if self.is_user_scrolling():
            self._math_render_timer.start()
            return
        if self.external_math: self.mathUpdated.emit()
        else: self.set_markdown(self._markdown_text, footer_html=self._markdown_footer)


    def format_reading_text(self):
        """Qt Markdown does not consistently apply CSS paragraph metrics; format blocks directly."""
        heading_background = get_theme(current_theme()).heading_background
        block = self.document().begin()
        while block.isValid():
            cursor = QTextCursor(block)
            fmt = block.blockFormat()
            level = fmt.headingLevel()
            if not level and not block.textList() and block.text().strip().rstrip("：:") in _ANALYSIS_SECTION_LABELS:
                level = 3
            fmt.setLineHeight(140 if level else 150, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            fmt.setTopMargin(14 if level and block.blockNumber() else 0)
            fmt.setBottomMargin(6 if level else (4 if block.textList() else 9))
            if level and heading_background:
                fmt.setBackground(QColor(heading_background))
                fmt.setLeftMargin(8)
                fmt.setLineHeight(175, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            cursor.setBlockFormat(fmt)
            size = {1: 18, 2: 16, 3: 14, 4: 13, 5: 13, 6: 13}.get(level, 13)
            chars = QTextCharFormat()
            chars.setProperty(QTextFormat.Property.FontPixelSize, size)
            chars.setProperty(QTextFormat.Property.FontSizeAdjustment, 0)
            if level:
                chars.setForeground(QColor(theme_color(ACCENT)))
            cursor.setPosition(block.position() + block.length() - 1, QTextCursor.MoveMode.KeepAnchor)
            cursor.mergeCharFormat(chars)
            block = block.next()


from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget, QTextEdit


class MarkdownEditor(QWidget):
    """Store Markdown source, with a live rendered preview."""
    textChanged = Signal()

    def __init__(self, placeholder="", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.source = QTextEdit()
        self.source.setAcceptRichText(False)
        self.source.setPlaceholderText(placeholder)
        self.preview = MarkdownBrowser()
        self.tabs.addTab(self.source, "Markdown 编辑")
        self.tabs.addTab(self.preview, "预览")
        layout.addWidget(self.tabs)
        self.source.textChanged.connect(self.changed)
        self.tabs.currentChanged.connect(self.refresh_visible_preview)

    def changed(self):
        self.preview.set_markdown(self.toPlainText())
        self.textChanged.emit()

    def refresh_visible_preview(self):
        if self.tabs.currentWidget() is self.preview:
            # Read the editor again after the preview is visible and sized.
            self.preview.set_markdown(self.toPlainText())

    def toPlainText(self):
        return self.source.toPlainText()

    def setPlainText(self, text, *, reveal_append=False):
        if not reveal_append:
            self.source.setPlainText(text)
            return
        with QSignalBlocker(self.source):
            self.source.setPlainText(text)
        self.changed()
        if self.preview.isVisible():
            scrollbar = self.preview.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def clear(self):
        self.source.clear()

    def setFocus(self):
        self.tabs.setCurrentIndex(0)
        self.source.setFocus()
