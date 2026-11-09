import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton
from paperreader.ui.markdown import MarkdownBrowser
from paperreader.ui.outline import AnalysisOutline


class OutlineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_outline_refreshes_with_streamed_headings_and_navigates(self):
        browser = MarkdownBrowser(reading_style=True)
        button = QPushButton('目录')
        outline = AnalysisOutline()
        browser.set_markdown('# 快速概要\n\n## 研究问题\n\n内容')
        outline.show_for(button, browser)
        self.assertEqual(outline.items.count(), 2)
        outline.hide()
        browser.set_markdown('# 快速概要\n\n## 研究问题\n\n内容\n\n## 方法框架\n\n更多内容')
        outline.show_for(button, browser)
        self.assertEqual(outline.items.count(), 3)
        item = outline.items.item(2)
        outline.go_to_item(item)
        self.assertEqual(browser.textCursor().position(), item.data(Qt.ItemDataRole.UserRole))
        self.assertFalse(outline.isVisible())
