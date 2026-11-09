import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
import tempfile
import time
import unittest
from unittest.mock import patch
import fitz
from PySide6.QtWidgets import QApplication, QPushButton
from paperreader.services.library import Library
from paperreader.ui.paper_list import PAPER_ID_ROLE, GROUP_ID_ROLE, PAPER_MIME, GROUP_MIME
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
    def model(config, key, messages, on_chunk=None, *, cancel=None):
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

    def test_library_search_and_group_rows(self):
        doc = fitz.open(); doc.new_page().insert_text((72, 72), 'Second paper')
        other = self.library.import_pdf(doc.tobytes(), 'Other study', 'https://arxiv.org/abs/1234.5678')
        doc.close()
        other['title'] = 'Other study'
        self.library.save(other)
        self.window.reload(self.paper['id'])
        self.assertEqual(self.window.list.count(), 2)

        self.window.paper_search.setText('other')
        self.assertEqual(self.window.list.count(), 2)
        self.window.paper_search.returnPressed.emit()
        self.assertEqual(self.window.list.count(), 1)
        self.assertEqual(self.window.papers[0]['id'], other['id'])
        self.window.paper_search.clear()
        self.assertEqual(self.window.list.count(), 2)

        group_id = self.library.create_group('重点论文')
        self.window.move_paper_to_group(other, group_id)
        self.assertEqual(self.window.list.count(), 4)
        self.assertEqual(self.window.list.item(0).data(GROUP_ID_ROLE), group_id)
        self.assertEqual(self.window.list.item(1).data(PAPER_ID_ROLE), other['id'])
        self.assertEqual(self.window.list.item(2).data(GROUP_ID_ROLE), -1)
        self.assertEqual(self.window.list.item(3).data(PAPER_ID_ROLE), self.paper['id'])
        self.window.open_paper(0)
        self.assertEqual(self.window.paper['id'], self.paper['id'])
        self.window.open_paper(1)
        self.assertEqual(self.window.paper['id'], other['id'])
        self.window.show(); self.app.processEvents()
        add_group = self.window.findChild(QPushButton, 'AddPaperGroup')
        self.assertEqual(self.window.paper_search.height(), add_group.height())
        self.assertEqual(self.window.paper_search.geometry().top(), add_group.geometry().top())
        self.assertFalse(self.errors)

    def test_delete_group_dialog_moves_papers_to_ungrouped(self):
        from PySide6.QtCore import QTimer
        group_id = self.library.create_group('待整理')
        self.library.set_group(self.paper['id'], group_id)
        self.window.reload(self.paper['id'], reopen=False)

        def choose_keep():
            dialog = self.app.activeModalWidget()
            next(button for button in dialog.buttons() if button.text() == '仅删除分组').click()

        QTimer.singleShot(0, choose_keep)
        self.window.delete_paper_group(self.library.list_groups()[0])
        self.assertEqual(self.library.list_groups(), [])
        self.assertIsNone(self.library.list_metadata()[0]['group_id'])
        self.assertTrue(self.library.pdf_path(self.paper).exists())
        self.assertEqual(self.window.paper['id'], self.paper['id'])
        self.assertFalse(self.errors)

    def test_click_group_header_collapses_and_expands_without_closing_paper(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        group_id = self.library.create_group('阅读计划')
        self.library.set_group(self.paper['id'], group_id)
        self.window.reload(self.paper['id'], reopen=False)
        self.window.show(); self.app.processEvents()
        self.assertEqual(self.window.list.count(), 3)

        def click_group():
            header = self.window.list.item(0)
            center = self.window.list.visualItemRect(header).center()
            QTest.mouseClick(self.window.list.viewport(), Qt.MouseButton.LeftButton, pos=center)
            self.app.processEvents()

        click_group()
        self.assertEqual(self.window.list.count(), 2)
        self.assertTrue(self.window.list.item(0).text().startswith('▸'))
        self.assertEqual(self.window.paper['id'], self.paper['id'])
        self.window.reload(self.paper['id'], reopen=False)
        self.assertEqual(self.window.list.count(), 2)
        self.window.paper_search.setText(self.window.paper['title'])
        self.window.paper_search.returnPressed.emit()
        self.assertEqual(self.window.list.count(), 2)
        self.window.paper_search.clear()
        self.assertEqual(self.window.list.count(), 2)
        click_group()
        self.assertEqual(self.window.list.count(), 3)
        self.assertTrue(self.window.list.item(0).text().startswith('▾'))
        self.assertEqual(self.window.paper['id'], self.paper['id'])

    def test_fixed_work_rail_controls_and_library_restore(self):
        from PySide6.QtWidgets import QLabel
        self.window.show(); self.app.processEvents()
        self.assertEqual(self.window.windowTitle(), 'PaperReader · 读起来不烧心')
        self.assertEqual(self.window.work_rail.width(), 48)
        controls = (self.window.library_rail_button, self.window.import_pdf_button,
                    self.window.import_link_button)
        self.assertEqual([control.size().width() for control in controls], [38, 38, 38])
        centers = [control.geometry().center() for control in controls]
        self.assertEqual([point.x() for point in centers], [centers[0].x()] * 3)
        self.assertEqual(centers[1].y() - centers[0].y(), centers[2].y() - centers[1].y())
        self.assertGreater(self.window.splitter.sizes()[0], 0)
        self.assertTrue(self.window.library_rail_button.property('active'))
        self.assertIsNone(self.window.findChild(QLabel, 'LibraryRailHint'))
        self.assertIsNotNone(self.window.findChild(QLabel, 'BrandLabel'))
        self.assertIsNone(self.window.findChild(QPushButton, 'Brand'))
        self.assertIsNone(self.window.findChild(QLabel, 'BrandSlogan'))
        self.assertEqual(self.window.reader_paper_title.full_text, self.paper['title'])
        self.assertNotIn(self.paper['title'], [label.text() for label in self.window.top_bar.findChildren(QLabel)])
        long_title = 'An unusually long paper title ' * 12
        self.window.set_reader_title(long_title)
        self.app.processEvents()
        self.assertEqual(self.window.reader_paper_title.toolTip(), long_title)
        self.assertTrue(self.window.reader_paper_title.text().endswith('…'))

        with patch('paperreader.ui.window.QFileDialog.getOpenFileNames', return_value=([], '')) as choose_pdf:
            self.window.import_pdf_button.click()
            choose_pdf.assert_called_once()
        with patch('paperreader.ui.window.QInputDialog.exec', return_value=0) as choose_link:
            self.window.import_link_button.click()
            choose_link.assert_called_once()
        with patch('paperreader.ui.window.SettingsDialog.exec', return_value=0) as settings:
            self.window.settings_rail_button.click()
            settings.assert_called_once()

        expanded_sizes = self.window.splitter.sizes()
        self.window.library_rail_button.click(); self.app.processEvents()
        collapsed_sizes = self.window.splitter.sizes()
        self.assertEqual(self.window.splitter.sizes()[0], 0)
        self.assertTrue(self.window.work_rail.isVisible())
        self.assertFalse(self.window.library_rail_button.property('active'))
        self.window.library_rail_button.click(); self.app.processEvents()
        self.assertEqual(self.window.splitter.sizes(), expanded_sizes)
        self.assertTrue(self.window.library_rail_button.property('active'))
        self.window.library_rail_button.click(); self.app.processEvents()
        self.assertEqual(self.window.splitter.sizes(), collapsed_sizes)
        self.assertFalse(self.errors)

    def test_drag_papers_onto_group_and_back_to_ungrouped(self):
        from PySide6.QtCore import QMimeData, QPointF, Qt
        from PySide6.QtGui import QDragLeaveEvent, QDragMoveEvent, QDropEvent
        doc = fitz.open(); doc.new_page().insert_text((72, 72), 'Another paper')
        other = self.library.import_pdf(doc.tobytes(), 'Another paper'); doc.close()
        group_id = self.library.create_group('研究分组')
        self.window.reload(self.paper['id'], reopen=False)
        self.window.show(); self.app.processEvents()

        dragged = []
        class FakeDrag:
            def __init__(self, _source): pass
            def setMimeData(self, mime): self.mime = mime
            def setPixmap(self, pixmap): self.pixmap = pixmap
            def setHotSpot(self, point): self.hotspot = point
            def exec(self, action):
                dragged.append((bytes(self.mime.data(PAPER_MIME)), action, self.pixmap, self.hotspot))

        self.window.list.setCurrentRow(self.window.row_for_paper(self.paper['id']))
        with patch('paperreader.ui.paper_list.QDrag', FakeDrag):
            self.window.list.startDrag(Qt.DropAction.MoveAction)
        self.assertEqual(dragged[0][:2], (json.dumps([self.paper['id']]).encode('ascii'), Qt.DropAction.MoveAction))
        preview, hotspot = dragged[0][2:]
        self.assertFalse(preview.isNull())
        self.assertGreater(preview.width(), 0)
        self.assertGreater(preview.height(), 0)
        self.assertGreaterEqual(hotspot.x(), 0)
        self.assertGreaterEqual(hotspot.y(), 0)

        mime = QMimeData(); mime.setData(PAPER_MIME, json.dumps([self.paper['id']]).encode('ascii'))
        target = self.window.list.visualItemRect(self.window.list.item(0)).center()
        move = QDragMoveEvent(target, Qt.DropAction.MoveAction, mime,
                              Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.window.list.dragMoveEvent(move)
        self.assertTrue(move.isAccepted())
        self.assertEqual(self.window.list.drop_target_row, 0)
        self.window.list.dragLeaveEvent(QDragLeaveEvent())
        self.assertEqual(self.window.list.drop_target_row, -1)

        def drop(identifier, target_row):
            mime = QMimeData(); mime.setData(PAPER_MIME, json.dumps([identifier]).encode('ascii'))
            point = self.window.list.visualItemRect(self.window.list.item(target_row)).center()
            event = QDropEvent(QPointF(point), Qt.DropAction.MoveAction, mime,
                               Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            self.window.list.dropEvent(event)
            self.assertTrue(event.isAccepted())

        drop(self.paper['id'], 0)
        self.assertEqual(next(p for p in self.library.list_metadata() if p['id'] == self.paper['id'])['group_id'], group_id)
        self.assertEqual(self.window.list.item(1).data(PAPER_ID_ROLE), self.paper['id'])
        # Dropping on a paper also targets its containing group.
        drop(other['id'], 1)
        self.assertEqual(next(p for p in self.library.list_metadata() if p['id'] == other['id'])['group_id'], group_id)
        # The empty default group remains a drop target.
        default_row = next(i for i in range(self.window.list.count())
                           if self.window.list.item(i).data(GROUP_ID_ROLE) == -1)
        drop(self.paper['id'], default_row)
        self.assertIsNone(next(p for p in self.library.list_metadata() if p['id'] == self.paper['id'])['group_id'])
        self.window.collapsed_groups.add(group_id)
        self.window.reload(self.paper['id'], reopen=False)
        self.assertEqual(self.window.list.count(), 3)
        drop(self.paper['id'], 0)
        self.assertNotIn(group_id, self.window.collapsed_groups)
        self.assertGreaterEqual(self.window.row_for_paper(self.paper['id']), 0)
        self.assertFalse(self.errors)

    def test_drag_group_header_reorders_without_collapsing(self):
        from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt
        from PySide6.QtGui import QDragMoveEvent, QDropEvent, QMouseEvent
        from PySide6.QtTest import QTest
        ids = [self.library.create_group(name) for name in ('第一组', '第二组', '第三组')]
        self.window.reload(self.paper['id'], reopen=False)
        self.window.show(); self.app.processEvents()
        header = self.window.list.item(0)
        start = self.window.list.visualItemRect(header).center()
        dragged = []

        class FakeDrag:
            def __init__(self, _source): pass
            def setMimeData(self, mime): self.mime = mime
            def setPixmap(self, pixmap): self.pixmap = pixmap
            def setHotSpot(self, point): self.hotspot = point
            def exec(self, _action): dragged.append((bytes(self.mime.data(GROUP_MIME)), self.pixmap))

        with patch('paperreader.ui.paper_list.QDrag', FakeDrag):
            QTest.mousePress(self.window.list.viewport(), Qt.MouseButton.LeftButton, pos=start)
            moved = start + QPoint(0, self.app.startDragDistance() + 5)
            event = QMouseEvent(QEvent.Type.MouseMove, QPointF(moved),
                                QPointF(self.window.list.viewport().mapToGlobal(moved)),
                                Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                                Qt.KeyboardModifier.NoModifier)
            self.window.list.mouseMoveEvent(event)
            QTest.mouseRelease(self.window.list.viewport(), Qt.MouseButton.LeftButton, pos=moved)
        self.assertEqual(dragged[0][0], str(ids[0]).encode('ascii'))
        self.assertFalse(dragged[0][1].isNull())
        self.assertFalse(self.window.collapsed_groups)

        mime = QMimeData(); mime.setData(GROUP_MIME, str(ids[0]).encode('ascii'))
        target_rect = self.window.list.visualItemRect(self.window.list.item(1))
        target = QPoint(target_rect.center().x(), target_rect.bottom() - 2)
        move = QDragMoveEvent(target, Qt.DropAction.MoveAction, mime,
                              Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.window.list.dragMoveEvent(move)
        self.assertTrue(move.isAccepted())
        self.assertEqual(self.window.list.drop_target_kind, 'group')
        self.assertTrue(self.window.list.drop_after)
        drop = QDropEvent(QPointF(target), Qt.DropAction.MoveAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.window.list.dropEvent(drop)
        self.assertTrue(drop.isAccepted())
        self.assertEqual([group['id'] for group in self.library.list_groups()], [ids[1], ids[0], ids[2]])
        self.assertEqual(self.window.list.item(0).data(GROUP_ID_ROLE), ids[1])
        self.assertFalse(self.errors)

    def test_ctrl_and_shift_select_multiple_papers_for_one_drag(self):
        from PySide6.QtCore import QMimeData, QPointF, Qt
        from PySide6.QtGui import QDropEvent
        from PySide6.QtTest import QTest
        papers = [self.paper]
        for title in ('Second paper', 'Third paper'):
            doc = fitz.open(); doc.new_page().insert_text((72, 72), title)
            papers.append(self.library.import_pdf(doc.tobytes(), title)); doc.close()
        group_id = self.library.create_group('批量整理')
        self.window.reload(self.paper['id'], reopen=False)
        self.window.show(); self.app.processEvents()

        def click(paper, modifier=Qt.KeyboardModifier.NoModifier):
            row = self.window.row_for_paper(paper['id'])
            point = self.window.list.visualItemRect(self.window.list.item(row)).center()
            QTest.mouseClick(self.window.list.viewport(), Qt.MouseButton.LeftButton, modifier, pos=point)
            self.app.processEvents()

        def selected_ids():
            return {item.data(PAPER_ID_ROLE) for item in self.window.list.selectedItems()}

        click(papers[0])
        click(papers[2], Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(selected_ids(), {papers[0]['id'], papers[2]['id']})
        self.assertEqual(self.window.paper['id'], papers[0]['id'])
        with patch('paperreader.ui.paper_list.MACOS', True):
            click(papers[1], Qt.KeyboardModifier.MetaModifier)
            self.assertEqual(selected_ids(), {paper['id'] for paper in papers})
            click(papers[1], Qt.KeyboardModifier.MetaModifier)
            self.assertEqual(selected_ids(), {papers[0]['id'], papers[2]['id']})
        self.assertEqual(self.window.paper['id'], papers[0]['id'])

        click(papers[0])
        click(papers[2], Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(selected_ids(), {paper['id'] for paper in papers})
        self.assertEqual(self.window.paper['id'], papers[0]['id'])

        dragged = []
        class FakeDrag:
            def __init__(self, _source): pass
            def setMimeData(self, mime): self.mime = mime
            def setPixmap(self, pixmap): self.pixmap = pixmap
            def setHotSpot(self, point): self.hotspot = point
            def exec(self, _action): dragged.append((json.loads(bytes(self.mime.data(PAPER_MIME))), self.pixmap))

        drag_row = self.window.row_for_paper(papers[2]['id'])
        drag_point = self.window.list.visualItemRect(self.window.list.item(drag_row)).center()
        QTest.mousePress(self.window.list.viewport(), Qt.MouseButton.LeftButton, pos=drag_point)
        self.assertEqual(selected_ids(), {paper['id'] for paper in papers})
        self.assertEqual(self.window.paper['id'], papers[0]['id'])
        with patch('paperreader.ui.paper_list.QDrag', FakeDrag):
            self.window.list.startDrag(Qt.DropAction.MoveAction)
        QTest.mouseRelease(self.window.list.viewport(), Qt.MouseButton.LeftButton, pos=drag_point)
        self.assertEqual(set(dragged[0][0]), {paper['id'] for paper in papers})
        self.assertFalse(dragged[0][1].isNull())

        mime = QMimeData()
        mime.setData(PAPER_MIME, json.dumps([paper['id'] for paper in papers]).encode('ascii'))
        target = self.window.list.visualItemRect(self.window.list.item(0)).center()
        event = QDropEvent(QPointF(target), Qt.DropAction.MoveAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.window.list.dropEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertEqual({paper['group_id'] for paper in self.library.list_metadata()}, {group_id})
        self.assertFalse(self.errors)

    def test_create_group_dialog_has_wider_input(self):
        from PySide6.QtWidgets import QInputDialog

        def check_width(dialog):
            self.assertGreaterEqual(dialog.minimumWidth(), 620)
            return 0

        with patch.object(QInputDialog, 'exec', check_width):
            self.window.create_paper_group()

    def test_delete_group_dialog_can_purge_current_paper(self):
        from PySide6.QtCore import QTimer
        group_id = self.library.create_group('彻底清理')
        self.library.set_group(self.paper['id'], group_id)
        self.window.reload(self.paper['id'], reopen=False)

        def choose_purge():
            dialog = self.app.activeModalWidget()
            next(button for button in dialog.buttons() if button.text() == '删除分组及全部论文').click()

        QTimer.singleShot(0, choose_purge)
        self.window.delete_paper_group(self.library.list_groups()[0])
        self.assertEqual(self.library.list_groups(), [])
        self.assertEqual(self.library.list_metadata(), [])
        self.assertFalse(self.library.pdf_path(self.paper).exists())
        self.assertIsNone(self.window.paper)
        self.assertFalse(self.errors)

    def test_note_preview_reads_latest_text_each_time_it_is_opened(self):
        from PySide6.QtCore import QSignalBlocker
        editor = self.window.notes
        editor.setPlainText("# 第一次修改")
        editor.tabs.setCurrentWidget(editor.preview)
        self.assertEqual(editor.preview.toPlainText(), "第一次修改")
        editor.tabs.setCurrentWidget(editor.source)
        with QSignalBlocker(editor.source):
            editor.setPlainText("## 第二次修改\n\n**最新内容**")
        editor.tabs.setCurrentWidget(editor.preview)
        self.assertEqual(editor.preview.toPlainText(), "第二次修改\n最新内容")
        self.assertIn("<h2", editor.preview.document().toHtml())

    def test_new_answer_is_visible_without_resizing_chat(self):
        from PySide6.QtCore import QEvent, QObject

        class PaintEvents(QObject):
            count = 0

            def eventFilter(self, watched, event):
                if event.type() == QEvent.Type.Paint:
                    self.count += 1
                return False

        self.assertTrue(self.window.change_theme("naruto"))
        chat = self.window.chat
        self.window.paper["messages"] += [
            {"role": "user", "content": "旧问题"},
            {"role": "assistant", "content": "旧回答内容\n\n" * 100},
        ]
        self.window.show()
        self.window.render_chat()
        self.app.processEvents()
        size = chat.size()
        bar = chat.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        bar.setValue(0)
        paints = PaintEvents(chat)
        chat.viewport().installEventFilter(paints)

        self.window.question.setPlainText("新问题")
        with patch('paperreader.ui.window.complete', return_value="新回答已显示"):
            self.window.ask()
            self.wait()

        answer = chat.document().find("新回答已显示")
        self.assertFalse(answer.isNull())
        self.assertEqual(chat.size(), size)
        self.assertEqual(bar.value(), bar.maximum())
        self.assertTrue(chat.viewport().rect().intersects(chat.cursorRect(answer)))
        self.assertGreater(paints.count, 0)
        self.assertFalse(self.window.chat_reflow_timer.isActive())

    def test_streaming_text_waits_for_scrollbar_drag_in_both_panes(self):
        from threading import Event
        from PySide6.QtTest import QTest

        self.window.show()
        first = "第一批流式内容，用于测试长文滚动。\n\n" * 100
        tail = "下一批内容"

        def wait_for_text(browser, text):
            deadline = time.monotonic() + 2
            while text not in browser.toPlainText() and time.monotonic() < deadline:
                QTest.qWait(10)
            self.assertIn(text, browser.toPlainText())

        for name, browser, start in (
            ("analysis", self.window.summary, self.window.analyze),
            ("chat", self.window.chat, self.window.ask),
        ):
            with self.subTest(pane=name):
                send_tail, finish = Event(), Event()

                def model(config, key, messages, on_chunk=None, *, cancel=None):
                    on_chunk(first)
                    send_tail.wait(3)
                    for chunk in tail:
                        on_chunk(chunk)
                    finish.wait(3)
                    return first + tail

                with patch('paperreader.ui.window.complete', side_effect=model):
                    self.window.question.setPlainText("测试滚动")
                    start()
                    bar = browser.verticalScrollBar()
                    try:
                        wait_for_text(browser, "第一批流式内容")
                        self.assertGreater(bar.maximum(), 20)
                        bar.setSliderDown(True)
                        bar.setValue(bar.maximum() // 2)
                        position = bar.value()
                        send_tail.set()
                        QTest.qWait(350)
                        self.assertTrue(self.window.busy)
                        self.assertNotIn(tail, browser.toPlainText())
                        self.assertEqual(bar.value(), position)
                        bar.setSliderDown(False)
                        wait_for_text(browser, tail)
                        self.assertEqual(bar.value(), position)
                    finally:
                        bar.setSliderDown(False)
                        send_tail.set()
                        finish.set()
                        self.wait()

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
        self.assertTrue(self.window.chat_status.toggle.isChecked())
        self.assertFalse(self.window.chat_status.timer.isActive())

    def test_submitted_question_clears_immediately_and_status_collapses(self):
        import threading
        release = threading.Event()
        def delayed(config, key, messages, on_chunk=None):
            release.wait(3)
            on_chunk('Answer')
            return 'Answer'
        try:
            with patch('paperreader.ui.window.complete', side_effect=delayed):
                self.window.question.setPlainText('First question')
                self.window.ask()
                self.assertEqual(self.window.question.toPlainText(), '')
                status = self.window.chat_status
                self.assertTrue(status.toggle.isChecked())
                self.assertTrue(status.timer.isActive())
                self.assertIn('等待模型响应', status.toggle.text())
                self.assertIn('正在调用模型，等待首段内容', self.window.chat.toPlainText())
                self.assertNotIn('添加到笔记', self.window.chat.toPlainText())
                self.assertTrue(status.isHidden())
                self.window.question.setPlainText('Next question draft')
                release.set(); self.wait()
                self.assertEqual(self.window.question.toPlainText(), 'Next question draft')
                self.assertFalse(status.toggle.isChecked())
                self.assertFalse(status.timer.isActive())
                self.assertIn('已完成', status.toggle.text())
                rendered = self.window.chat.toPlainText()
                self.assertLess(rendered.index('First question'), rendered.index('已完成'))
                self.assertLess(rendered.index('已完成'), rendered.index('Answer'))
                self.assertNotIn('正在调用模型，等待首段内容', rendered)
                self.assertIn('已收到模型内容', status.log.toPlainText())
                from PySide6.QtCore import QUrl
                self.window.chat.anchorClicked.emit(QUrl('paperreader-status:toggle?message=0'))
                self.assertTrue(status.toggle.isChecked())
                self.assertIn('正在调用模型，等待首段内容', self.window.chat.toPlainText())
                self.window.ask(); self.wait()
                rendered = self.window.chat.toPlainText()
                self.assertEqual(rendered.count('已完成'), 2)
                self.assertLess(rendered.index('Next question draft'), rendered.rindex('已完成'))
                self.window.chat.anchorClicked.emit(QUrl('paperreader-status:toggle?message=0'))
                self.assertNotIn('正在调用模型，等待首段内容', self.window.chat.toPlainText())
        finally: release.set()

    def test_request_status_isolated_while_switching_papers_and_sessions(self):
        import threading
        release = threading.Event()
        def delayed(config, key, messages, on_chunk=None):
            release.wait(3)
            on_chunk('Only first paper answer')
            return 'Only first paper answer'
        doc = fitz.open(); doc.new_page().insert_text((72, 72), 'Different paper')
        other = self.library.import_pdf(doc.tobytes(), 'Other'); doc.close()
        first_id = self.window.paper['id']
        first_session = self.window.paper['active_session']
        try:
            with patch('paperreader.ui.window.complete', side_effect=delayed):
                self.window.question.setPlainText('First paper question')
                self.window.ask()
                self.assertIn('等待模型响应', self.window.chat.toPlainText())
                self.window.reload(other['id'])
                self.assertEqual(self.window.chat._status_html, '')
                self.window.chat_status.tick()
                self.assertEqual(self.window.chat._status_html, '')
                release.set(); self.wait()
                self.assertEqual(self.window.chat._status_html, '')
                self.assertNotIn('Only first paper answer', self.window.chat.toPlainText())
                self.window.reload(first_id)
                self.assertIn('已完成', self.window.chat.toPlainText())
                self.assertIn('Only first paper answer', self.window.chat.toPlainText())
                self.window.new_session()
                self.assertEqual(self.window.chat._status_html, '')
                self.window.switch_session(first_session)
                self.assertIn('已完成', self.window.chat.toPlainText())
        finally: release.set()

    def test_analysis_status_isolated_by_paper_and_mode(self):
        with patch('paperreader.ui.window.complete', side_effect=self.model):
            self.window.analyze(); self.wait()
        self.assertIn('已完成', self.window.summary.toPlainText())
        self.window.analysis_mode.setCurrentIndex(1)
        self.assertEqual(self.window.summary._status_html, '')
        self.window.analysis_mode.setCurrentIndex(0)
        self.assertIn('已完成', self.window.summary.toPlainText())
        doc = fitz.open(); doc.new_page().insert_text((72, 72), 'Another analysis paper')
        other = self.library.import_pdf(doc.tobytes(), 'Other'); doc.close()
        first_id = self.window.paper['id']
        self.window.reload(other['id'])
        self.assertEqual(self.window.summary._status_html, '')
        self.window.reload(first_id)
        self.assertIn('已完成', self.window.summary.toPlainText())

    def test_read_button_restarts_and_continue_preserves_partial(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QTextCursor
        from PySide6.QtTest import QTest
        from paperreader.services.analysis import AnalysisStopped

        window = self.window
        requests = []
        def model(config, key, messages, on_chunk=None, *, cancel=None):
            requests.append(messages)
            if len(requests) <= 2:
                on_chunk(f"第{len(requests)}次的部分内容。")
                if cancel.wait(2):
                    raise AnalysisStopped()
            on_chunk("续读完成。")
            return "续读完成。"

        with patch('paperreader.ui.window.complete', side_effect=model):
            for index in (1, 2):
                self.assertEqual(window.read_button.text(), "阅读")
                window.read_button.click()
                self.assertEqual(window.read_button.text(), "停止")
                deadline = time.monotonic() + 1.5
                while f"第{index}次的部分内容" not in window.summary.toPlainText() and time.monotonic() < deadline:
                    QTest.qWait(10)
                self.assertIn(f"第{index}次的部分内容", window.summary.toPlainText())
                window.read_button.click()
                self.wait()
                self.assertIn("继续阅读", window.summary.toPlainText())
                self.assertTrue(self.library.get(window.paper['id'])['analyses']['quick']['stopped'])
            self.assertEqual(len(requests[1]), 2)  # Top button restarted with no partial answer.
            window.reload(window.paper["id"])
            link = window.summary.document().find("继续阅读")
            self.assertFalse(link.isNull())
            link.setPosition(link.selectionStart())
            link.movePosition(QTextCursor.MoveOperation.NextCharacter)
            href = link.charFormat().anchorHref()
            self.assertEqual(href, "paperreader-analysis:continue")
            window.summary.anchorClicked.emit(QUrl(href))
            self.wait()
        self.assertEqual(requests[2][-2]["content"], "第2次的部分内容。")
        self.assertIn("第2次的部分内容。续读完成。", window.summary.toPlainText())
        self.assertNotIn("继续阅读", window.summary.toPlainText())
        self.assertEqual(self.errors, [])

    def test_title_double_click_opens_and_context_menu_renames_in_wide_dialog(self):
        from PySide6.QtWidgets import QInputDialog, QMenu
        item = self.window.list.currentItem()
        with patch('paperreader.ui.window.QInputDialog.getText') as old_dialog:
            self.window.list.itemDoubleClicked.emit(item)
            old_dialog.assert_not_called()
        self.assertEqual(self.window.paper['id'], self.paper['id'])
        self.window.notes.setPlainText('Keep notes'); self.window.save_notes()
        renamed = 'A longer renamed paper title'
        def edit(dialog):
            self.assertGreaterEqual(dialog.minimumWidth(), 760)
            self.assertEqual(dialog.textValue(), self.window.paper['title'])
            dialog.setTextValue(renamed)
            return 1
        from unittest.mock import MagicMock
        from PySide6.QtGui import QAction
        menu = MagicMock()
        rename = QAction('修改论文标题…', self.window)
        remove = QAction('移除论文…', self.window)
        menu.addAction.side_effect = [
            QAction('收藏论文', self.window), rename, QAction('导出学习内容', self.window),
            QAction('清除学习内容', self.window), remove,
        ]
        menu.exec.side_effect = lambda position: rename.trigger()
        self.window.show(); self.app.processEvents()
        with patch.object(QInputDialog, 'exec', edit), patch('paperreader.ui.window.QMenu', return_value=menu):
            self.window.paper_context_menu(self.window.list.visualItemRect(item).center())
        self.assertEqual(item.text(), renamed)
        saved = self.library.get(self.paper['id'])
        self.assertEqual(saved['title'], renamed)
        self.assertEqual(saved['notes'], 'Keep notes')

    def test_favorite_reorders_library_without_reopening_paper(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QToolButton

        doc = fitz.open()
        doc.new_page().insert_text((72, 72), 'Another paper')
        newer = self.library.import_pdf(doc.tobytes(), 'Newer paper')
        doc.close()
        identifier = self.paper['id']
        paper = self.library.get(identifier)
        paper['title'] = 'A long paper title that must not push the favorite button out of view ' * 5
        self.library.save(paper)
        self.window.show()
        self.window.reload(newer['id'])
        self.app.processEvents()
        self.assertEqual(self.window.papers[0]['id'], newer['id'])
        original_doc = self.window.doc
        view = self.window.list

        def click_star(row):
            self.app.processEvents()
            button = view.itemWidget(view.item(row)).findChild(QToolButton, "PaperFavoriteButton")
            self.assertTrue(button.isVisible())
            self.assertTrue(view.viewport().rect().contains(button.mapTo(view.viewport(), button.rect().topLeft())))
            self.assertTrue(view.viewport().rect().contains(button.mapTo(view.viewport(), button.rect().bottomRight())))
            position = button.mapTo(view.viewport(), button.rect().center())
            self.assertIs(view.viewport().childAt(position), button)
            QTest.mouseClick(self.window.windowHandle(), Qt.MouseButton.LeftButton,
                             pos=button.mapTo(self.window, button.rect().center()))

        click_star(1)
        self.assertIs(self.window.doc, original_doc)
        self.assertEqual(view.currentRow(), 1)
        self.assertEqual(self.window.papers[0]['id'], identifier)
        self.assertTrue(self.window.papers[0]['favorite'])
        reopened = Library(self.library.root)
        try:
            self.assertTrue(reopened.list_metadata()[0]['favorite'])
        finally:
            reopened.db.close()
        for theme in ('naruto', 'cat'):
            self.assertTrue(self.window.change_theme(theme))
            self.app.processEvents()
            click_star(0)
            self.assertEqual(self.window.papers[0]['id'], newer['id'])
            self.assertFalse(self.window.papers[1]['favorite'])
            click_star(1)
            self.assertEqual(self.window.papers[0]['id'], identifier)
            self.assertIs(self.window.doc, original_doc)


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

    def test_splitter_click_collapse_restore_and_immediate_drag(self):
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt, QPoint
        self.window.show(); self.app.processEvents()
        splitter = self.window.splitter
        handle = splitter.handle(1)
        QTest.mouseClick(handle, Qt.MouseButton.LeftButton)
        self.assertEqual(splitter.sizes()[0], 0)
        self.assertFalse(self.window.library_rail_button.property('active'))
        QTest.mouseClick(handle, Qt.MouseButton.LeftButton)
        self.assertGreater(splitter.sizes()[0], 0)
        self.assertTrue(self.window.library_rail_button.property('active'))
        before = splitter.sizes()[0]
        QTest.mousePress(handle, Qt.MouseButton.LeftButton)
        QTest.qWait(handle.HOLD_MS + 150)
        self.assertTrue(handle.dragging)
        QTest.mouseRelease(handle, Qt.MouseButton.LeftButton)
        self.assertEqual(splitter.sizes()[0], before)
        QTest.mousePress(handle, Qt.MouseButton.LeftButton)
        self.assertFalse(handle.dragging)
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
        self.assertAlmostEqual(reader.scale, old_scale*1.2**1.5)
        self.assertGreater(reader.verticalScrollBar().value(), 0)

    def test_native_pinch_follows_each_delta_and_ignores_duplicate_qt_pinch(self):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QNativeGestureEvent, QPointingDevice, QWheelEvent
        from PySide6.QtWidgets import QGestureEvent, QPinchGesture
        self.window.show(); self.app.processEvents()
        reader = self.window.view
        page = reader.pages[0]
        original_bitmap = page.bitmap.cacheKey()
        original_scale = reader.scale
        centre = reader.viewport().rect().center()
        def native(kind, value=0):
            return QNativeGestureEvent(kind, QPointingDevice.primaryPointingDevice(), 2,
                QPointF(centre), QPointF(centre),
                QPointF(reader.viewport().mapToGlobal(centre)), value, QPointF())
        reader.eventFilter(reader.viewport(), native(Qt.NativeGestureType.BeginNativeGesture))
        reader.eventFilter(reader.viewport(), native(Qt.NativeGestureType.ZoomNativeGesture, .04))
        self.assertAlmostEqual(reader.scale, original_scale*1.04**1.5)
        reader.eventFilter(reader.viewport(), native(Qt.NativeGestureType.ZoomNativeGesture, .06))
        self.assertAlmostEqual(reader.scale, original_scale*1.04**1.5*1.06**1.5)
        self.assertTrue(page.fast_preview)
        self.assertEqual(page.bitmap.cacheKey(), original_bitmap)
        pinch = QPinchGesture(); pinch.setScaleFactor(1.3); pinch.setLastScaleFactor(1.0)
        self.assertTrue(reader.eventFilter(reader.viewport(), QGestureEvent([pinch])))
        wheel = QWheelEvent(QPointF(centre), QPointF(reader.viewport().mapToGlobal(centre)),
            QPoint(0, 120), QPoint(0, 120), Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.ControlModifier, Qt.ScrollPhase.ScrollUpdate, False)
        self.assertTrue(reader.eventFilter(reader.viewport(), wheel))
        self.assertAlmostEqual(reader.scale, original_scale*1.04**1.5*1.06**1.5)
        reader.eventFilter(reader.viewport(), native(Qt.NativeGestureType.EndNativeGesture))
        self.assertTrue(reader.settle_timer.isActive())
        self.assertEqual(reader.settle_timer.interval(), 90)

    def test_pinch_or_ctrl_wheel_alone_still_zooms_on_macos(self):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QNativeGestureEvent, QPointingDevice, QWheelEvent
        from PySide6.QtWidgets import QGestureEvent, QPinchGesture
        self.window.show(); self.app.processEvents()
        reader = self.window.view
        initial = reader.scale
        centre = reader.viewport().rect().center()
        pinch = QPinchGesture(); pinch.setLastScaleFactor(1.0); pinch.setScaleFactor(1.1)
        self.assertTrue(reader.eventFilter(reader.viewport(), QGestureEvent([pinch])))
        self.assertAlmostEqual(reader.scale, initial*1.1**1.5)
        reader.finish_zoom_preview()
        begin = QNativeGestureEvent(Qt.NativeGestureType.BeginNativeGesture,
            QPointingDevice.primaryPointingDevice(), 3, QPointF(centre), QPointF(centre),
            QPointF(reader.viewport().mapToGlobal(centre)), 0, QPointF())
        reader.eventFilter(reader.viewport(), begin)
        wheel = QWheelEvent(QPointF(centre), QPointF(reader.viewport().mapToGlobal(centre)),
            QPoint(0, 120), QPoint(0, 120), Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.ControlModifier, Qt.ScrollPhase.ScrollUpdate, False)
        self.assertTrue(reader.eventFilter(reader.viewport(), wheel))
        self.assertGreater(reader.scale, initial*1.1**1.5)

    def test_mouse_wheel_scrolls_and_ctrl_wheel_zooms(self):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        self.window.show(); self.app.processEvents()
        reader = self.window.view
        reader.resize(450, 300); self.app.processEvents()
        centre = reader.viewport().rect().center()
        global_centre = QPointF(reader.viewport().mapToGlobal(centre))
        original_scale = reader.scale
        scroll = reader.verticalScrollBar()
        self.assertGreater(scroll.maximum(), 0)
        scroll.setValue(0)
        plain = QWheelEvent(QPointF(centre), global_centre, QPoint(), QPoint(0, -120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate, False)
        QApplication.sendEvent(reader.viewport(), plain)
        self.assertGreater(scroll.value(), 0)
        self.assertEqual(reader.scale, original_scale)
        zoom = QWheelEvent(QPointF(centre), global_centre, QPoint(), QPoint(0, 120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier,
            Qt.ScrollPhase.ScrollUpdate, False)
        QApplication.sendEvent(reader.viewport(), zoom)
        self.assertAlmostEqual(reader.scale, original_scale*2**(120/480))

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
        deadline = time.monotonic() + 6
        while page.render_scale != reader.scale and time.monotonic() < deadline:
            QTest.qWait(25)
            self.app.processEvents()
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

    def test_triple_click_selects_only_clicked_paragraph(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from paperreader.ui.pdf import PageView

        with fitz.open() as doc:
            page = doc.new_page(width=600, height=800)
            page.insert_text((50, 80), "Alpha starts the paragraph.\nSecond line continues.\nThird line finishes.")
            page.insert_text((330, 80), "Right column starts here.\nRight column continues.\nRight column finishes.")
            page.insert_text((50, 180), "Next paragraph remains separate.")
            for rotation in (0, 90):
                page.set_rotation(rotation)
                view = PageView()
                view.scale = .75
                view.display(page, [])
                view.show()
                word = next(word for word in view.words if word[4] == "Alpha")
                rect = fitz.Rect(word[:4]) * page.rotation_matrix
                center = (rect.tl + rect.br) / 2
                point = QPoint(round(center.x * view.scale), round(center.y * view.scale))
                QTest.mouseDClick(view, Qt.MouseButton.LeftButton, pos=point)
                QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=point)
                self.assertEqual(view.selected()[0], "Alpha")
                QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=point)
                text, rects = view.selected()
                self.assertEqual(text, "Alpha starts the paragraph.\nSecond line continues.\nThird line finishes.")
                self.assertTrue(all(rect[0] < 300 for rect in rects))
                QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=point)
                self.assertEqual(view.selected(), ("", []))
                view.close()

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

    def test_analysis_selected_text_followup_context_and_save(self):
        from PySide6.QtGui import QTextCursor, QContextMenuEvent
        from PySide6.QtCore import QPoint
        self.window.summary.set_markdown('## 核心贡献\n\n注意力建立长距离关联。')
        cursor = self.window.summary.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        self.window.summary.setTextCursor(cursor)
        menu = self.window.summary.createStandardContextMenu()
        def execute(position):
            action = next(a for a in menu.actions() if a.text() == '针对所选内容提问')
            self.assertTrue(action.isEnabled()); action.trigger()
        with patch.object(self.window.summary, 'createStandardContextMenu', return_value=menu), patch.object(menu, 'exec', side_effect=execute):
            self.window.summary.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(1,1)))
        self.assertIn('来源：AI 分析', self.window.quote)
        self.assertIn('注意力建立长距离关联', self.window.quote)
        self.assertNotIn('第 1 页', self.window.quote)
        def model(config, key, messages, on_chunk=None):
            self.assertIn('来源：AI 分析', messages[-1]['content'])
            return self.model(config, key, messages, on_chunk)
        self.window.question.setPlainText('为什么？')
        with patch('paperreader.ui.window.complete', side_effect=model):
            self.window.ask(); self.wait()
        self.assertIn('来源：AI 分析', self.library.all()[0]['messages'][0]['content'])
        self.assertEqual(self.window.quote, '')


    def test_inline_quote_close_preserves_question_and_history(self):
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QPushButton
        self.window.show()
        self.window.ask_about_analysis('引用分析段落')
        self.window.question.setPlainText('保留我的问题')
        history = list(self.window.paper['messages'])
        self.assertFalse(self.window.quote_box.isHidden())
        self.assertEqual(self.window.clear_quote_button.width(), 24)
        QTest.mouseClick(self.window.clear_quote_button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.window.quote, '')
        self.assertTrue(self.window.quote_box.isHidden())
        self.assertEqual(self.window.question.toPlainText(), '保留我的问题')
        self.assertEqual(self.window.paper['messages'], history)
        self.assertFalse(any(b.text() == '清除选区引用' for b in self.window.findChildren(QPushButton)))


    def test_question_is_plain_multiline_input(self):
        from PySide6.QtWidgets import QTextEdit, QTabWidget
        self.assertIsInstance(self.window.question, QTextEdit)
        self.assertFalse(self.window.question.acceptRichText())
        self.assertFalse(self.window.question.findChildren(QTabWidget))
        self.window.question.setPlainText('第一行\n第二行')
        self.assertEqual(self.window.question.toPlainText(), '第一行\n第二行')

    def test_model_switch_persistence_and_inset_controls(self):
        from paperreader.services.profiles import new_profile
        self.window.show(); self.app.processEvents()
        second = new_profile(); second.update(name='备用服务', model='second-model')
        self.window.profile_config['profiles'].append(second); self.window.refresh_models()
        self.window.model_selector.setCurrentIndex(1)
        self.assertEqual(self.window.config['model'], 'second-model')
        self.assertEqual(self.library.config()['active_id'], second['id'])
        self.assertIs(self.window.send_button.parent(), self.window.question.footer)
        self.assertIs(self.window.model_selector.parent(), self.window.question.footer)
        self.assertGreaterEqual(self.window.question.footer.y(), 0)

    def test_rail_settings_and_paper_context_export(self):
        from pathlib import Path
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtTest import QTest
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QListWidget, QPushButton
        from unittest.mock import MagicMock
        from paperreader.ui.window import SettingsDialog

        self.window.show()
        with fitz.open() as doc:
            doc.new_page().insert_text((72, 72), "Other paper")
            other = self.library.import_pdf(doc.tobytes(), "Other")
        other["notes"] = "右击论文的笔记"
        self.library.save(other)
        self.window.reload(self.paper["id"])
        self.window.notes.setPlainText("正在阅读的论文笔记")
        path = Path(self.temp.name) / "export.md"
        errors = []

        def check_settings():
            dialog = self.window.findChild(SettingsDialog)
            try:
                self.assertEqual(dialog.windowTitle(), "系统设置")
                navigation = dialog.findChild(QListWidget, "SettingsNavigation")
                self.assertEqual([navigation.item(i).text() for i in range(navigation.count())],
                                 ["常规设置", "模型设置"])
            except Exception as exc:
                errors.append(exc)
            finally:
                dialog.reject()

        self.assertEqual(self.window.top_bar.findChildren(QPushButton), [])
        QTimer.singleShot(0, check_settings)
        QTest.mouseClick(self.window.settings_rail_button, Qt.MouseButton.LeftButton)
        self.assertFalse(errors, str(errors))
        menu = MagicMock()
        actions = {}

        def add_action(icon, text):
            actions[text] = QAction(icon, text, self.window)
            return actions[text]

        menu.addAction.side_effect = add_action
        menu.exec.side_effect = lambda position: actions["导出学习内容"].trigger()
        row = next(i for i, paper in enumerate(self.window.papers) if paper["id"] == other["id"])
        position = self.window.list.visualItemRect(self.window.list.item(row)).center()
        with patch('paperreader.ui.window.QMenu', return_value=menu), patch(
            'paperreader.ui.window.QFileDialog.getSaveFileName', return_value=(str(path), "")
        ):
            self.window.paper_context_menu(position)
        exported = path.read_text(encoding="utf-8")
        self.assertIn("右击论文的笔记", exported)
        self.assertNotIn("正在阅读的论文笔记", exported)
        self.assertEqual(self.window.paper["id"], self.paper["id"])

    def test_pdf_background_switch_persists_and_ignores_theme_when_off(self):
        from PySide6.QtCore import QPoint, QTimer, Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QCheckBox
        from paperreader.services.themes import get_theme
        from paperreader.ui.window import SettingsDialog
        from paperreader.ui.theme import ThemeSwitch

        self.window.show()
        reader = self.window.view
        page = reader.pages[0]

        def await_color(expected):
            deadline = time.monotonic() + 6
            while time.monotonic() < deadline:
                self.app.processEvents()
                if page.bitmap is not None and page.bitmap.toImage().pixelColor(0, 0).name() == expected:
                    return
                QTest.qWait(25)
            self.fail(f"PDF 纸张颜色未更新为 {expected}")

        await_color(get_theme('dark').pdf_paper)
        def turn_off():
            dialog = self.window.findChild(SettingsDialog)
            checkbox = dialog.findChild(QCheckBox, 'PdfFollowTheme')
            self.assertIsInstance(checkbox, ThemeSwitch)
            self.assertTrue(checkbox.isChecked())
            self.assertEqual(checkbox.status_text(), '已开启')
            QTest.mouseClick(checkbox, Qt.MouseButton.LeftButton, pos=QPoint(20, checkbox.height() // 2))
            self.assertFalse(checkbox.isChecked())
            self.assertEqual(checkbox.status_text(), '已关闭')
            dialog.reject()
        QTimer.singleShot(0, turn_off)
        self.window.settings()
        self.assertFalse(self.library.config()['pdf_follow_theme'])
        await_color('#ffffff')
        self.assertTrue(self.window.change_theme('cat'))
        self.assertEqual(page.bitmap.toImage().pixelColor(0, 0).name(), '#ffffff')
        self.assertTrue(self.window.change_pdf_follow_theme(True))
        await_color(get_theme('cat').pdf_paper)
        self.assertTrue(self.library.config()['pdf_follow_theme'])
        self.assertFalse(self.errors)

    def test_read_button_matches_mode_selector_height_in_every_theme(self):
        self.window.show()
        for theme in ('dark', 'cat', 'naruto'):
            self.assertTrue(self.window.change_theme(theme))
            self.app.processEvents()
            self.assertEqual(self.window.analysis_mode.height(), 36)
            self.assertEqual(self.window.read_button.height(), 36)
            self.assertEqual(self.window.analysis_mode.y(), self.window.read_button.y())

    def test_settings_add_and_save_multiple_profiles(self):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QListWidget, QPushButton, QDialogButtonBox
        from paperreader.ui.window import SettingsDialog
        saved_keys = {}
        errors = []
        def edit():
            try:
                dialog = next(d for d in self.window.findChildren(SettingsDialog) if d.isVisible())
                navigation = dialog.findChild(QListWidget, 'SettingsNavigation')
                navigation.setCurrentRow(1)
                next(b for b in dialog.findChildren(QPushButton) if b.text() == '新增配置').click()
                dialog.findChild(QLineEdit, 'ModelEndpoint').setText('https://example.org/v1')
                dialog.findChild(QLineEdit, 'ModelName').setText('new-model')
                dialog.findChild(QLineEdit, 'ModelKey').setText('new-secret')
                dialog.findChild(QLineEdit, 'ProfileName').setText('备用模型')
                navigation.setCurrentRow(0)
                theme = dialog.findChild(QComboBox, 'ThemePicker')
                theme.setCurrentIndex(theme.findData('naruto'))
                navigation.setCurrentRow(1)
                dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
            except Exception as exc:
                errors.append(exc)
                for dialog in self.window.findChildren(SettingsDialog): dialog.reject()
        with patch('paperreader.ui.window.keyring.set_password', side_effect=lambda service, account, secret: saved_keys.update({account: secret})):
            QTimer.singleShot(0, edit); self.window.settings()
        self.assertFalse(errors, str(errors))
        config = self.library.config()
        self.assertEqual(len(config['profiles']), 2)
        self.assertEqual(config['theme'], 'naruto')
        self.assertEqual(self.window.config['model'], 'new-model')
        self.assertEqual(saved_keys[self.window.config['key_account']], 'new-secret')
        self.assertNotIn('new-secret', str(config))

    def test_theme_switch_preserves_document_and_restores_on_restart(self):
        from paperreader.ui.theme import ACCENT, theme_color
        self.window.summary.set_markdown('## 研究问题\n\n保留正文与 #66ddda。')
        original = self.window.summary.toPlainText()
        document = self.window.doc
        self.assertTrue(self.window.sage_card.isHidden())
        self.assertTrue(self.window.change_theme('naruto'))
        self.assertFalse(self.window.sage_card.isHidden())
        self.assertIs(self.window.doc, document)
        self.assertEqual(self.window.summary.toPlainText(), original)
        heading = self.window.summary.document().find('研究问题')
        self.assertEqual(heading.charFormat().foreground().color().name(), theme_color(ACCENT))
        reopened = Window(self.library)
        try:
            self.assertFalse(reopened.sage_card.isHidden())
        finally:
            reopened.close()
        self.assertTrue(self.window.change_theme('dark'))
        self.assertTrue(self.window.sage_card.isHidden())
        heading = self.window.summary.document().find('研究问题')
        self.assertEqual(heading.charFormat().foreground().color().name(), ACCENT)

    def test_followup_uses_current_theme_in_same_conversation(self):
        from threading import Event

        release = Event()

        def model(config, key, messages, on_chunk=None):
            if messages[-1]["content"].endswith("先看什么？"):
                release.wait(3)
                return "嗯……让老夫看看这组对照。"
            return "第二个回答。"

        with patch('paperreader.ui.window.complete', side_effect=model) as complete:
            self.assertTrue(self.window.change_theme('naruto'))
            self.window.question.setPlainText("先看什么？")
            self.window.ask()
            try:
                self.assertTrue(self.window.change_theme('dark'))
                self.assertIn('蛤蟆丸', self.window.chat.toPlainText())
            finally:
                release.set()
                self.wait()
            self.window.question.setPlainText("具体怎么比较？")
            self.window.ask()
            self.wait()

        first, second = [call.args[2] for call in complete.call_args_list]
        self.assertIn('蛤蟆丸', first[0]['content'])
        self.assertIn('直接、中性', second[0]['content'])
        self.assertNotIn('蛤蟆丸', second[0]['content'])
        self.assertTrue(any(m['role'] == 'assistant' and '老夫' in m['content'] for m in second))
        answers = self.library.get(self.paper['id'])['messages'][1::2]
        self.assertEqual([m['assistant_name'] for m in answers], ['蛤蟆丸', '无情的阅读机器'])

    def test_sessions_preserve_history_and_isolate_context(self):
        from paperreader.services.sessions import ensure_sessions
        paper = self.window.paper
        original = ensure_sessions(paper)['id']
        self.window.question.setPlainText('First question')
        with patch('paperreader.ui.window.complete', side_effect=self.model):
            self.window.ask(); self.wait()
        self.window.new_session()
        self.assertEqual(paper['messages'], [])
        second = paper['active_session']
        self.assertNotEqual(original, second)
        self.window.question.setPlainText('Second question')
        def model(config, key, messages, on_chunk=None):
            self.assertFalse(any('First question' in m['content'] for m in messages))
            return self.model(config, key, messages, on_chunk)
        with patch('paperreader.ui.window.complete', side_effect=model):
            self.window.ask(); self.wait()
        self.window.switch_session(original)
        self.assertEqual(paper['messages'][0]['question'], 'First question')
        self.assertEqual(len(self.library.all()[0]['sessions']), 2)
        self.assertEqual(self.window.question_navigation.items, ['First question'])

    def test_followup_identity_question_sends_no_paper_evidence(self):
        self.window.paper["messages"].extend([
            {"role": "user", "content": "上一条关于论文的问题"},
            {"role": "assistant", "content": "首页提到了论文背景"},
        ])
        self.window.question.setPlainText("你是谁？")
        with patch("paperreader.ui.window.complete", return_value="我是无情的阅读机器。") as complete:
            self.window.ask(); self.wait()
        messages = complete.call_args.args[2]
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertEqual(messages[-1]["content"], "你是谁？")
        self.assertIsNone(self.window.passage_index)
        self.assertEqual(self.window.paper["messages"][-1]["citations"], {})

    def test_followup_citations_reopen_and_highlight_source(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QTextCursor

        with fitz.open() as doc:
            doc.new_page().insert_text((72, 80), "Introduction to the paper.")
            doc.new_page().insert_text((72, 500), "Ablation studies remove the retrieval module.")
            paper = self.library.import_pdf(doc.tobytes(), "Retrieval example")
        self.window.reload(paper["id"])
        self.window.show()
        self.window.question.setPlainText("消融怎么做？")
        answer = "作者移除了检索模块【E1】。无效引用【E99】。代码 `【E1】`。"
        with patch("paperreader.ui.window.complete", return_value=answer) as complete:
            self.window.ask(); self.wait()
        messages = complete.call_args.args[2]
        self.assertIn("【E1】第 2 页\nAblation", messages[-1]["content"])
        self.assertNotIn("Introduction to the paper.", messages[-1]["content"])
        saved = self.library.get(paper["id"])["messages"][1]
        self.assertEqual(set(saved["citations"]), {"E1"})
        self.assertIn("【第 2 页】", self.window.answer_with_page_numbers(saved))

        self.window.reload(paper["id"])
        doc = self.window.chat.document()
        cursor = doc.find("第 2 页 · E1")
        self.assertFalse(cursor.isNull())
        cursor.setPosition(cursor.selectionStart())
        cursor.movePosition(QTextCursor.MoveOperation.NextCharacter)
        href = cursor.charFormat().anchorHref()
        self.assertTrue(href.startswith("paperreader-cite://"))
        self.window.chat.anchorClicked.emit(QUrl(href))
        self.assertEqual(self.window.view.citation_page, 1)
        self.assertEqual(self.window.view.pages[1].citation_rects, saved["citations"]["E1"]["rects"])
        self.assertGreater(self.window.view.verticalScrollBar().value(), self.window.view.offsets[1])
        self.assertEqual(self.window.paper["marks"], [])

    def test_question_markers_overflow_and_navigation(self):
        from PySide6.QtCore import QPointF, QPoint, Qt
        from PySide6.QtGui import QWheelEvent
        nav = self.window.question_navigation
        self.window.show()
        nav.update_questions([f'Question {i}' for i in range(50)])
        self.app.processEvents()
        self.assertGreater(nav.horizontalScrollBar().maximum(), 0)
        self.assertEqual(nav.horizontalScrollBar().value(), nav.horizontalScrollBar().maximum())
        nav.choose(45)
        self.assertEqual(nav.current, 45)
        self.assertGreater(nav.horizontalScrollBar().value(), 0)
        nav.horizontalScrollBar().setValue(0)
        event = QWheelEvent(QPointF(10,10), QPointF(10,10), QPoint(-80,0), QPoint(),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.ScrollUpdate, False)
        nav.wheelEvent(event)
        self.assertGreater(nav.horizontalScrollBar().value(), 0)


    def test_role_labels_stay_left_after_indented_markdown(self):
        self.window.paper['messages'] = [
            {'role': 'user', 'content': '> 引用\n\n- 列表'},
            {'role': 'assistant', 'content': '## 回答\n\n正文'},
            {'role': 'user', 'content': '继续提问'}]
        from paperreader.services.sessions import ensure_sessions
        session = ensure_sessions(self.window.paper)
        session['messages'] = self.window.paper['messages'] = [
            {'role': 'user', 'content': '> 引用\n\n- 列表'},
            {'role': 'assistant', 'content': '## 回答\n\n正文'},
            {'role': 'user', 'content': '继续提问'}]
        self.window.render_chat()
        from PySide6.QtCore import Qt
        block = self.window.chat.document().begin()
        labels = []
        while block.isValid():
            if block.text() in ('你', '无情的阅读机器'):
                fmt = block.blockFormat()
                self.assertTrue(fmt.alignment() & Qt.AlignmentFlag.AlignLeft)
                self.assertEqual(fmt.leftMargin(), 0)
                self.assertEqual(fmt.indent(), 0)
                self.assertEqual(fmt.textIndent(), 0)
                labels.append(block.text())
            block = block.next()
        self.assertEqual(labels, ['你', '无情的阅读机器', '你'])

    def test_add_qa_to_notes_keeps_markdown_and_unsaved_notes(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtWidgets import QTabWidget
        from paperreader.services.sessions import ensure_sessions
        session = ensure_sessions(self.window.paper)
        prompt = '引用选区：原文\n\n**为什么？**'
        answer = '## 解释\n\n- 要点\n\n```python\nprint(1)\n```\n\n\\(x_i^2\\)'
        session['messages'] += [{'role':'user','content':prompt}, {'role':'assistant','content':answer}]
        notes = self.window.notes
        notes.setPlainText('还未自动保存的笔记\n\n' + '已有内容\n\n' * 100)
        self.window.show()
        self.window.splitter.widget(2).findChild(QTabWidget).setCurrentWidget(notes)
        notes.tabs.setCurrentWidget(notes.preview)
        self.app.processEvents()
        bar = notes.preview.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        bar.setValue(0)
        self.window.render_chat()
        url = QUrl(f"paperreader-note://add?paper={self.window.paper['id']}&session={session['id']}&message=1")
        button = self.window.chat.document().find('添加到笔记')
        self.assertEqual(QUrl(button.charFormat().anchorHref()), url)
        self.window.chat.anchorClicked.emit(url)
        self.assertIs(notes.tabs.currentWidget(), notes.preview)
        self.assertIn('解释', notes.preview.toPlainText())
        self.assertEqual(bar.value(), bar.maximum())
        saved = self.library.all()[0]['notes']
        self.assertTrue(saved.startswith('还未自动保存的笔记'))
        self.assertIn(prompt, saved); self.assertIn(answer, saved)
        self.assertEqual(self.window.notes.toPlainText(), saved)
        bar.setValue(0)
        self.window.chat.anchorClicked.emit(url)
        self.assertEqual(notes.preview.toPlainText().count('解释'), 2)
        self.assertEqual(bar.value(), bar.maximum())
        self.assertTrue(self.window.notes.toPlainText().startswith(saved))
        self.assertEqual(self.window.notes.toPlainText().count(answer), 2)
        self.assertNotIn("noted_answers", session)


    def test_top_note_action_uses_selected_question_and_separator(self):
        from paperreader.services.sessions import ensure_sessions
        session = ensure_sessions(self.window.paper)
        session['messages'] += [
            {'role': 'user', 'content': 'question one'}, {'role': 'assistant', 'content': '**answer one**'},
            {'role': 'user', 'content': 'question two'}, {'role': 'assistant', 'content': 'answer two'}]
        self.window.notes.setPlainText('existing notes')
        self.window.render_chat()
        self.window.question_navigation.choose(0)
        from PySide6.QtWidgets import QMenu
        from PySide6.QtCore import QPoint
        from unittest.mock import MagicMock
        from PySide6.QtGui import QAction
        menu = MagicMock(); action = QAction('添加到笔记', self.window)
        menu.addAction.return_value = action
        menu.exec.side_effect = lambda position: action.trigger()
        with patch('paperreader.ui.window.QMenu', return_value=menu):
            self.window.question_context_menu(0, QPoint(10,10))
        notes = self.window.notes.toPlainText()
        self.assertIn('existing notes\n\n---\n\n', notes)
        self.assertIn('question one', notes); self.assertIn('**answer one**', notes)
        self.assertNotIn('question two', notes)
        self.assertNotIn("noted_answers", session)
        self.assertNotIn('加入笔记', self.window.chat.toPlainText())
        self.window.question_navigation.choose(1)
        self.assertNotIn("noted_answers", session)


    def test_batch_pdf_import_partial_failure(self):
        from pathlib import Path
        source = Path(self.temp.name)/'source.pdf'
        doc = fitz.open(); doc.new_page().insert_text((72,72), 'Batch paper'); source.write_bytes(doc.tobytes()); doc.close()
        invalid = Path(self.temp.name)/'broken.pdf'; invalid.write_text('not PDF')
        with patch('paperreader.ui.window.QFileDialog.getOpenFileNames', return_value=([str(source), str(invalid)], '')):
            self.window.import_file()
        self.assertEqual(len(self.library.all()), 2)
        self.assertTrue(self.errors)

    def test_clear_learning_confirms_and_keeps_pdf_and_favorite(self):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QMessageBox

        with fitz.open() as doc:
            doc.new_page().insert_text((72, 72), "First page")
            doc.new_page().insert_text((72, 72), "Second page")
            imported = self.library.import_pdf(doc.tobytes(), "Paper with reading progress")
        self.window.reload(imported["id"])
        paper = self.window.paper
        old_session = paper["active_session"]
        paper["summary"] = "旧概要"
        paper["analyses"] = {"deep": {"text": "旧精读"}}
        paper["notes"] = "旧笔记"
        paper["messages"].append({"role": "user", "content": "旧问题"})
        paper["marks"] = [{"page": 1, "text": "批注原文", "comment": "旧批注", "rects": [], "highlight": True}]
        self.window.view.jump(1)
        self.assertEqual(paper["page"], 1)
        self.library.save(paper)
        self.library.set_favorite(paper["id"], True)
        self.window.notes.setPlainText("待保存的旧笔记")
        self.window.question.setPlainText("旧问题草稿")
        self.window.ask_about_analysis("旧引用")
        self.window.preview_mark(0)

        def click_confirmation(label):
            dialog = next(d for d in self.window.findChildren(QMessageBox) if d.isVisible())
            next(button for button in dialog.buttons() if button.text() == label).click()

        QTimer.singleShot(0, lambda: click_confirmation("取消"))
        self.window.clear_paper_learning(paper)
        self.assertEqual(self.window.paper["summary"], "旧概要")
        self.assertEqual(self.window.notes.toPlainText(), "待保存的旧笔记")

        QTimer.singleShot(0, lambda: click_confirmation("确认清除"))
        self.window.clear_paper_learning(paper)
        self.window.save_notes()
        saved = self.library.get(paper["id"])
        for field, value in (("summary", ""), ("analyses", {}), ("notes", ""), ("messages", [])):
            self.assertEqual(saved[field], value)
        self.assertEqual(len(saved["sessions"]), 1)
        self.assertNotEqual(saved["active_session"], old_session)
        self.assertEqual(saved["marks"], [])
        self.assertEqual(saved["page"], 0)
        self.assertEqual(self.window.page_label.text(), "1 / 2")
        self.assertEqual(self.window.mark_preview.toPlainText(), "")
        self.assertEqual(self.window.marks.count(), 0)
        self.assertTrue(self.library.pdf_path(saved).exists())
        self.assertTrue(self.library.list_metadata()[0]["favorite"])
        self.assertEqual(self.window.question.toPlainText(), "")
        self.assertEqual(self.window.quote, "")
        self.assertEqual(self.window.question_navigation.items, [])

    def test_purge_current_paper_clears_ui_and_cannot_resurrect(self):
        from unittest.mock import MagicMock
        from PySide6.QtWidgets import QMessageBox
        paper = self.window.paper
        self.window.notes.setPlainText('pending note')
        dialog = MagicMock(); dialog.findChild.return_value = None
        from PySide6.QtWidgets import QPushButton
        cancel, hide, purge = QPushButton(), QPushButton(), QPushButton()
        dialog.addButton.side_effect = [cancel, hide, purge]
        dialog.clickedButton.return_value = purge
        with patch('paperreader.ui.window.QMessageBox', dialog_factory := MagicMock(return_value=dialog)):
            dialog_factory.ButtonRole = QMessageBox.ButtonRole
            self.window.remove_paper(paper)
        self.assertIsNone(self.window.paper)
        self.assertEqual(self.library.all(include_removed=True), [])
        self.assertFalse(self.library.pdf_path(paper).exists())
        self.window.save_notes(); self.window.persist()
        self.assertEqual(self.library.all(include_removed=True), [])


    def test_quick_and_deep_reports_are_separate_and_streamed(self):
        with patch('paperreader.ui.window.complete', side_effect=self.model):
            self.window.analyze(); self.wait()
            self.assertTrue(self.window.paper['analyses']['quick']['complete'])
            quick = self.window.paper['analyses']['quick']['text']
            self.window.analysis_mode.setCurrentIndex(1)
            self.window.analyze(); self.wait()
        analyses = self.library.all()[0]['analyses']
        self.assertEqual(analyses['quick']['text'], quick)
        self.assertTrue(analyses['deep']['complete'])
        self.assertIn('分段精读记录', analyses['deep']['text'])
        self.assertIn('精读报告', self.window.summary.toPlainText())


    def test_scrollbar_reveal_hides_whole_bar_without_changing_layout(self):
        self.window.show(); self.app.processEvents()
        controller = self.app._paperreader_hover_scrollbars
        self.window.chat.set_markdown('line\n\n'*100)
        self.app.processEvents()
        area = self.window.chat
        controller.register(area)
        bar = area.verticalScrollBar()
        width = area.viewport().width()
        controller.set_active(None)
        self.assertEqual(bar.graphicsEffect().opacity(), 0)
        controller.set_active(area)
        self.assertEqual(bar.graphicsEffect().opacity(), 1)
        controller.set_active(self.window.view)
        self.assertEqual(bar.graphicsEffect().opacity(), 0)
        self.assertEqual(area.viewport().width(), width)
        bar.setValue(bar.maximum())
        self.assertGreater(bar.value(), 0)


    def test_drag_stays_in_starting_column(self):
        from PySide6.QtCore import QPoint
        from paperreader.ui.pdf import PageView
        doc = fitz.open(); page = doc.new_page(width=600, height=800)
        for row in range(8):
            page.insert_text((50,100+row*18), f'LEFT{row} some words for this paper', fontsize=11)
            page.insert_text((330,100+row*18), f'RIGHT{row} other words for this paper', fontsize=11)
        view = PageView(); view.display(page, [])
        def centre(word):
            r = fitz.Rect(word[:4])*page.rotation_matrix
            return QPoint(round((r.x0+r.x1)/2*view.scale), round((r.y0+r.y1)/2*view.scale))
        for rotation in (0, 90):
            page.set_rotation(rotation); view.display(page, [])
            for prefix, excluded in [('LEFT', 'RIGHT'), ('RIGHT','LEFT')]:
                first = next(w for w in view.words if w[4] == prefix+'1')
                last = next(w for w in view.words if w[4] == prefix+'5')
                for start, end in [(first,last),(last,first)]:
                    view.anchor, view.endpoint = centre(start), centre(end)
                    text, rects = view.selected()
                    self.assertIn(prefix+'3', text)
                    self.assertNotIn(excluded, text)
                    self.assertTrue(all(r[0]<300 if prefix=='LEFT' else r[0]>300 for r in rects))
        view.close(); doc.close()


    def test_startup_only_loads_metadata_then_selected_paper(self):
        self.window.close()
        with patch.object(self.library, 'all', side_effect=AssertionError('Must not load all')), \
             patch.object(self.library, 'get', wraps=self.library.get) as get_record:
            window = Window(library=self.library)
            self.assertEqual(window.list.count(), 1)
            self.assertIsNone(window.paper)
            self.assertIsNone(window.doc)
            get_record.assert_not_called()
            window.list.setCurrentRow(0)
            get_record.assert_called_once_with(self.paper['id'])
            self.assertIsNotNone(window.doc)
            window.close()
