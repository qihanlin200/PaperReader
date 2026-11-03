import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import time
import unittest
from unittest.mock import patch
import fitz
from PySide6.QtWidgets import QApplication
from paperreader.services.library import Library
from paperreader.ui.window import Window


class StreamingUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.library = Library(self.temp.name)
        doc = fitz.open(); doc.new_page().insert_text((72, 72), 'Paper text')
        self.paper = self.library.import_pdf(doc.tobytes(), 'Test'); doc.close()
        self.lib_patch = patch('paperreader.ui.window.Library', return_value=self.library)
        self.key_patch = patch('paperreader.ui.window.keyring.get_password', return_value='test')
        self.lib_patch.start(); self.key_patch.start()
        self.window = Window(); self.window.reload(self.paper['id'])
        self.errors = []
        self.window.error = self.errors.append

    def tearDown(self):
        self.wait()
        self.window.close()
        self.lib_patch.stop(); self.key_patch.stop()
        self.library.db.close(); self.temp.cleanup()

    def wait(self):
        deadline = time.monotonic() + 5
        while self.window.busy and time.monotonic() < deadline:
            self.app.processEvents(); time.sleep(.005)
        self.app.processEvents()
        self.assertFalse(self.window.busy)

    @staticmethod
    def model(config, key, messages, on_chunk=None):
        assert on_chunk is not None
        for text in ['## Answer\n\n', '**Markdown** result']:
            on_chunk(text); time.sleep(.01)
        return '## Answer\n\n**Markdown** result'

    def test_chat_translation_notes_markdown(self):
        with patch('paperreader.ui.window.complete', side_effect=self.model):
            self.window.question.setPlainText('**Question**\n\n- detail')
            self.window.ask(); self.wait()
            self.assertIn('<h2', self.window.chat.document().toHtml())
            self.assertEqual(len(self.library.all()[0]['messages']), 2)
            self.window.show_translation('Original'); self.wait()
            from paperreader.ui.markdown import MarkdownBrowser
            browsers = self.window.translation_dialog.findChildren(MarkdownBrowser)
            self.assertIn('Markdown result', browsers[-1].toPlainText())
            self.window.translation_dialog.close()
        self.window.notes.setPlainText('# Note\n\n**Saved**'); self.window.save_notes()
        self.assertIn('<h1', self.window.notes.preview.document().toHtml())
        self.assertEqual(self.library.all()[0]['notes'], '# Note\n\n**Saved**')
        self.assertFalse(self.errors)

    def test_interrupted_chat_preserves_partial(self):
        def broken(config, key, messages, on_chunk=None):
            on_chunk('partial answer')
            raise ValueError('disconnected')
        with patch('paperreader.ui.window.complete', side_effect=broken):
            self.window.question.setPlainText('question')
            self.window.ask(); self.wait()
        answer = self.library.all()[0]['messages'][-1]['content']
        self.assertIn('partial answer', answer)
        self.assertIn('生成中断', answer)
        self.assertTrue(self.errors)
        self.assertEqual(self.window.question.toPlainText(), 'question')


    def test_continuous_scroll_lazy_render_and_selection_page(self):
        doc = fitz.open()
        for i in range(20): doc.new_page().insert_text((72, 72), f"Page {i}")
        paper = self.library.import_pdf(doc.tobytes(), 'Long paper'); doc.close()
        self.window.reload(paper['id']); self.window.show()
        for _ in range(10): self.app.processEvents()
        reader = self.window.view
        reader.jump(10)
        for _ in range(10): self.app.processEvents()
        self.assertEqual(self.window.page, 10)
        self.assertLess(sum(v.page is not None for v in reader.pages), 7)
        self.assertIsNotNone(reader.pages[10].page)
        reader.verticalScrollBar().setValue(reader.offsets[11] + 50)
        for _ in range(10): self.app.processEvents()
        self.assertEqual(self.window.page, 11)
        self.window.pdf_action(12, '高亮', 'selected', [[72, 60, 110, 75]])
        self.assertEqual(self.window.paper['marks'][-1]['page'], 12)
        reader.zoom(1.18)
        for _ in range(10): self.app.processEvents()
        self.assertEqual(self.window.page, 11)
        self.assertEqual(len(reader.pages), 20)

    def test_drag_selection_mouse_events_and_context_action(self):
        from PySide6.QtTest import QTest
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtGui import QContextMenuEvent
        from paperreader.ui.pdf import PageView
        doc = fitz.open()
        page = doc.new_page(); page.insert_text((72, 72), 'Alpha Beta Gamma')
        view = PageView(); view.display(page, []); view.show()
        words = page.get_text('words', sort=True)
        y = int((words[0][1] + words[0][3])/2 * view.scale)
        start = QPoint(int(words[0][0]*view.scale)+1, y)
        end = QPoint(int(words[1][2]*view.scale)-1, y)
        # Same-height drags used to produce a zero-height PDF rectangle and no words.
        QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual(view.selected()[0], 'Alpha Beta')
        emitted = []
        view.action.connect(lambda *args: emitted.append(args))
        from unittest.mock import MagicMock
        menu = MagicMock()
        menu.exec.return_value.text.return_value = "复制"
        with patch('paperreader.ui.pdf.QMenu', return_value=menu):
            view.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, end, view.mapToGlobal(end)))
        self.assertEqual(emitted[0][0], '复制')
        self.assertEqual(emitted[0][1], 'Alpha Beta')
        QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=end)
        QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=start)
        self.assertEqual(view.selected()[0], 'Alpha Beta')
        view.close(); doc.close()

    def test_splitter_click_collapse_restore_and_hold_drag(self):
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt, QPoint
        self.window.show(); self.app.processEvents()
        splitter = self.window.splitter
        handle = splitter.handle(1)
        QTest.mouseClick(handle, Qt.MouseButton.LeftButton)
        self.assertEqual(splitter.sizes()[0], 0)
        QTest.mouseClick(handle, Qt.MouseButton.LeftButton)
        self.assertGreater(splitter.sizes()[0], 0)
        before = splitter.sizes()[0]
        QTest.mousePress(handle, Qt.MouseButton.LeftButton)
        QTest.qWait(handle.HOLD_MS + 150)
        self.assertTrue(handle.dragging)
        QTest.mouseRelease(handle, Qt.MouseButton.LeftButton)
        self.assertEqual(splitter.sizes()[0], before)
        QTest.mousePress(handle, Qt.MouseButton.LeftButton)
        QTest.qWait(handle.HOLD_MS + 150)
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QEvent, QPointF
        local = handle.rect().center() + QPoint(35, 0)
        move = QMouseEvent(QEvent.Type.MouseMove, QPointF(local), QPointF(handle.mapToGlobal(local)),
                           Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(handle, move)
        self.assertNotEqual(splitter.sizes()[0], before)
        QTest.mouseRelease(handle, Qt.MouseButton.LeftButton)
        # Shift-click can collapse/restore the pane on the other side.
        QTest.mouseClick(splitter.handle(3), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(splitter.sizes()[3], 0)
        QTest.mouseClick(splitter.handle(3), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)
        self.assertGreater(splitter.sizes()[3], 0)


    def test_retina_render_resolution_and_native_pinch(self):
        from math import ceil
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QNativeGestureEvent, QPointingDevice
        from paperreader.ui.pdf import PageView
        doc = fitz.open(); page = doc.new_page()
        page.insert_text((72, 72), 'Retina test')
        view = PageView()
        with patch.object(PageView, 'devicePixelRatioF', return_value=2.0):
            view.display(page, [])
        self.assertEqual(view.width(), ceil(page.rect.width * view.scale))
        self.assertEqual(view.bitmap.devicePixelRatio(), 2.0)
        self.assertGreaterEqual(view.bitmap.width(), view.width()*2-1)
        word = page.get_text('words')[0]
        y = int((word[1]+word[3])/2 * view.scale)
        view.anchor = QPoint(int(word[0]*view.scale), y)
        view.endpoint = QPoint(int(word[2]*view.scale), y)
        self.assertEqual(view.selected()[0], 'Retina')
        view.close(); doc.close()
        self.window.show(); self.app.processEvents()
        reader = self.window.view
        old_scale = reader.scale
        centre = reader.viewport().rect().center()
        event = QNativeGestureEvent(Qt.NativeGestureType.ZoomNativeGesture,
            QPointingDevice.primaryPointingDevice(), 2, QPointF(centre), QPointF(centre),
            QPointF(reader.viewport().mapToGlobal(centre)), .2, QPointF())
        self.assertTrue(reader.eventFilter(reader.viewport(), event))
        reader.zoom_timer.stop(); reader.apply_pending_zoom()
        self.assertAlmostEqual(reader.scale, old_scale*1.2)
        self.assertGreater(reader.verticalScrollBar().value(), 0)

    def test_live_zoom_reuses_pages_and_bitmap_until_settled(self):
        from PySide6.QtTest import QTest
        self.window.show()
        for _ in range(10): self.app.processEvents()
        reader = self.window.view; page = reader.pages[0]
        self.assertIsNotNone(page.bitmap)
        bitmap_key = page.bitmap.cacheKey()
        old_render_scale = page.render_scale
        reader.zoom(1.1)
        reader.zoom(1.05)
        self.assertIs(reader.pages[0], page)
        self.assertEqual(page.bitmap.cacheKey(), bitmap_key)
        self.assertEqual(page.render_scale, old_render_scale)
        QTest.qWait(250)
        for _ in range(10): self.app.processEvents()
        self.assertEqual(page.render_scale, reader.scale)
        self.assertNotEqual(page.bitmap.cacheKey(), bitmap_key)

    def test_remove_highlight_and_comment_independently(self):
        p = self.window.paper
        rect = [[72, 60, 120, 80]]
        p['marks'] = [dict(id='first', page=0, text='text', rects=rect, comment='note', highlight=True),
                      dict(id='other', page=0, text='other', rects=[[200, 60, 240, 80]], comment='', highlight=True)]
        self.window.selection_action('取消高亮', '', rect, page=0)
        self.assertFalse(p['marks'][0]['highlight'])
        self.assertEqual(p['marks'][0]['comment'], 'note')
        self.window.selection_action('删除批注', '', rect, page=0)
        self.assertEqual([m['id'] for m in p['marks']], ['other'])
        self.assertEqual(len(self.library.all()[0]['marks']), 1)

    def test_double_click_word_blank_and_rotated_page(self):
        from PySide6.QtTest import QTest
        from PySide6.QtCore import QPoint, Qt
        from paperreader.ui.pdf import PageView
        doc = fitz.open(); page = doc.new_page()
        page.insert_text((72, 72), 'Alpha Beta Gamma')
        for rotation in (0, 90):
            page.set_rotation(rotation)
            view = PageView(); view.scale = .75; view.display(page, []); view.show()
            self.app.processEvents()
            rect = fitz.Rect(view.words[1][:4]) * page.rotation_matrix
            centre = (rect.tl + rect.br)/2
            point = QPoint(round(centre.x*view.scale), round(centre.y*view.scale))
            QTest.mouseDClick(view, Qt.MouseButton.LeftButton, pos=point)
            QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=point)
            self.assertEqual(view.selected()[0], 'Beta')
            self.assertEqual(view.selected()[1], [list(view.words[1][:4])])
            QTest.mouseDClick(view, Qt.MouseButton.LeftButton, pos=QPoint(10,10))
            self.assertEqual(view.selected(), ('', []))
            view.close()
        doc.close()

    def test_dark_workspace_structure_and_quote_visibility(self):
        from PySide6.QtGui import QPalette
        from PySide6.QtWidgets import QLabel
        self.window.show(); self.app.processEvents()
        self.assertEqual(self.app.palette().color(QPalette.ColorRole.Window).name(), '#0b1019')
        self.assertEqual(self.window.splitter.count(), 4)
        titles = [label.text() for label in self.window.findChildren(QLabel)]
        for title in ('原文预览', '学习工作台', '论文追问'):
            self.assertIn(title, titles)
        self.assertTrue(self.window.quote_box.isHidden())
        self.window.selection_action('针对所选内容提问', 'Paper text', [[72,60,120,80]], page=0)
        self.assertFalse(self.window.quote_box.isHidden())
        self.window.clear_quote()
        self.assertTrue(self.window.quote_box.isHidden())
        self.window.fit_width()
        self.assertAlmostEqual(self.window.view.scale,
            max(.5, min(4, (self.window.view.viewport().width()-28)/self.window.doc[0].rect.width)))
