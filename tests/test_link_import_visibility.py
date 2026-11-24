import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PySide6.QtWidgets import QApplication
from paperreader.services.library import Library
from paperreader.ui.window import Window


class LinkImportVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def pdf(text):
        with fitz.open() as doc:
            doc.new_page().insert_text((72, 72), text)
            return doc.tobytes()

    def test_duplicate_in_group_reveals_existing_paper_and_source(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Library(directory)
            original_data = self.pdf("Existing paper")
            original = library.import_pdf(original_data, "Existing paper")
            group_id = library.create_group("Agent自进化")
            library.set_group(original["id"], group_id)
            other = library.import_pdf(self.pdf("Other paper"), "Other paper")
            window = Window(library=library)
            try:
                window.show()
                window.reload(other["id"])
                window.collapsed_groups.add(group_id)
                window.paper_search.setText("Other paper")
                window.finish_link_import(original_data, "https://arxiv.org/abs/2408.08435")
                self.app.processEvents()
                row = window.row_for_paper(original["id"])
                self.assertGreaterEqual(row, 0)
                self.assertEqual(window.paper["id"], original["id"])
                self.assertEqual(window.list.currentRow(), row)
                self.assertNotIn(group_id, window.collapsed_groups)
                self.assertEqual(window.paper_search.text(), "")
                self.assertTrue(window.list.visualItemRect(window.list.item(row)).intersects(window.list.viewport().rect()))
                self.assertIn("已存在于「Agent自进化」", window.statusBar().currentMessage())
                self.assertEqual(library.get(original["id"])["source"], "https://arxiv.org/abs/2408.08435")
                self.assertEqual(len(library.list_metadata()), 2)
            finally:
                window.close()
                library.db.close()


if __name__ == "__main__":
    unittest.main()
