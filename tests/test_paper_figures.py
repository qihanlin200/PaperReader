import unittest

from paperreader.ui.paper_figures import insert_figure_markers


class PaperFigurePlacementTests(unittest.TestCase):
    def test_figure_is_placed_beside_method_explanation_not_legend(self):
        report = ('## 标注约定\n\n图 1 展示结构，图 2 展示流程。\n\n'
                  '## 方法机制\n\n图 1 展示编码器结构和信息流。\n\n'
                  '图 2 只是被提及。')
        rendered, shown = insert_figure_markers(report, {'1': object(), '2': object()})
        self.assertEqual(shown, ['1'])
        self.assertGreater(rendered.index('PRPAPERFIGURE1END'), rendered.index('## 方法机制'))
        self.assertNotIn('PRPAPERFIGURE2END', rendered)

    def test_explicit_marker_controls_which_figures_appear(self):
        report = ('## 标注约定\n\n[[论文图:1]]\n\n'
                  '## 理论分析\n\n图 1 展示背景。\n\n'
                  '机制中的关键步骤对应图 2。\n\n[[论文图:2]]')
        rendered, shown = insert_figure_markers(report, {'1': object(), '2': object()})
        self.assertEqual(shown, ['2'])
        self.assertNotIn('PRPAPERFIGURE1END', rendered)
        self.assertNotIn('[[论文图:', rendered)
        self.assertGreater(rendered.index('PRPAPERFIGURE2END'), rendered.index('关键步骤'))

    def test_unmatched_marker_is_hidden(self):
        rendered, shown = insert_figure_markers('解释机制。\n\n[[论文图:9]]', {})
        self.assertEqual(shown, [])
        self.assertNotIn('[[论文图:', rendered)
