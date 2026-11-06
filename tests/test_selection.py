import unittest

from paperreader.ui.selection import paragraph_words


class ParagraphSelectionTests(unittest.TestCase):
    def test_paragraphs_merged_into_one_pdf_block(self):
        for indent, gap in ((11, 0), (0, 8)):
            with self.subTest(indent=indent, gap=gap):
                lines = [
                    (60, 50, 260, "Games provide a controlled setting"),
                    (50, 64, 260, "The first paragraph continues"),
                    (50, 78, 160, "Figure 1 illustrates this role."),
                    (50 + indent, 92 + gap, 260, "This setting raises a natural question"),
                    (50, 106 + gap, 250, "The second paragraph continues"),
                ]
                # Simulate PyMuPDF assigning all five lines to block zero.
                words = [(x, y, right, y + 12, text, 0, i, 0)
                         for i, (x, y, right, text) in enumerate(lines)]
                for clicked in words[:3]:
                    self.assertEqual(paragraph_words(words, clicked), words[:3])
                for clicked in words[3:]:
                    self.assertEqual(paragraph_words(words, clicked), words[3:])

    def test_uniform_wide_line_spacing_stays_one_paragraph(self):
        words = [(50, y, 260, y + 10, f"Line {i}", 0, i, 0)
                 for i, y in enumerate((50, 68, 86, 104))]
        self.assertEqual(paragraph_words(words, words[2]), words)
