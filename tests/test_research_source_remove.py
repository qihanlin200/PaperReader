"""Removing a research source only unlinks it from the current topic."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PySide6.QtWidgets import QApplication
from paperreader.services.library import Library
from paperreader.ui.window import Window


class ResearchSourceRemoveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_right_click_unlinks_text_and_pdf_without_deleting_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            text_file = root / "notes.md"
            text_file.write_text("local source text", encoding="utf-8")
            pdf_file = root / "paper.pdf"
            with fitz.open() as doc:
                doc.new_page().insert_text((72, 72), "Paper source")
                pdf_file.write_bytes(doc.tobytes())
            library = Library(directory)
            window = Window(library=library)
            try:
                window.show()
                window.toggle_research()
                workspace = window.research_workspace
                space = {"id": "topic-1", "name": "研究课题", "sources": [], "runs": []}
                workspace.spaces.append(space)
                workspace.add_space_item(space["name"])
                workspace.space_list.setCurrentRow(0)
                with patch("paperreader.ui.research.QFileDialog.getOpenFileNames",
                           return_value=([str(text_file), str(pdf_file)], "")):
                    workspace.import_local()
                self.app.processEvents()
                self.assertEqual(workspace.sources.count(), 2)
                text_source = next(item for item in space["sources"] if item["kind"] == "text")
                paper_source = next(item for item in space["sources"] if item["kind"] == "paper")
                pdf_copy = library.pdf_path(paper_source)
                self.assertTrue(pdf_copy.exists())
                row = next(i for i, item in enumerate(space["sources"])
                           if item["id"] == text_source["id"])
                self.assertEqual(workspace.sources.contextMenuPolicy().name, "CustomContextMenu")
                workspace.preview_source(workspace.sources.item(row))
                self.assertEqual(workspace.previewed_source_id, text_source["id"])
                menu = workspace.build_source_menu(workspace.sources.item(row))
                self.assertEqual([action.text() for action in menu.actions()], ["从知识库移出"])
                menu.actions()[0].trigger()
                menu.deleteLater()
                self.assertIsNone(workspace.previewed_source_id)
                self.assertEqual(workspace.sources.count(), 1)
                self.assertEqual(space["sources"][0]["id"], paper_source["id"])
                self.assertTrue(text_file.exists())
                self.assertNotIn(text_source["id"],
                                 [item["id"] for item in json.loads(workspace.path.read_text())[0]["sources"]])
                self.assertTrue(workspace.remove_source(0))
                self.assertEqual(space["sources"], [])
                self.assertTrue(pdf_file.exists())
                self.assertTrue(pdf_copy.exists())
                self.assertEqual(len(library.list_metadata()), 1)
                self.assertEqual(json.loads(workspace.path.read_text())[0]["sources"], [])
            finally:
                window.close()
                library.db.close()

    def test_save_failure_restores_source(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Library(directory)
            window = Window(library=library)
            try:
                window.toggle_research()
                workspace = window.research_workspace
                source = {"kind": "text", "id": "note", "title": "note.txt", "text": "hello"}
                space = {"id": "topic-1", "name": "研究课题", "sources": [source], "runs": []}
                workspace.spaces.append(space)
                workspace.add_space_item(space["name"])
                workspace.space_list.setCurrentRow(0)
                workspace.active = (space, None, None)
                menu = workspace.build_source_menu(workspace.sources.item(0))
                self.assertFalse(menu.actions()[0].isEnabled())
                self.assertFalse(workspace.remove_source(0))
                menu.deleteLater()
                workspace.active = None
                with patch.object(workspace, "save", return_value=False):
                    self.assertFalse(workspace.remove_source(0))
                self.assertEqual(space["sources"], [source])
                self.assertEqual(workspace.sources.count(), 1)
            finally:
                window.close()
                library.db.close()


if __name__ == "__main__":
    unittest.main()
