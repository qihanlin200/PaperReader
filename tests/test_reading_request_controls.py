"""Reading call details persist, and a chat answer can be stopped."""
import os
import json
import tempfile
import time
import unittest
from threading import Event
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import fitz
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from paperreader.services.analysis import AnalysisStopped
from paperreader.services.library import Library
from paperreader.ui.window import Window


class ReadingRequestControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, root):
        library = Library(root)
        document = fitz.open()
        document.new_page().insert_text((72, 72), 'Paper text with a method and a result.')
        paper = library.import_pdf(document.tobytes(), 'Request controls')
        document.close()
        window = Window(library=library)
        window.reload(paper['id'])
        return window, library, paper['id']

    def wait_for(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.app.processEvents()
        self.assertTrue(condition())

    def test_analysis_call_usage_is_saved_and_expandable(self):
        with tempfile.TemporaryDirectory() as root, \
                patch('paperreader.ui.window.keyring.get_password', return_value='test'):
            def model(config, key, messages, on_chunk=None, *, cancel=None, on_usage=None):
                on_chunk('一句话概括：测试。')
                on_usage({'prompt_tokens': 123, 'completion_tokens': 45, 'total_tokens': 168})
                return '一句话概括：测试。'
            with patch('paperreader.ui.window.complete', side_effect=model):
                window, library, paper_id = self.make_window(root)
                try:
                    window.analyze()
                    self.wait_for(lambda: not window.busy)
                    record = library.get(paper_id)['analyses']['quick']['request_status']
                    self.assertIn('调用 1 次', record['title'])
                    self.assertIn('输入 123 tokens', record['log'])
                    self.assertIn('输出 45 tokens', record['log'])
                finally:
                    window.close()
                    library.db.close()
            reopened, library, _ = self.make_window(root)
            try:
                reopened.reload(paper_id)
                self.assertIn('调用 1 次', reopened.summary.toPlainText())
                reopened.summary.anchorClicked.emit(QUrl('paperreader-status:toggle'))
                self.assertIn('输入 123 tokens', reopened.summary.toPlainText())
            finally:
                reopened.close()
                library.db.close()

    def test_chat_send_button_stops_stream_and_keeps_partial_answer(self):
        with tempfile.TemporaryDirectory() as root, \
                patch('paperreader.ui.window.keyring.get_password', return_value='test'):
            def model(config, key, messages, on_chunk=None, *, cancel=None):
                on_chunk('部分回答')
                if cancel.wait(2):
                    raise AnalysisStopped()
                return '部分回答后继续'
            with patch('paperreader.ui.window.complete', side_effect=model):
                window, library, paper_id = self.make_window(root)
                try:
                    window.question.setPlainText('解释论文方法')
                    window.send_button.click()
                    self.assertEqual(window.send_button.text(), '停止')
                    self.wait_for(lambda: '部分回答' in window.chat.toPlainText())
                    window.send_button.click()
                    self.assertEqual(window.send_button.text(), '停止中…')
                    self.wait_for(lambda: not window.busy)
                    self.assertEqual(window.send_button.text(), '发送 ↑')
                    saved = library.get(paper_id)['messages'][-1]
                    self.assertIn('已停止', saved['content'])
                    self.assertIn('部分回答', saved['content'])
                    self.assertIn('已停止', saved['request_status']['title'])
                finally:
                    window.close()
                    library.db.close()

    def test_deep_reading_progress_advances_and_retains_completion(self):
        with tempfile.TemporaryDirectory() as root, \
                patch('paperreader.ui.window.keyring.get_password', return_value='test'):
            phase_release = Event()
            release = Event()
            def analysis(pages, config, key, mode, complete, emit, **kwargs):
                emit(json.dumps({'kind': 'plan', 'plan': 'v5', 'total': 1, 'completed': 0}))
                emit(json.dumps({'kind': 'section', 'title': '全文精读 · 完整原文', 'prefix': ''}))
                emit(json.dumps({'kind': 'text', 'text': '# 分段报告\n' + '证据' * 100}))
                phase_release.wait(2)
                emit(json.dumps({'kind': 'text', 'text': '\n# 精读报告\n' + '分析' * 200}))
                release.wait(2)
                return {'scope': '全文', 'text': '报告', 'report': '报告',
                        'segments_text': '分段', 'segments': 1}
            with patch('paperreader.ui.window.run_analysis', side_effect=analysis):
                window, library, _ = self.make_window(root)
                try:
                    window.show()
                    window.analysis_mode.setCurrentIndex(1)
                    window.analyze()
                    self.wait_for(lambda: 0 < window.analysis_progress_bar.value() < 50)
                    self.assertTrue(window.analysis_progress_widget.isVisible())
                    self.assertIn('约', window.analysis_progress_label.text())
                    self.assertLess(window.analysis_progress_widget.geometry().left(), 20)
                    phase_release.set()
                    self.wait_for(lambda: 50 < window.analysis_progress_bar.value() < 95)
                    release.set()
                    self.wait_for(lambda: not window.busy)
                    self.assertEqual(window.analysis_progress_bar.value(), 100)
                    self.assertTrue(window.analysis_progress_widget.isVisible())
                    self.assertIn('已完成', window.analysis_progress_state.text())
                    other = fitz.open()
                    other.new_page().insert_text((72, 72), 'A different paper.')
                    second = library.import_pdf(other.tobytes(), 'Other paper')
                    other.close()
                    window.reload(second['id'])
                    self.assertTrue(window.analysis_progress_widget.isHidden())
                finally:
                    phase_release.set()
                    release.set()
                    deadline = time.monotonic() + 3
                    while window.busy and time.monotonic() < deadline:
                        self.app.processEvents()
                        time.sleep(.005)
                    window.close()
                    library.db.close()


if __name__ == '__main__':
    unittest.main()
