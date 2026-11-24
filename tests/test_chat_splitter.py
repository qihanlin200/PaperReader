"""The reading chat composer resizes only through vertical dragging."""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
import fitz

from paperreader.services.library import Library
from paperreader.ui.splitter import ChatResizeHandle, ChatVerticalSplitter
from paperreader.ui.theme import apply_theme
from paperreader.ui.window import Window


class ChatSplitterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_drag_resizes_but_double_click_does_not_collapse(self):
        apply_theme("dark")
        splitter = ChatVerticalSplitter()
        output, composer = QWidget(), QWidget()
        output.setMinimumHeight(120)
        composer.setMinimumHeight(104)
        splitter.addWidget(output)
        splitter.addWidget(composer)
        splitter.resize(360, 600)
        splitter.setSizes([450, 140])
        splitter.show()
        self.app.processEvents()
        try:
            handle = splitter.handle(1)
            self.assertIsInstance(handle, ChatResizeHandle)
            self.assertEqual(handle.cursor().shape(), Qt.CursorShape.SplitVCursor)
            before = splitter.sizes()
            QTest.mouseDClick(handle, Qt.MouseButton.LeftButton)
            self.app.processEvents()
            self.assertEqual(splitter.sizes(), before)

            point = QPoint(handle.width() // 2, handle.height() // 2)
            QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=point)
            QTest.mouseMove(handle, point + QPoint(0, -45))
            QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=point + QPoint(0, -45))
            self.app.processEvents()
            self.assertGreater(splitter.sizes()[1], before[1])
            self.assertGreaterEqual(splitter.sizes()[0], 120)
        finally:
            splitter.close()

    def test_latest_answer_stays_at_bottom_while_dragging_up(self):
        with tempfile.TemporaryDirectory() as root:
            library = Library(root)
            document = fitz.open()
            document.new_page().insert_text((72, 72), "PaperReader")
            paper = library.import_pdf(document.tobytes(), "Chat resize")
            document.close()
            window = Window(library=library)
            window.resize(1500, 900)
            window.show()
            window.reload(paper["id"])
            try:
                window.chat.setHtml("<p>答复内容</p>" * 90)
                self.app.processEvents()
                scrollbar = window.chat.verticalScrollBar()
                self.assertGreater(scrollbar.maximum(), 0)
                scrollbar.setValue(scrollbar.maximum())
                previous_max = scrollbar.maximum()
                previous_input_height = window.question.height()
                handle = window.chat_splitter.handle(1)
                point = QPoint(handle.width() // 2, handle.height() // 2)
                QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=point)
                QTest.mouseMove(handle, point + QPoint(0, -70))
                QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=point + QPoint(0, -70))
                self.app.processEvents()
                self.assertGreater(window.question.height(), previous_input_height)
                self.assertGreater(scrollbar.maximum(), previous_max)
                self.assertEqual(scrollbar.value(), scrollbar.maximum())

                scrollbar.setValue(50)
                point = QPoint(handle.width() // 2, handle.height() // 2)
                QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=point)
                QTest.mouseMove(handle, point + QPoint(0, 30))
                QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=point + QPoint(0, 30))
                self.app.processEvents()
                self.assertEqual(scrollbar.value(), 50)
            finally:
                window.close()
                library.db.close()


if __name__ == "__main__":
    unittest.main()
