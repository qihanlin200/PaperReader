import json
import unittest
from paperreader.services.analysis import run_analysis, quick_context, message_length


class AnalysisTests(unittest.TestCase):
    def test_quick_context_includes_end_of_long_paper(self):
        pages = [(0, 'Intro '*2000), (1,'Method '*2000), (2,'Results '*2000), (3,'Conclusion END '*2000)]
        scope, text = quick_context(pages, 2000)
        self.assertIn('Conclusion END', text)
        self.assertLessEqual(len(text), 2000)
        self.assertIn('节选', scope)

    def test_deep_covers_every_page_with_budget_and_streams(self):
        pages = [(i, f'PAGE{i} '+('word '*1500)) for i in range(5)]
        calls = []; events = []
        def model(config, key, messages, on_chunk=None):
            self.assertLessEqual(message_length(messages), config['max_input_chars'])
            self.assertIsNotNone(on_chunk)
            calls.append(messages[-1]['content'])
            on_chunk('## 分析\n'); on_chunk('结论')
            return '## 分析\n结论'
        report = run_analysis(pages, {'model':'test','max_input_chars':4096}, '', 'deep', model, lambda x:events.append(json.loads(x)))
        for i in range(5): self.assertTrue(any(f'PAGE{i}' in call for call in calls))
        self.assertGreater(report['segments'], 1)
        self.assertIn('分段精读记录', report['text'])
        self.assertTrue(any(e['kind']=='checkpoint' for e in events))
        self.assertTrue(any(e['kind']=='text' for e in events))

    def test_blank_document_rejected(self):
        with self.assertRaises(ValueError): run_analysis([(0,'')], {}, '', 'quick', None, None)
