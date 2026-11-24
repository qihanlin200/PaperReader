import os
import tempfile
import time
import unittest
from threading import Event
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PySide6.QtWidgets import QApplication
from paperreader.services.library import Library
from paperreader.ui.breathing import AnalysisBreathingFrame
from paperreader.ui.theme import apply_theme
from paperreader.ui.window import Window


class AnalysisBreathingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_theme_color_and_animation_stop(self):
        frame = AnalysisBreathingFrame()
        frame.resize(240, 100)
        try:
            apply_theme("dark")
            frame.show()
            frame.set_active(True)
            frame.animation.setCurrentTime(1100)
            self.app.processEvents()
            self.assertEqual(frame.animation.state(), frame.animation.State.Running)
            dark_border = frame.grab().toImage().pixelColor(3, 50).name()
            apply_theme("naruto")
            frame.update()
            self.app.processEvents()
            self.assertNotEqual(frame.grab().toImage().pixelColor(3, 50).name(), dark_border)
            frame.set_active(False)
            self.assertEqual(frame.animation.state(), frame.animation.State.Stopped)
        finally:
            frame.close()
            apply_theme("dark")

    def test_reading_analysis_pulses_only_while_running(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Library(directory)
            with fitz.open() as doc:
                doc.new_page().insert_text((72, 72), "Paper text")
                paper = library.import_pdf(doc.tobytes(), "Test paper")
            window = Window(library=library)
            release = Event()

            def analyze(*args, **kwargs):
                release.wait(2)
                return {"scope": "全文", "text": "分析结果", "segments": []}

            try:
                window.reload(paper["id"])
                window.show()
                with patch("paperreader.ui.window.keyring.get_password", return_value="key"), \
                     patch("paperreader.ui.window.run_analysis", side_effect=analyze):
                    window.analyze()
                    self.assertTrue(window.analysis_frame.active)
                    self.assertEqual(window.analysis_frame.animation.state(),
                                     window.analysis_frame.animation.State.Running)
                    window.analysis_mode.setCurrentIndex(1)
                    self.assertFalse(window.analysis_frame.active)
                    window.analysis_mode.setCurrentIndex(0)
                    self.assertTrue(window.analysis_frame.active)
                    release.set()
                    deadline = time.monotonic() + 3
                    while window.busy and time.monotonic() < deadline:
                        self.app.processEvents()
                        time.sleep(.005)
                    self.app.processEvents()
                self.assertFalse(window.busy)
                self.assertFalse(window.analysis_frame.active)
                self.assertEqual(window.analysis_frame.animation.state(),
                                 window.analysis_frame.animation.State.Stopped)
            finally:
                release.set()
                window.close()
                library.db.close()


if __name__ == "__main__":
    unittest.main()
