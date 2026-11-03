"""Markdown display for untrusted model output, without HTML or image loading."""
from PySide6.QtGui import QTextDocument, QTextCursor, QTextBlockFormat, QTextCharFormat, QTextFormat
from PySide6.QtWidgets import QTextBrowser
from paperreader.ui.theme import DOCUMENT_CSS


class MarkdownBrowser(QTextBrowser):
    def __init__(self, parent=None, reading_style=False):
        super().__init__(parent)
        self.reading_style = reading_style
        self.document().setDefaultStyleSheet(DOCUMENT_CSS)
        self.document().setDocumentMargin(10)
        self.setOpenExternalLinks(False)
        self.setOpenLinks(False)

    def loadResource(self, resource_type, name):
        # Model output must not read local files or fetch tracking images.
        return None

    def set_markdown(self, text):
        scrollbar = self.verticalScrollBar()
        previous = scrollbar.value()
        following = previous >= scrollbar.maximum() - 20
        self.document().setMarkdown(
            text,
            QTextDocument.MarkdownFeature.MarkdownDialectGitHub
            | QTextDocument.MarkdownFeature.MarkdownNoHTML,
        )
        if self.reading_style:
            self.format_reading_text()
        scrollbar.setValue(scrollbar.maximum() if following else previous)


    def format_reading_text(self):
        """Qt Markdown does not consistently apply CSS paragraph metrics; format blocks directly."""
        block = self.document().begin()
        while block.isValid():
            cursor = QTextCursor(block)
            fmt = block.blockFormat()
            level = fmt.headingLevel()
            fmt.setLineHeight(140 if level else 150, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            fmt.setTopMargin(14 if level and block.blockNumber() else 0)
            fmt.setBottomMargin(6 if level else (4 if block.textList() else 9))
            cursor.setBlockFormat(fmt)
            size = {1: 18, 2: 16, 3: 14, 4: 13, 5: 13, 6: 13}.get(level, 13)
            chars = QTextCharFormat()
            chars.setProperty(QTextFormat.Property.FontPixelSize, size)
            chars.setProperty(QTextFormat.Property.FontSizeAdjustment, 0)
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
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

    def changed(self):
        self.preview.set_markdown(self.toPlainText())
        self.textChanged.emit()

    def toPlainText(self):
        return self.source.toPlainText()

    def setPlainText(self, text):
        self.source.setPlainText(text)

    def clear(self):
        self.source.clear()

    def setFocus(self):
        self.tabs.setCurrentIndex(0)
        self.source.setFocus()
