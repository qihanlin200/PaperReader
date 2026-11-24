"""Markdown display for untrusted model output, without HTML or image loading."""
import re
import time
import hashlib
from PySide6.QtCore import Signal, Qt, QObject, QSignalBlocker, QTimer, QRectF
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtGui import QTextDocument, QTextCursor, QTextBlockFormat, QTextCharFormat, QTextFormat, QTextTable, QColor, QBrush, QPainter, QPainterPath
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
_PAGE_LABEL = r'(?:第\s*[1-9]\d*\s*页|p\.\s*[1-9]\d*)'
_ANALYSIS_PAGE = re.compile(r'(?<![\w/])(?:\[(?P<bracketed>' + _PAGE_LABEL + r')\]|(?P<plain>' + _PAGE_LABEL + r'))(?!\d)', re.I)
_MARKDOWN_LINK = re.compile(r'!?\[[^\]\n]*\]\([^\n)]*\)')


def link_analysis_pages(text, paper_id, page_count):
    """Link cited PDF pages while leaving math, code, and existing links untouched."""
    def link_plain(segment):
        def replace(match):
            label = match.group('bracketed') or match.group('plain')
            page = int(re.search(r'\d+', label).group())
            if page > page_count:
                return match.group()
            return f'[{label}](paperreader-page://open?paper={paper_id}&page={page})'

        output = []
        offset = 0
        for existing in _MARKDOWN_LINK.finditer(segment):
            output.append(_ANALYSIS_PAGE.sub(replace, segment[offset:existing.start()]))
            output.append(existing.group())
            offset = existing.end()
        output.append(_ANALYSIS_PAGE.sub(replace, segment[offset:]))
        return ''.join(output)

    output = []
    offset = 0
    for protected in TOKENS.finditer(text):
        output.append(link_plain(text[offset:protected.start()]))
        output.append(protected.group())
        offset = protected.end()
    output.append(link_plain(text[offset:]))
    return ''.join(output)


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
    figurePreviewRequested = Signal(object, str)

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
        self._trusted_figures = {}
        self._figure_labels = {}
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
        document = self.document()
        layout_enabled = document.isLayoutEnabled()
        document.setLayoutEnabled(False)
        try:
            self._replace_html(text)
        finally:
            document.setLayoutEnabled(layout_enabled)

    def _replace_html(self, text):
        self._body_html = text
        super().setHtml(self._status_html + text)
        if not self.normalize_tables:
            return

        def visit(frame):
            for child in frame.childFrames():
                if isinstance(child, QTextTable):
                    if child.rows() == 1 and child.format().border() == 0:
                        visit(child)
                        continue
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

    def refresh_theme(self, old_html=None, new_html=None):
        position = self.verticalScrollBar().value()
        self.document().setDefaultStyleSheet(document_stylesheet())
        document = self.document()
        layout_enabled = document.isLayoutEnabled()
        document.setLayoutEnabled(False)
        try:
            body = self._body_html if old_html is None else self._body_html.replace(old_html, new_html)
            self._replace_html(body)
            if self.reading_style:
                self.format_reading_text()
        finally:
            document.setLayoutEnabled(layout_enabled)
        self.verticalScrollBar().setValue(position)

    def wheelEvent(self, event):
        self._wheel_scrolling_until = time.monotonic() + 0.18
        super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event):
        cursor = self.cursorForPosition(event.position().toPoint())
        for position in (cursor.position(), cursor.position() - 1):
            if position < 0:
                continue
            candidate = QTextCursor(self.document())
            candidate.setPosition(position)
            candidate.movePosition(QTextCursor.MoveOperation.NextCharacter,
                                   QTextCursor.MoveMode.KeepAnchor)
            image_format = candidate.charFormat().toImageFormat()
            url = image_format.name()
            if url.startswith('paperreader-figure:') and url in self.math_resources:
                self.figurePreviewRequested.emit(self.math_resources[url], self._figure_labels.get(url, '论文原图'))
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

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
        # Only app-rendered math and PDF excerpts; never model-supplied image URLs.
        return self.math_resources.get(name.toString()) if name is not None else None

    def set_markdown(self, text, *, footer_html="", reuse=False, trusted_figures=None):
        trusted_figures = trusted_figures or {}
        if reuse and (text, footer_html, tuple(trusted_figures)) == (
                self._markdown_text, self._markdown_footer, tuple(self._trusted_figures)):
            return
        self._markdown_text = text
        self._markdown_footer = footer_html
        self._trusted_figures = trusted_figures
        self._figure_labels = {
            'paperreader-figure:' + hashlib.sha256(token.encode()).hexdigest(): card[1]
            for token, card in trusted_figures.items()
        }
        scrollbar = self.verticalScrollBar()
        previous = scrollbar.value()
        following = previous == scrollbar.maximum()
        document = self.document()
        layout_enabled = document.isLayoutEnabled()
        document.setLayoutEnabled(False)
        try:
            self.math_resources.clear()
            self.math_sources.clear()
            self._replace_html(self.html_fragment(text) + footer_html)
            if self.reading_style:
                self.format_reading_text()
        finally:
            document.setLayoutEnabled(layout_enabled)
        scrollbar.setValue(scrollbar.maximum() if following else previous)
        self.headingsChanged.emit()

    def html_fragment(self, text):
        pending = set()
        math_font_px = 13 if self.reading_style else 14
        def cached_formula(source, *, max_width=None):
            key = (source, max_width)
            if key not in self._formula_images:
                pending.add(key)
                raise LookupError(source)
            image = self._formula_images[key]
            if image is None: raise ValueError(source)
            return image
        def direct_formula(source, *, max_width=None):
            return render_formula(source, math_font_px, max_width)
        available_width = min(self.width(), self.viewport().width()) - 32
        result = markdown_html(text, self.math_resources, self.math_sources, available_width,
                               renderer=cached_formula if self.async_math else
                               direct_formula, trusted_figures=getattr(self, '_trusted_figures', {}))
        if pending and not self._math_running:
            self._math_running = True
            signal = self._math_result
            def work():
                images = {}
                for source, max_width in pending:
                    key = (source, max_width)
                    try: images[key] = render_formula(source, math_font_px, max_width)
                    except Exception: images[key] = None
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_math_render_timer') and 'paperreader-flow' in self._markdown_text:
            self._math_render_timer.start()

    def _render_math(self):
        if self.is_user_scrolling():
            self._math_render_timer.start()
            return
        if self.external_math: self.mathUpdated.emit()
        else: self.set_markdown(self._markdown_text, footer_html=self._markdown_footer,
                                trusted_figures=self._trusted_figures)


    def format_reading_text(self):
        """Qt Markdown does not consistently apply CSS paragraph metrics; format blocks directly."""
        heading_background = get_theme(current_theme()).heading_background
        block = self.document().begin()
        previous = None
        figure_indent = None
        while block.isValid():
            cursor = QTextCursor(block)
            fmt = block.blockFormat()
            level = fmt.headingLevel()
            is_figure = False
            if block.text().startswith('\ufffc'):
                image_cursor = QTextCursor(block)
                image_cursor.movePosition(QTextCursor.MoveOperation.NextCharacter,
                                          QTextCursor.MoveMode.KeepAnchor)
                is_figure = image_cursor.charFormat().toImageFormat().name().startswith('paperreader-figure:')
            if is_figure:
                preceding = previous
                while preceding is not None and preceding.text().strip() == '':
                    preceding = preceding.previous() if preceding.previous().isValid() else None
                if preceding is not None:
                    text_list = preceding.textList()
                    figure_indent = text_list.format().indent() if text_list else preceding.blockFormat().indent()
                else:
                    figure_indent = 0
            if is_figure or (figure_indent is not None and block.text().strip() in self._figure_labels.values()):
                fmt.setAlignment(Qt.AlignmentFlag.AlignLeft)
                fmt.setIndent(figure_indent)
                fmt.setLeftMargin(0)
                fmt.setTextIndent(0)
            elif figure_indent is not None:
                figure_indent = None
            if not level and not block.textList() and block.text().strip().rstrip("：:") in _ANALYSIS_SECTION_LABELS:
                level = 3
            standalone_image = block.text().strip() == '\ufffc'
            fmt.setLineHeight(100 if standalone_image else 150,
                              QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            fmt.setTopMargin(12 if level and block.blockNumber() else 0)
            fmt.setBottomMargin(0 if standalone_image else 6)
            if level and heading_background:
                fmt.setBackground(QColor(heading_background))
                fmt.setLeftMargin(8)
            cursor.setBlockFormat(fmt)
            size = {1: 18, 2: 16, 3: 14, 4: 13, 5: 13, 6: 13}.get(level, 13)
            chars = QTextCharFormat()
            chars.setProperty(QTextFormat.Property.FontPixelSize, size)
            chars.setProperty(QTextFormat.Property.FontSizeAdjustment, 0)
            if level:
                chars.setForeground(QColor(theme_color(ACCENT)))
            cursor.setPosition(block.position() + block.length() - 1, QTextCursor.MoveMode.KeepAnchor)
            cursor.mergeCharFormat(chars)
            previous = block
            block = block.next()


from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget, QTextEdit, QPushButton, QFrame


class ChatBrowser(MarkdownBrowser):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PaperChat")
        self.document().setDocumentMargin(5)

    def paintEvent(self, event):
        super().paintEvent(event)
        document = self.document()
        layout = document.documentLayout()
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRegion(event.region())

        for frame in document.rootFrame().childFrames():
            if not isinstance(frame, QTextTable) or frame.rows() != 1:
                continue
            bubble = frame
            if frame.columns() == 2:
                bubble = next((child for child in frame.childFrames() if isinstance(child, QTextTable)), None)
            if bubble is None or bubble.columns() != 1:
                continue
            bounds = QRectF(layout.frameBoundingRect(bubble))
            # Qt reports the table origin at the padded content corner.
            cell_format = bubble.cellAt(0, 0).format().toTableCellFormat()
            bounds.translate(
                -cell_format.leftPadding() - self.horizontalScrollBar().value(),
                -cell_format.topPadding() - self.verticalScrollBar().value(),
            )
            if not bounds.intersects(QRectF(event.rect())):
                continue
            rectangle = QPainterPath()
            rectangle.addRect(bounds)
            rounded = QPainterPath()
            rounded.addRoundedRect(bounds, 9, 9)
            painter.fillPath(rectangle.subtracted(rounded), self.viewport().palette().base())


class MarkdownEditor(QWidget):
    """Store Markdown source, with a live rendered preview."""
    textChanged = Signal()

    def __init__(self, placeholder="", parent=None):
        super().__init__(parent)
        self.setObjectName("MarkdownEditor")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        view_bar = QWidget()
        view_bar.setObjectName("AnalysisViewBar")
        view_layout = QHBoxLayout(view_bar)
        view_layout.setContentsMargins(0, 0, 0, 0)
        view_layout.setSpacing(0)
        self.view_buttons = []
        for index, label in enumerate(("Markdown 编辑", "预览")):
            control = QPushButton(label)
            control.setObjectName("AnalysisViewButton")
            control.setProperty("analysisSide", "left" if index == 0 else "right")
            control.setCheckable(True)
            control.setFixedHeight(26)
            control.clicked.connect(lambda checked=False, selected=index: self.tabs.setCurrentIndex(selected))
            view_layout.addWidget(control, 1)
            self.view_buttons.append(control)
        layout.addWidget(view_bar)
        self.tabs = QStackedWidget()
        self.source = QTextEdit()
        self.source.setObjectName("NoteMarkdownSource")
        self.source.setFrameShape(QFrame.Shape.NoFrame)
        self.source.setAcceptRichText(False)
        self.source.setPlaceholderText(placeholder)
        self.preview = MarkdownBrowser()
        self.preview.setObjectName("NoteMarkdownPreview")
        self.preview.setFrameShape(QFrame.Shape.NoFrame)
        self.tabs.addWidget(self.source)
        self.tabs.addWidget(self.preview)
        layout.addWidget(self.tabs)
        self.source.textChanged.connect(self.changed)
        self.tabs.currentChanged.connect(self.refresh_visible_preview)
        self.tabs.currentChanged.connect(self.sync_view_buttons)
        self.sync_view_buttons(0)

    def sync_view_buttons(self, index):
        for position, control in enumerate(self.view_buttons):
            control.setChecked(position == index)

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
