"""Acceptance checks for the compact, vertically scrolling skill page."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QLabel

from paperreader.research_agent import domain_registry
from paperreader.services.library import Library
from paperreader.ui.window import Window


class SkillLibraryLayoutTests(unittest.TestCase):
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
        self.lib_patch.start(); self.key_patch.start()
        self.window = Window()
        self.window.toggle_skills()
        self.widget = self.window.skill_library
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.lib_patch.stop(); self.key_patch.stop()
        self.library.db.close()
        self.root_patch.stop()
        self.temporary.cleanup()

    def test_heading_is_one_line_and_editors_are_taller(self):
        title = self.widget.findChild(QLabel, "SkillLibraryTitle")
        subtitle = self.widget.findChild(QLabel, "SkillLibraryMuted")
        separator = self.widget.findChild(QLabel, "SkillLibrarySeparator")
        self.assertEqual(separator.text(), "|")
        controls = (title, separator, subtitle, self.widget.import_button,
                    self.widget.new_button)
        midlines = [control.mapTo(self.widget, control.rect().center()).y()
                    for control in controls]
        self.assertLessEqual(max(midlines) - min(midlines), 6)
        self.assertGreaterEqual(self.widget.workflow.height(), 120)
        self.assertGreaterEqual(self.widget.tabs.minimumHeight(), 260)

    def test_short_window_scroll_reaches_bottom_and_shrinks_after_fold(self):
        self.window.resize(1050, 560)
        self.widget.reload(preferred=("domain", "game"))
        self.app.processEvents()
        scroll = self.widget.detail_scroll.verticalScrollBar()
        self.assertGreater(scroll.maximum(), 0)
        before = scroll.maximum()
        scroll.setValue(before)
        self.app.processEvents()
        tab_bottom = self.widget.tabs.mapTo(self.widget.detail_scroll.viewport(),
                                            QPoint(0, self.widget.tabs.height())).y()
        self.assertLessEqual(tab_bottom, self.widget.detail_scroll.viewport().height() + 4)
        self.widget.toggle_domain_content()
        self.app.processEvents()
        self.assertLess(scroll.maximum(), before)


if __name__ == "__main__":
    unittest.main()
