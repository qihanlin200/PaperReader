"""Initial PDF loading progress closes after visible pages render."""
import os
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import fitz
from PySide6.QtWidgets import QApplication
from paperreader.ui.pdf import ContinuousPDF


class PDFLoadingProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_long_document_progress_tracks_preparation_and_initial_render(self):
        document = fitz.open()
        for _ in range(28):
            document.new_page()
        view = ContinuousPDF()
        view.resize(500, 600)
        view.show()
        try:
            view.begin_loading()
            self.assertTrue(view.loading_panel.isVisible())
            view.load(document)
            self.assertEqual(view.loading_progress.maximum(), 0)
            self.assertTrue(view.loading_panel.isVisible())
            deadline = time.monotonic() + 3
            while view.loading_active and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.005)
            self.assertFalse(view.loading_active)
            self.assertFalse(view.loading_panel.isVisible())
            self.assertIsNotNone(view.pages[0].bitmap)
        finally:
            view.clear_document()
            view.close()
            document.close()


if __name__ == '__main__':
    unittest.main()
