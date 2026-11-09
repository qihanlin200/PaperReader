import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from PySide6.QtWidgets import QApplication
from paperreader.ui.math_render import markdown_html
from paperreader.ui.markdown import MarkdownBrowser


class MathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def test_common_delimiters_and_currency(self):
        resources, sources = {}, {}
        source = r'\[U=w_{score}p_{score}+w_{cost}\left(1-\min(1,p_{cost}/\$10)\right)\] and \(\tau=0.5\), $x^2$ and $$\frac{a}{b}$$'
        result = markdown_html(source, resources, sources)
        self.assertEqual(len(resources), 4)
        self.assertEqual(result.count('<img'), 4)
        self.assertTrue(all(not image.isNull() for image in resources.values()))

    def test_code_currency_and_incomplete_input_stay_text(self):
        resources, sources = {}, {}
        result = markdown_html('`$x^2$`\n\n```python\n"$a_b$"\n```\n\nCosts $10 and $20.\n\n\\[unfinished', resources, sources)
        self.assertFalse(resources)
        self.assertIn('$10', result)

    def test_resources_are_local_only(self):
        view = MarkdownBrowser()
        view.set_markdown(r'## Formula\n\n\(x_i^2\)')
        self.assertEqual(len(view.math_resources), 1)
        from PySide6.QtCore import QUrl
        self.assertIsNone(view.loadResource(2, QUrl('https://example.org/a.png')))
        key = next(iter(view.math_resources))
        self.assertIsNotNone(view.loadResource(2, QUrl(key)))

    def test_bold_cjk_evidence_label_next_to_text(self):
        rendered = markdown_html('**【推断】**实验说明。\n\n`**【事实】**原样`', {}, {})
        self.assertIn('font-weight:700;">【推断】</span>实验说明', rendered)
        self.assertNotIn('**【推断】**实验说明', rendered)
        self.assertIn('**【事实】**原样', rendered)


    def test_formula_transparent_background_and_table_alignment(self):
        from paperreader.ui.math_render import render_formula
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QTextTable
        image = render_formula(r"x_i^2 + \tau")
        self.assertTrue(image.hasAlphaChannel())
        self.assertTrue(any(image.pixelColor(x, 0).alpha() == 0 for x in range(image.width())))
        view = MarkdownBrowser()
        view.set_markdown('| Name | Value |\n| ---: | ---: |\n| foo | 12 |')
        table = next(f for f in view.document().rootFrame().childFrames() if isinstance(f, QTextTable))
        self.assertTrue(table.format().alignment() & Qt.AlignmentFlag.AlignLeft)
        self.assertTrue(table.cellAt(1,1).firstCursorPosition().blockFormat().alignment() & Qt.AlignmentFlag.AlignLeft)
        self.assertEqual(table.cellAt(1,1).format().background().color().name(), '#101824')
