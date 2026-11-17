"""Exercise the skill library's user workflow without real file dialogs."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from paperreader.research_agent import domain_registry
from paperreader.services.library import Library
from paperreader.ui.skill_library import SkillLibrary
from paperreader.ui.window import Window


class SkillLibraryUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.root_patch = patch.object(domain_registry, "USER_DOMAIN_ROOT", self.root)
        self.root_patch.start()
        self.widget = SkillLibrary()

    def tearDown(self):
        self.widget.close()
        self.root_patch.stop()
        self.temporary.cleanup()

    def test_create_edit_export_delete_import_from_ui(self):
        self.assertEqual(len(self.widget.entries), 8)
        self.widget.new_skill()
        self.widget.skill_id.setText("local_study")
        self.widget.description.setPlainText("本地研究")
        self.widget.when.setPlainText("研究本地资料时")
        for stage, editor in self.widget.stage_edits.items():
            editor.setPlainText(f"{stage} 先核对资料")
        self.widget.save_current()
        self.assertEqual(self.widget.current_data["id"], "local_study")
        self.assertIn("local_study", domain_registry.discover_domain_skills())

        self.widget.edit_current()
        self.widget.description.setPlainText("修改后的描述")
        self.widget.save_current()
        self.assertEqual(self.widget.current_data["manifest"]["description"], "修改后的描述")

        archive = self.root / "local_study.zip"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(archive), "技能包 (*.zip)")):
            self.widget.export_current()
        self.assertTrue(archive.is_file())

        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.widget.delete_current()
        self.assertNotIn("local_study", domain_registry.discover_domain_skills())

        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(archive), "技能包 (*.zip)")):
            self.widget.import_skill()
        self.assertEqual(self.widget.current_data["id"], "local_study")
        self.assertIn("local_study", domain_registry.discover_domain_skills())

    def test_builtin_domain_disable_and_restore_from_ui(self):
        self.widget.reload(preferred=("domain", "game"))
        self.assertEqual(self.widget.current_data["id"], "game")
        self.assertTrue(self.widget.delete_button.isVisible() or not self.widget.isVisible())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.widget.delete_current()
        self.assertIsNone(domain_registry.load_domain_skill("game"))
        self.assertTrue(self.widget.current_data["disabled"])
        self.widget.restore_current()
        self.assertIsNotNone(domain_registry.load_domain_skill("game"))
        self.assertEqual(self.widget.current_data["id"], "game")

    def test_cancel_edit_keeps_saved_definition(self):
        self.widget.reload(preferred=("domain", "medicine"))
        original = self.widget.current_data["manifest"]["description"]
        self.widget.edit_current()
        self.widget.description.setPlainText("未保存的文字")
        self.widget.cancel_edit()
        self.assertEqual(self.widget.description.toPlainText(), original)
        self.assertEqual(domain_registry.load_domain_skill("medicine").description, original)

    def test_rail_entry_switches_between_reader_research_and_skills(self):
        library = Library(self.root / "library")
        with (patch("paperreader.ui.window.Library", return_value=library),
              patch("paperreader.ui.window.keyring.get_password", return_value="test")):
            window = Window()
            try:
                rail = window.skills_rail_button.parentWidget().layout()
                self.assertEqual(rail.indexOf(window.skills_rail_button),
                                 rail.indexOf(window.research_rail_button) + 1)
                window.toggle_skills()
                self.assertIs(window.workspace_stack.currentWidget(), window.skill_library)
                window.toggle_research()
                self.assertIs(window.workspace_stack.currentWidget(), window.research_workspace)
                window.toggle_skills()
                self.assertIs(window.workspace_stack.currentWidget(), window.skill_library)
                window.toggle_skills()
                self.assertIs(window.workspace_stack.currentWidget(), window.splitter)
            finally:
                window.close()
                library.db.close()


if __name__ == "__main__":
    unittest.main()
