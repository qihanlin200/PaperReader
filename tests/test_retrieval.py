import unittest
import fitz
from paperreader.services.retrieval import Passage, PassageIndex


class RetrievalTests(unittest.TestCase):
    def test_chinese_passage_ranking_and_pdf_selection(self):
        with fitz.open() as doc:
            doc.new_page().insert_text((72, 80), "本文介绍研究背景", fontname="china-s")
            doc.new_page().insert_text((72, 300), "训练语料包含多种语言", fontname="china-s")
            index = PassageIndex(doc)
        context, sources = index.context("训练语料有哪些", 256)
        self.assertEqual(sources["E1"]["page"], 1)
        self.assertIn("训练语料", context)
        self.assertLessEqual(len(context), 256)

        selection = Passage(0, "本文", ((72, 65, 92, 80),))
        context, sources = index.context("训练语料有哪些", 256, selection=selection)
        self.assertTrue(context.startswith("【E1】第 1 页（用户手动选区）\n本文"))
        self.assertEqual(sources["E1"]["rects"], selection.rects)

    def test_no_match_does_not_attach_first_page(self):
        with fitz.open() as doc:
            doc.new_page().insert_text((72, 80), "Paper title and author names.")
            doc.new_page().insert_text((72, 80), "Ablation results.")
            index = PassageIndex(doc)
        self.assertEqual(index.context("你是谁", 1000), ("", {}))
        context, sources = index.context("消融实验", 1000)
        self.assertEqual(set(sources), {"E1"})
        self.assertIn("Ablation results", context)
