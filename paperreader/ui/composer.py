"""Plain text composer with an inset footer, outside the text editing viewport."""
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTextEdit, QWidget, QHBoxLayout

MACOS = sys.platform == 'darwin'


class QuestionEdit(QTextEdit):
    submitRequested = Signal()

    def __init__(self, parent=None, *, footer_height=40):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setToolTip('回车发送；Option（⌥）+回车换行' if MACOS else '回车发送；Ctrl+回车换行')
        self.footer_height = footer_height
        self.setViewportMargins(0, 0, 0, footer_height + 8)
        self.footer = QWidget(self)
        self.footer.setObjectName('ComposerFooter')
        self.footer_layout = QHBoxLayout(self.footer)
        self.footer_layout.setContentsMargins(4, 4, 4, 4)
        self.footer_layout.setSpacing(8)
        self.setMinimumHeight(140)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'footer'):
            self.footer.setGeometry(8, self.height()-self.footer_height-8, max(0, self.width()-16), self.footer_height)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            newline_modifier = Qt.KeyboardModifier.AltModifier if MACOS else Qt.KeyboardModifier.ControlModifier
            if event.modifiers() == newline_modifier:
                self.insertPlainText('\n')
            elif not event.isAutoRepeat():
                self.submitRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)
