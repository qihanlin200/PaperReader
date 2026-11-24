import tempfile
import unittest
import fitz
from paperreader.services.titles import paper_title
from paperreader.services.library import Library


class TitleTests(unittest.TestCase):
    def test_metadata_and_first_page(self):
        doc = fitz.open(); page = doc.new_page()
        page.insert_text((70, 80), 'A Real Paper Title', fontsize=22)
        page.insert_text((70, 120), 'Author name', fontsize=10)
        self.assertEqual(paper_title(doc, '2504.15228'), 'A Real Paper Title')
        doc.set_metadata({'title': 'Embedded\nPaper Title'})
        self.assertEqual(paper_title(doc), 'Embedded Paper Title')
        doc.close()

    def test_old_number_title_migration_preserves_notes(self):
        with tempfile.TemporaryDirectory() as root:
            lib = Library(root); doc = fitz.open()
            doc.new_page().insert_text((72, 80), 'Recovered Title', fontsize=20)
            paper = lib.import_pdf(doc.tobytes(), '2504.15228'); doc.close()
            paper['title'] = '2504.15228'; paper['notes'] = 'keep notes'; lib.save(paper)
            restored = lib.all()[0]
            self.assertEqual(restored['title'], 'Recovered Title')
            self.assertEqual(restored['notes'], 'keep notes')
            lib.db.close()

    def test_split_span_title_repair_preserves_manual_titles_and_notes(self):
        with tempfile.TemporaryDirectory() as root:
            lib = Library(root)
            doc = fitz.open()
            doc.new_page().insert_text((72, 80), 'AUTOMATED DESIGN OF AGENTIC SYSTEMS', fontsize=20)
            paper = lib.import_pdf(doc.tobytes(), '2408.08435')
            doc.close()
            paper['title'] = 'A UTOMATED D ESIGN OF A GENTIC S YSTEMS'
            paper['notes'] = 'do not change'
            lib.save(paper)
            restored = lib.get(paper['id'])
            self.assertEqual(restored['title'], 'AUTOMATED DESIGN OF AGENTIC SYSTEMS')
            self.assertEqual(restored['notes'], 'do not change')
            restored['title'] = 'A STUDY OF A SYSTEM'
            lib.save(restored)
            self.assertEqual(lib.get(paper['id'])['title'], 'A STUDY OF A SYSTEM')
            lib.db.close()
