import io
import os
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QSpinBox
from paperreader.logger import configure_logging, get_logger, shutdown_logging
from paperreader.services.library import Library
from paperreader.ui.window import Window


class LoggerSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_save_export_and_model_save_keep_log_limits(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()):
            library = Library(directory)
            configure_logging(directory)
            window = Window(library=library)
            archive = str(Path(directory) / "export.zip")
            get_logger("paperreader.tests").warning("保留这一行")

            def edit(dialog):
                try:
                    size = dialog.findChild(QSpinBox, "LogSizeMb")
                    days = dialog.findChild(QSpinBox, "LogRetentionDays")
                    self.assertEqual((size.value(), days.value()), (10, 14))
                    size.setValue(4)
                    days.setValue(7)
                    next(button for button in dialog.findChildren(QPushButton)
                         if button.text() == "保存日志设置").click()
                    next(button for button in dialog.findChildren(QPushButton)
                         if button.text() == "导出全部日志").click()
                finally:
                    dialog.reject()

            try:
                with patch("paperreader.ui.settings.QFileDialog.getSaveFileName",
                           return_value=(archive, "ZIP 文件 (*.zip)")):
                    edit(window.settings())
                self.assertEqual(library.config()["log_size_mb"], 4)
                self.assertEqual(library.config()["log_retention_days"], 7)
                with zipfile.ZipFile(archive) as exported:
                    self.assertIn("保留这一行", exported.read("paperreader.log").decode())
                with patch("paperreader.ui.settings.keyring.get_password", return_value=""), \
                     patch("paperreader.ui.settings.keyring.set_password"):
                    from PySide6.QtWidgets import QDialog, QFormLayout
                    dialog = QDialog(window)
                    save = window.build_model_settings(dialog, QFormLayout(dialog))
                    save()
                self.assertEqual(library.config()["log_size_mb"], 4)
                self.assertEqual(library.config()["log_retention_days"], 7)
            finally:
                window.close()
                library.db.close()
                shutdown_logging()


if __name__ == "__main__":
    unittest.main()
