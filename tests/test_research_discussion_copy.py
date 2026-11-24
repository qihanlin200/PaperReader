"""Copy text from the research discussion and paste it into the composer."""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from paperreader.services.library import Library
from paperreader.ui.research import DiscussionQuestion
from paperreader.ui.window import Window


class ResearchDiscussionCopyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_question_and_answer_can_be_selected_and_pasted(self):
        with tempfile.TemporaryDirectory() as root:
            library = Library(root)
            window = Window(library=library)
            try:
                window.resize(1400, 850)
                window.show()
                window.toggle_research()
                workspace = window.research_workspace
                run = {"id": "copy-test", "question": "研究问题测试", "answer": "研究答复测试",
                       "status": "已完成", "workflow": {"mode": "answer"}}
                workspace.render_discussion({"runs": [run]})
                self.app.processEvents()

                row, reply, *_ = workspace.turn_rows["copy-test"]
                question = row.findChild(DiscussionQuestion)
                selectable = Qt.TextInteractionFlag.TextSelectableByMouse
                self.assertTrue(question.textInteractionFlags() & selectable)
                self.assertTrue(reply.textInteractionFlags() & selectable)

                question.setFocus()
                question.setSelection(0, len(question.text()))
                self.assertEqual(question.selectedText(), "研究问题测试")
                QTest.keyClick(question, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
                self.assertEqual(self.app.clipboard().text(), "研究问题测试")
                workspace.composer.setFocus()
                QTest.keyClick(workspace.composer, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
                self.assertEqual(workspace.composer.toPlainText(), "研究问题测试")

                reply.setFocus()
                reply.setSelection(0, len("研究答复测试"))
                self.assertIn("研究答复测试", reply.selectedText())
                QTest.keyClick(reply, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
                self.assertIn("研究答复测试", self.app.clipboard().text())
            finally:
                window.close()
                library.db.close()


if __name__ == "__main__":
    unittest.main()
