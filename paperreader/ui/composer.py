"""Plain text composer with an inset footer, outside the text editing viewport."""
from PySide6.QtWidgets import QTextEdit, QWidget, QHBoxLayout


class QuestionEdit(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setViewportMargins(0, 0, 0, 48)
        self.footer = QWidget(self)
        self.footer.setObjectName('ComposerFooter')
        self.footer_layout = QHBoxLayout(self.footer)
        self.footer_layout.setContentsMargins(4, 4, 4, 4)
        self.footer_layout.setSpacing(8)
        self.setMinimumHeight(140)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'footer'):
            self.footer.setGeometry(8, self.height()-48, max(0, self.width()-16), 40)
