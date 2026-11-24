import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QNativeGestureEvent, QPointingDevice, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from paperreader.ui.figure_preview import FigurePreview
from paperreader.ui.markdown import MarkdownBrowser


class FigurePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_pinch_zoom_and_escape(self):
        image = QImage(800, 500, QImage.Format.Format_RGB888)
        image.fill(Qt.GlobalColor.red)
        preview = FigurePreview(image, '原文图 1')
        preview.resize(1000, 700)
        preview.show()
        centre = preview.rect().center()
        event = QNativeGestureEvent(Qt.NativeGestureType.ZoomNativeGesture,
                                    QPointingDevice.primaryPointingDevice(), 1,
                                    QPointF(centre), QPointF(centre),
                                    QPointF(preview.mapToGlobal(centre)), .2, QPointF())
        self.assertTrue(preview.event(event))
        self.assertGreater(preview.zoom_level, 1)
        QTest.keyClick(preview, Qt.Key.Key_Escape)
        self.assertFalse(preview.isVisible())

    def test_click_outside_image_closes(self):
        image = QImage(800, 500, QImage.Format.Format_RGB888)
        image.fill(Qt.GlobalColor.red)
        preview = FigurePreview(image, '原文图 1')
        preview.resize(1000, 700)
        preview.show()
        QTest.mouseClick(preview, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
        self.assertFalse(preview.isVisible())

    def test_double_click_on_report_image_requests_preview(self):
        browser = MarkdownBrowser(reading_style=True)
        browser.resize(480, 500)
        image = QImage(400, 220, QImage.Format.Format_RGB888)
        image.fill(Qt.GlobalColor.red)
        browser.set_markdown('引用原文图 1。\n\nPRPAPERFIGURE1END',
                             trusted_figures={'PRPAPERFIGURE1END':
                                              (image, '原文图 1', 'paperreader-page://open?page=1')})
        browser.show()
        self.app.processEvents()
        seen = []
        browser.figurePreviewRequested.connect(lambda preview, label: seen.append((preview, label)))
        block = browser.document().begin()
        while block.isValid() and '\ufffc' not in block.text():
            block = block.next()
        self.assertTrue(block.isValid())
        cursor = QTextCursor(browser.document())
        cursor.setPosition(block.position() + block.text().index('\ufffc'))
        rect = browser.cursorRect(cursor)
        QTest.mouseDClick(browser.viewport(), Qt.MouseButton.LeftButton,
                         pos=QPoint(rect.x() + 20, rect.y() + 20))
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][1], '原文图 1')
        browser.close()

    def test_report_figure_and_caption_align_with_preceding_list_text(self):
        browser = MarkdownBrowser(reading_style=True)
        browser.resize(700, 650)
        image = QImage(400, 220, QImage.Format.Format_RGB888)
        image.fill(Qt.GlobalColor.red)
        browser.set_markdown('- 局限与疑点：\n  - 图 3 的数值需要看原图。\n\nPRPAPERFIGURE3END',
                             trusted_figures={'PRPAPERFIGURE3END':
                                              (image, '原文图 3', 'paperreader-page://open?page=5')})
        browser.show()
        self.app.processEvents()
        blocks = []
        block = browser.document().begin()
        while block.isValid():
            blocks.append(block)
            block = block.next()

        def left(block):
            cursor = QTextCursor(browser.document())
            cursor.setPosition(block.position())
            return browser.cursorRect(cursor).x()

        self.assertEqual(left(blocks[1]), left(blocks[2]))
        self.assertEqual(left(blocks[2]), left(blocks[3]))
        browser.close()
