import json
import unittest
from paperreader.services.analysis import ModelContextLimitError, run_analysis, quick_context


class AnalysisTests(unittest.TestCase):
    def test_quick_context_includes_end_of_long_paper(self):
        pages = [(0, 'Intro '*2000), (1,'Method '*2000), (2,'Results '*2000), (3,'Conclusion END '*2000)]
        scope, text = quick_context(pages, 2000)
        self.assertIn('Conclusion END', text)
        self.assertLessEqual(len(text), 2000)
        self.assertIn('节选', scope)

    def test_deep_uses_one_request_when_full_text_fits(self):
        pages = [(i, f'PAGE{i} '+('word '*2500)) for i in range(5)]
        calls = []; events = []
        def model(config, key, messages, on_chunk=None):
            self.assertIsNotNone(on_chunk)
            content = messages[-1]['content']
            calls.append(content)
            on_chunk('# 分段报告\n逐页证据\n# 精读报告\n结论')
            return '# 分段报告\n逐页证据\n# 精读报告\n结论'
        report = run_analysis(pages, {'model':'test'}, '', 'deep', model, lambda x:events.append(json.loads(x)))
        self.assertEqual(report['segments'], 1)
        self.assertEqual(len(calls), 1)
        self.assertIn('[[论文图:1]]', calls[0])
        self.assertIn('分段报告会显示在窄栏中', calls[0])
        self.assertIn('概念比较、流程、术语、优缺点和文字证据不要排成多列表格', calls[0])
        self.assertIn('只有必须并排比较的实验数值才使用 Markdown 表格', calls[0])
        self.assertIn('```mermaid', calls[0])
        self.assertIn('节点标签简短，不要在图中写引用页码', calls[0])
        self.assertIn('C -->|是| D', calls[0])
        self.assertIn('核心知识', calls[0])
        self.assertIn('## 优点与可改进点', calls[0])
        for i in range(5): self.assertIn(f'PAGE{i}', calls[0])
        self.assertIn('分段精读记录', report['text'])
        self.assertEqual(report['report'], '结论')
        self.assertEqual(report['segments_text'], '逐页证据')
        self.assertTrue(any(e['kind']=='checkpoint' for e in events))
        self.assertTrue(any(e['kind']=='text' for e in events))
        self.assertEqual(next(e for e in events if e['kind'] == 'plan')['total'], 1)
        calls = [event for event in events if event['kind'] == 'model_call']
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(call['usage'] == {} for call in calls))

    def test_short_deep_paper_uses_one_request(self):
        pages = [(i, f'PAGE{i} ' + 'word ' * 1400) for i in range(3)]
        calls = []
        def model(config, key, messages, on_chunk=None):
            calls.append(messages[1]['content'])
            return '分析结果'
        report = run_analysis(pages, {}, '', 'deep', model, lambda _: None)
        self.assertEqual(report['segments'], 1)
        self.assertEqual(len(calls), 1)
        for i in range(3): self.assertIn(f'PAGE{i}', calls[0])

    def test_deep_falls_back_to_chunks_only_after_context_rejection(self):
        pages = [(i, f'PAGE{i} '+('word '*2500)) for i in range(5)]
        calls, events = [], []
        def model(config, key, messages, on_chunk=None):
            content = messages[-1]['content']
            calls.append(content)
            if '请一次性阅读' in content:
                raise ModelContextLimitError('输入超出上下文容量')
            if '基于这些记录综合' in content:
                return '最终报告'
            return '分段证据'
        result = run_analysis(pages, {}, '', 'deep', model,
                              lambda value: events.append(json.loads(value)))
        self.assertEqual(len(calls), 5)
        self.assertEqual(result['segments'], 3)
        self.assertEqual(result['report'], '最终报告')
        self.assertEqual(result['segments_text'].count('分段证据'), 3)
        self.assertTrue(any(event['kind'] == 'fallback' for event in events))
        self.assertEqual([event['total'] for event in events if event['kind'] == 'plan'], [1, 4])

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

    def test_v4_resume_reuses_finished_segment_and_synthesizes_both(self):
        pages = [(0, 'FIRST ' * 3500), (1, 'SECOND ' * 3500)]
        calls = []
        def model(config, key, messages, on_chunk=None):
            content = messages[1]['content']
            calls.append(content)
            return '最终报告' if '基于这些记录综合' in content else '第二页证据'
        resume = {'plan': 'v4', 'completed': [
            {'title': '全文精读 · 第 1/2 段', 'text': '第一页证据'}],
            'profile': ['old', 'test']}
        result = run_analysis(pages, {}, '', 'deep', model, lambda _: None, resume=resume)
        self.assertEqual(len(calls), 2)
        self.assertIn('SECOND', calls[0])
        self.assertNotIn('FIRST', calls[0])
        self.assertIn('第一页证据', calls[1])
        self.assertIn('第二页证据', calls[1])
        self.assertEqual(result['report'], '最终报告')
        self.assertIn('第一页证据', result['segments_text'])

    def test_v3_resume_keeps_single_call_report_format(self):
        calls = []
        def model(config, key, messages, on_chunk=None):
            calls.append(messages[1]['content'])
            return '# 精读报告\n旧报告\n# 分段报告\n旧分段'
        result = run_analysis([(0, '原文')], {}, '', 'deep', model, lambda _: None,
                              resume={'plan': 'v3', 'profile': ['old', 'test']})
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['report'], '旧报告')
        self.assertEqual(result['segments_text'], '旧分段')

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
            if '请整理以下分段证据' in content:
                return '保留页码与关键证据。'
            if '基于这些记录综合为可独立阅读的精读报告' in content:
                return '最终报告'
            return '第 1 页：' + '分析记录。' * 3500
        report = run_analysis(pages, {}, '', 'deep', model, lambda _: None,
                              resume={'plan': 'v2', 'profile': ['old', 'test']})
        self.assertTrue(any('请整理以下分段证据' in call for call in calls))
        self.assertIn('最终报告', report['text'])
        synthesis = next(call for call in calls if '基于这些记录综合为可独立阅读的精读报告' in call)
        self.assertIn('条件分支、回路、并行与汇合关系', synthesis)
        self.assertIn('## 优点与可改进点', synthesis)

    def test_legacy_segment_prompt_also_uses_narrow_layout(self):
        calls = []
        def model(config, key, messages, on_chunk=None):
            calls.append(messages[1]['content'])
            return '简短分析'
        run_analysis([(0, '正文')], {}, '', 'deep', model, lambda _: None,
                     resume={'plan': 'v2', 'profile': ['old', 'test']})
        self.assertIn('分段报告会显示在窄栏中', calls[0])
        self.assertIn('只有必须并排比较的实验数值才使用 Markdown 表格', calls[0])
