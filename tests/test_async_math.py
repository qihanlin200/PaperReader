"""A slow formula engine must not block selection or overwrite newer content."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading
import time
import unittest
from unittest.mock import patch
from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from paperreader.ui.markdown import MarkdownBrowser


class AsyncMathTests(unittest.TestCase):
    def test_report_formula_code_spans_render_after_async_result(self):
        app = QApplication.instance() or QApplication([])
        browser = MarkdownBrowser(reading_style=True)
        browser.async_math = True
        image = QImage(20, 20, QImage.Format.Format_ARGB32)
        image.fill(0)
        try:
            with patch('paperreader.ui.markdown.render_formula', return_value=image):
                browser.set_markdown('目标函数：`h* = arg max_{h∈H_T} E_{x~X_T}[R_T(x)]`')
                deadline = time.monotonic() + 2
                while not browser.math_resources and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(.005)
            self.assertEqual(len(browser.math_resources), 1)
            self.assertIn('h^{*}', next(iter(browser.math_sources.values())))
        finally:
            browser.close()

    def test_slow_formula_keeps_event_loop_responsive_and_current_text(self):
        app = QApplication.instance() or QApplication([])
        browser = MarkdownBrowser()
        browser.async_math = True
        entered, release = threading.Event(), threading.Event()
        image = QImage(20, 20, QImage.Format.Format_ARGB32)
        image.fill(0)
        def slow_formula(source, font_px=13, max_width=None):
            entered.set()
            release.wait(3)
            return image
        try:
            with patch('paperreader.ui.markdown.render_formula', side_effect=slow_formula):
                browser.set_markdown(r'First paper \(x^2\)')
                self.assertTrue(entered.wait(2))
                ticks = []
                QTimer.singleShot(0, lambda: ticks.append(True))
                app.processEvents()
                self.assertTrue(ticks)
                self.assertFalse(browser.math_resources)
                browser.set_markdown('Second paper')
                release.set()
                deadline = time.monotonic() + 3
                while browser._math_running and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(.005)
                self.assertFalse(browser._math_running)
                self.assertEqual(browser.toPlainText(), 'Second paper')
                browser.set_markdown(r'Cached \(x^2\)')
                self.assertTrue(browser.math_resources)
        finally:
            release.set()
            browser.close()
