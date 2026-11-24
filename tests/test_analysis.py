import json
import unittest
from paperreader.services.analysis import run_analysis, quick_context


class AnalysisTests(unittest.TestCase):
    def test_quick_context_includes_end_of_long_paper(self):
        pages = [(0, 'Intro '*2000), (1,'Method '*2000), (2,'Results '*2000), (3,'Conclusion END '*2000)]
        scope, text = quick_context(pages, 2000)
        self.assertIn('Conclusion END', text)
        self.assertLessEqual(len(text), 2000)
        self.assertIn('节选', scope)

    def test_deep_sends_full_paper_once_and_splits_two_views(self):
        pages = [(i, f'PAGE{i} '+('word '*2500)) for i in range(5)]
        calls = []; events = []
        def model(config, key, messages, on_chunk=None):
            self.assertIsNotNone(on_chunk)
            calls.append(messages[-1]['content'])
            on_chunk('# 精读报告\n'); on_chunk('结论\n# 分段报告\n逐页证据')
            return '# 精读报告\n结论\n# 分段报告\n逐页证据'
        report = run_analysis(pages, {'model':'test'}, '', 'deep', model, lambda x:events.append(json.loads(x)))
        self.assertEqual(report['segments'], 1)
        self.assertEqual(len(calls), 1)
        self.assertIn('[[论文图:1]]', calls[0])
        self.assertIn('分段报告会显示在窄栏中', calls[0])
        self.assertIn('概念比较、流程、术语、优缺点和文字证据不要排成多列表格', calls[0])
        self.assertIn('只有必须并排比较的实验数值才使用 Markdown 表格', calls[0])
        self.assertIn('```paperreader-flow', calls[0])
        self.assertIn('每步都标原文页码', calls[0])
        for i in range(5): self.assertIn(f'PAGE{i}', calls[0])
        self.assertIn('分段精读记录', report['text'])
        self.assertEqual(report['report'], '结论')
        self.assertEqual(report['segments_text'], '逐页证据')
        self.assertTrue(any(e['kind']=='checkpoint' for e in events))
        self.assertTrue(any(e['kind']=='text' for e in events))
        calls = [event for event in events if event['kind'] == 'model_call']
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['usage'], {})

    def test_short_deep_paper_is_read_in_one_full_text_pass(self):
        pages = [(i, f'PAGE{i} ' + 'word ' * 1400) for i in range(3)]
        calls = []
        def model(config, key, messages, on_chunk=None):
            calls.append(messages[1]['content'])
            return '分析结果'
        report = run_analysis(pages, {}, '', 'deep', model, lambda _: None)
        self.assertEqual(report['segments'], 1)
        for i in range(3): self.assertIn(f'PAGE{i}', calls[0])

    def test_blank_document_rejected(self):
        with self.assertRaises(ValueError): run_analysis([(0,'')], {}, '', 'quick', None, None)

    def test_quick_reads_selected_pages_and_requests_a_decision(self):
        pages = [(i, 'Body ' * 2000) for i in range(12)]
        pages[5] = (5, 'Results\n' + 'score ' * 2000)
        pages[-1] = (11, 'Conclusion\n' + 'ending ' * 2000)
        calls = []
        def model(config, key, messages, on_chunk=None):
            calls.append(messages[1]['content'])
            return '摘要'
        run_analysis(pages, {}, '', 'quick', model, lambda _: None)
        self.assertIn('第 6 页', calls[0])
        self.assertIn('第 12 页', calls[0])
        self.assertIn('阅读建议', calls[0])
        self.assertNotIn('第 4 页', calls[0])

    def test_resume_deep_reuses_completed_model_calls(self):
        pages = [(0, "FIRST " * 380), (1, "SECOND " * 330)]
        calls = []
        def model(config, key, messages, on_chunk=None):
            calls.append(messages)
            return "续读结果"
        cached = {"completed": [{"title": "已完成段落", "text": "第一段分析"}],
                  "partial": "第二段开头。", "profile": ["old", "test", 4096]}
        report = run_analysis(pages, {}, "", "deep", model, lambda _: None,
                              resume=cached)
        self.assertIn("SECOND", calls[0][1]["content"])
        self.assertEqual(calls[0][-2]["content"], "第二段开头。")
        self.assertIn("第一段分析", report["text"])
        self.assertIn("第二段开头。续读结果", report["text"])

    def test_old_full_text_checkpoint_keeps_its_original_stage(self):
        pages = [(i, f'PAGE{i} ' + 'word ' * 4500) for i in range(3)]
        calls = []
        def model(config, key, messages, on_chunk=None):
            calls.append(messages[1]['content'])
            return '总报告'
        cached = {'completed': [{'title': '全文精读 · 第 1/1 段', 'text': '旧分析'}],
                  'profile': ['old', 'test']}
        report = run_analysis(pages, {}, '', 'deep', model, lambda _: None, resume=cached)
        self.assertEqual(report['segments'], 1)
        self.assertEqual(len(calls), 1)
        self.assertIn('旧分析', calls[0])

    def test_legacy_long_deep_notes_are_reduced_before_final_report(self):
        pages = [(i, 'paper text ' * 1800) for i in range(4)]
        calls = []
        def model(config, key, messages, on_chunk=None):
            content = messages[1]['content']
            calls.append(content)
            if '请压缩以下精读记录' in content:
                return '保留页码与关键证据。'
            if '综合为可独立阅读的精读报告' in content:
                return '最终报告'
            return '第 1 页：' + '分析记录。' * 3500
        report = run_analysis(pages, {}, '', 'deep', model, lambda _: None,
                              resume={'plan': 'v2', 'profile': ['old', 'test']})
        self.assertTrue(any('请压缩以下精读记录' in call for call in calls))
        self.assertIn('最终报告', report['text'])

    def test_legacy_segment_prompt_also_uses_narrow_layout(self):
        calls = []
        def model(config, key, messages, on_chunk=None):
            calls.append(messages[1]['content'])
            return '简短分析'
        run_analysis([(0, '正文')], {}, '', 'deep', model, lambda _: None,
                     resume={'plan': 'v2', 'profile': ['old', 'test']})
        self.assertIn('分段报告会显示在窄栏中', calls[0])
        self.assertIn('只有必须并排比较的实验数值才使用 Markdown 表格', calls[0])
