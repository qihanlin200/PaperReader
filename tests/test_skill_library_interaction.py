"""Acceptance checks for staged edits and the skill-library navigation."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox

from paperreader.research_agent import domain_registry
from paperreader.services.library import Library
from paperreader.ui.window import Window
from paperreader.ui.work_rail import draw_symbol


class SkillLibraryInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.root_patch = patch.object(domain_registry, "USER_DOMAIN_ROOT", self.root / "skills")
        self.root_patch.start()
        self.library = Library(self.root / "library")
        self.lib_patch = patch("paperreader.ui.window.Library", return_value=self.library)
        self.key_patch = patch("paperreader.ui.window.keyring.get_password", return_value="test")
        self.lib_patch.start()
        self.key_patch.start()
        self.window = Window()
        self.window.toggle_skills()
        self.widget = self.window.skill_library
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.lib_patch.stop()
        self.key_patch.stop()
        self.library.db.close()
        self.root_patch.stop()
        self.temporary.cleanup()

    def test_existing_skill_only_takes_effect_after_save(self):
        self.widget.reload(preferred=("domain", "game"))
        before = domain_registry.load_domain_skill("game").description
        self.assertFalse(self.widget.save_button.isVisible())
        self.assertFalse(self.widget.save_button.isEnabled())

        self.widget.edit_current()
        self.assertTrue(self.widget.save_button.isVisible())
        self.widget.description.setPlainText("待保存的游戏研究规则")
        self.assertEqual(domain_registry.load_domain_skill("game").description, before)
        self.assertTrue(self.widget.save_button.isEnabled())
        self.widget.save_button.click()

        self.assertEqual(domain_registry.load_domain_skill("game").description,
                         "待保存的游戏研究规则")
        self.assertIn("已保存", self.window.statusBar().currentMessage())
        self.assertFalse(self.widget.save_button.isEnabled())

    def test_cancel_keeps_runtime_skill_unchanged(self):
        self.widget.reload(preferred=("domain", "medicine"))
        before = domain_registry.load_domain_skill("medicine").description
        self.widget.edit_current()
        self.widget.description.setPlainText("不会生效")
        self.widget.cancel_edit()
        self.assertEqual(domain_registry.load_domain_skill("medicine").description, before)

    def test_leaving_with_unsaved_changes_can_be_cancelled_or_discarded(self):
        self.widget.reload(preferred=("domain", "game"))
        original = domain_registry.load_domain_skill("game").description
        self.widget.edit_current()
        self.widget.description.setPlainText("尚未保存")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.window.show_reader())
        self.assertIs(self.window.workspace_stack.currentWidget(), self.widget)
        self.assertEqual(domain_registry.load_domain_skill("game").description, original)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(self.window.show_reader())
        self.assertIs(self.window.workspace_stack.currentWidget(), self.window.splitter)
        self.assertEqual(domain_registry.load_domain_skill("game").description, original)

    def test_skill_groups_and_detail_can_collapse_and_expand(self):
        def rows(category):
            return [self.widget.catalog.item(index) for index in range(self.widget.catalog.count())
                    if (key := self.widget.catalog.item(index).data(Qt.ItemDataRole.UserRole))
                    and key[0] == category]

        self.assertEqual(len(rows("domain")), 4)
        self.assertEqual(len(rows("task")) + len(rows("workflow")) + len(rows("postprocess")), 0)
        system_header = next(self.widget.catalog.item(index)
                             for index in range(self.widget.catalog.count())
                             if self.widget.catalog.item(index).data(Qt.ItemDataRole.UserRole)
                             == ("group", "system"))
        self.widget.toggle_group(system_header)
        self.assertEqual(len(rows("task")) + len(rows("workflow")) + len(rows("postprocess")), 4)

        self.widget.reload(preferred=("domain", "game"))
        self.assertTrue(self.widget.domain_fields.isVisible())
        self.widget.toggle_domain_content()
        self.assertFalse(self.widget.domain_fields.isVisible())
        self.widget.toggle_domain_content()
        self.assertTrue(self.widget.domain_fields.isVisible())
        self.widget.toggle_stages()
        self.assertFalse(self.widget.tabs.isVisible())
        self.widget.toggle_stages()
        self.assertTrue(self.widget.tabs.isVisible())

        self.widget.reload(preferred=("task", "literature_compare"))
        self.assertEqual(self.widget.content.currentWidget(), self.widget.system_page)
        self.assertTrue(self.widget.system_text.isReadOnly())
        self.assertNotEqual(self.widget.system_text.objectName(), self.widget.description.objectName())
        self.assertTrue(self.widget.system_text.isVisible())
        self.widget.toggle_system_content()
        self.assertFalse(self.widget.system_text.isVisible())
        self.widget.toggle_system_content()
        self.assertTrue(self.widget.system_text.isVisible())

    def test_naruto_rail_art_is_distinct_and_theme_recolors_catalog(self):
        self.widget.reload(preferred=("domain", "game"))
        domain_item = next(self.widget.catalog.item(index)
                           for index in range(self.widget.catalog.count())
                           if self.widget.catalog.item(index).data(Qt.ItemDataRole.UserRole)
                           == ("domain", "game"))
        dark_color = domain_item.background().color().name()
        self.assertTrue(self.window.change_theme("naruto"))
        domain_item = next(self.widget.catalog.item(index)
                           for index in range(self.widget.catalog.count())
                           if self.widget.catalog.item(index).data(Qt.ItemDataRole.UserRole)
                           == ("domain", "game"))
        self.assertNotEqual(domain_item.background().color().name(), dark_color)

        artwork = []
        for symbol in ("library", "research", "skills", "settings"):
            canvas = QPixmap(26, 26)
            canvas.fill(Qt.GlobalColor.transparent)
            painter = QPainter(canvas)
            draw_symbol(painter, symbol, QColor("#eca16e"))
            painter.end()
            data = QByteArray()
            buffer = QBuffer(data)
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            canvas.save(buffer, "PNG")
            artwork.append(bytes(data))
        self.assertEqual(len(set(artwork)), 4)


if __name__ == "__main__":
    unittest.main()
