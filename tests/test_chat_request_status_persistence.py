"""A saved chat answer retains its model call status after reopening."""

import os
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from paperreader.services.library import Library
from paperreader.ui.window import Window


class ChatRequestStatusPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_completed_call_restores_status_and_log(self):
        with tempfile.TemporaryDirectory() as root:
            library = Library(root)
            document = fitz.open()
            document.new_page().insert_text((72, 72), "Paper text")
            paper = library.import_pdf(document.tobytes(), "Status persistence")
            document.close()

            def answer(config, key, messages, on_chunk=None):
                on_chunk("测试答复")
                return "测试答复"

            with patch("paperreader.ui.window.keyring.get_password", return_value="test"), \
                    patch("paperreader.ui.window.complete", side_effect=answer):
                window = Window(library=library)
                window.reload(paper["id"])
                window.question.setPlainText("请解释本文")
                window.ask()
                deadline = time.monotonic() + 5
                while window.busy and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.005)
                self.app.processEvents()
                self.assertFalse(window.busy)
                saved = library.get(paper["id"])
                record = saved["sessions"][0]["messages"][1]["request_status"]
                self.assertEqual(set(record), {"title", "log", "expanded"})
                self.assertIn("已完成", record["title"])
                self.assertIn("模型", record["log"])
                self.assertNotIn("请解释本文", record["log"])
                window.close()
                library.db.close()

                reopened_library = Library(root)
                reopened = Window(library=reopened_library)
                try:
                    reopened.reload(paper["id"])
                    self.assertIn("已完成", reopened.chat.toPlainText())
                    self.assertIn("已接收 4 字符", reopened.chat.toPlainText())
                    self.assertEqual(len(reopened.chat_status.records), 1)
                    reopened.chat.anchorClicked.emit(QUrl("paperreader-status:toggle?message=0"))
                    self.assertIn("正在调用模型", reopened.chat.toPlainText())
                finally:
                    reopened.close()
                    reopened_library.db.close()


if __name__ == "__main__":
    unittest.main()
