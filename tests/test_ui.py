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

    def test_settings_add_and_save_multiple_profiles(self):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton, QDialogButtonBox
        from paperreader.ui.window import SettingsDialog
        saved_keys = {}
        errors = []
        def edit():
            try:
                dialog = next(d for d in self.window.findChildren(SettingsDialog) if d.isVisible())
                next(b for b in dialog.findChildren(QPushButton) if b.text() == '新增配置').click()
                dialog.findChild(QLineEdit, 'ModelEndpoint').setText('https://example.org/v1')
                dialog.findChild(QLineEdit, 'ModelName').setText('new-model')
                dialog.findChild(QLineEdit, 'ModelKey').setText('new-secret')
                dialog.findChild(QLineEdit, 'ProfileName').setText('备用模型')
                dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
            except Exception as exc:
                errors.append(exc)
                for dialog in self.window.findChildren(SettingsDialog): dialog.reject()
        with patch('paperreader.ui.window.keyring.set_password', side_effect=lambda service, account, secret: saved_keys.update({account: secret})):
            QTimer.singleShot(0, edit); self.window.settings()
        self.assertFalse(errors, str(errors))
        config = self.library.config()
        self.assertEqual(len(config['profiles']), 2)
        self.assertEqual(self.window.config['model'], 'new-model')
        self.assertEqual(saved_keys[self.window.config['key_account']], 'new-secret')
        self.assertNotIn('new-secret', str(config))

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

    def test_question_markers_overflow_and_navigation(self):
        from PySide6.QtCore import QPointF, QPoint, Qt
        from PySide6.QtGui import QWheelEvent
        nav = self.window.question_navigation
        self.window.show()
        nav.update_questions([f'Question {i}' for i in range(50)])
        self.app.processEvents()
        self.assertGreater(nav.horizontalScrollBar().maximum(), 0)
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
            if block.text() in ('你', '蛤蟆丸'):
                fmt = block.blockFormat()
                self.assertTrue(fmt.alignment() & Qt.AlignmentFlag.AlignLeft)
                self.assertEqual(fmt.leftMargin(), 0)
                self.assertEqual(fmt.indent(), 0)
                self.assertEqual(fmt.textIndent(), 0)
                labels.append(block.text())
            block = block.next()
        self.assertEqual(labels, ['你', '蛤蟆丸', '你'])

    def test_add_qa_to_notes_keeps_markdown_and_unsaved_notes(self):
        from PySide6.QtCore import QUrl
        from paperreader.services.sessions import ensure_sessions
        session = ensure_sessions(self.window.paper)
        prompt = '引用选区：原文\n\n**为什么？**'
        answer = '## 解释\n\n- 要点\n\n```python\nprint(1)\n```\n\n\\(x_i^2\\)'
        session['messages'] += [{'role':'user','content':prompt}, {'role':'assistant','content':answer}]
        self.window.notes.setPlainText('还未自动保存的笔记')
        self.window.render_chat()
        url = QUrl(f"paperreader-note://add?paper={self.window.paper['id']}&session={session['id']}&message=1")
        self.window.add_answer_to_notes(url)
        saved = self.library.all()[0]['notes']
        self.assertTrue(saved.startswith('还未自动保存的笔记'))
        self.assertIn(prompt, saved); self.assertIn(answer, saved)
        self.assertEqual(self.window.notes.toPlainText(), saved)
        self.window.add_answer_to_notes(url)
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
