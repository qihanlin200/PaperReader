import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import re
import unittest
from PySide6.QtWidgets import QApplication
from paperreader.ui.math_render import markdown_html
from paperreader.ui.markdown import MarkdownBrowser
from paperreader.ui.flowchart import parse_flow


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

    def test_display_formula_with_equation_tag(self):
        resources, sources = {}, {}
        formula = (r'\[' '\n'
                   r'U=w_{\text{score}}p_{\text{score}}' '\n'
                   r'+w_{\text{cost}}\left(1-\min(1,p_{\text{cost}}/\$10)\right)' '\n'
                   r'+w_{\text{time}}\left(1-\min(1,p_{\text{time}}/300\,\text{s})\right)' '\n'
                   r'\tag{1}' '\n'
                   r'\]')
        result = markdown_html('基础效用：\n\n' + formula, resources, sources)
        self.assertEqual(result.count('<img'), 1)
        self.assertEqual(len(resources), 1)
        self.assertIn(r'\tag{1}', next(iter(sources.values())))
        self.assertNotIn(r'\tag{1}', result.split('alt=')[0])

    def test_long_display_formula_wraps_without_shrinking(self):
        resources, sources = {}, {}
        formula = (r'\[' '\n'
                   r'U=w_{\text{score}}p_{\text{score}}' '\n'
                   r'+w_{\text{cost}}\left(1-\min(1,p_{\text{cost}}/\$10)\right)' '\n'
                   r'+w_{\text{time}}\left(1-\min(1,p_{\text{time}}/300\,\text{s})\right)' '\n'
                   r'\tag{1}' '\n'
                   r'\]')
        result = markdown_html(formula, resources, sources, width=320)
        image = next(iter(resources.values()))
        self.assertLessEqual(image.width() / 2, 320)
        self.assertGreater(image.height() / 2, 40)
        self.assertIn(f'width="{image.width() / 2:.0f}"', result)

    def test_multiline_cases_formula_and_common_math_aliases(self):
        from paperreader.ui.math_render import render_formula
        resources, sources = {}, {}
        formula = (r'\[' '\n' r'U_{\text{final}}=' '\n'
                   r'\begin{cases}' '\n'
                   r'U(1-\tau), & \text{若超时}\\' '\n'
                   r'U, & \text{否则}' '\n'
                   r'\end{cases}' '\n' r'\tag{2}' '\n' r'\]')
        rendered = markdown_html(formula, resources, sources)
        self.assertEqual(rendered.count('<img'), 1)
        self.assertGreater(next(iter(resources.values())).height(), 60)
        for source in (r'\mathrm{LayerNorm}\bigl(x\bigr)', r'\mathcal M',
                       r'n\in\mathbb N', r'A_{\le i}',
                       r'R_s=\frac{R_s^{(1)}+R_s^{(2)}}2'):
            self.assertFalse(render_formula(source).isNull(), source)

    def test_multiline_formula_inside_list_is_preserved_and_rendered(self):
        source = (
            '- 经济指标：对方法 \\(m\\)、种子 \\(s\\) 的均值为\n'
            '  \\[\n'
            '  \\hat M_{m,s}(r)=\\frac{1}{N_{m,s}}\\sum_{i=1}^{N_{m,s}}\\tilde M_i(r),\\qquad\n'
            '  \\tilde M_i(r)=\\begin{cases}\n'
            '  M_i(r), & \\text{到达第 }r\\text{ 轮},\\\\\n'
            '  0, & \\text{否则}.\n'
            '  \\end{cases}\n'
            '  \\]\n'
            '  原文依据：第15页。'
        )
        resources = {}
        html = markdown_html(source, resources, {}, width=480)
        visible_html = re.sub(r'<img\b[^>]*>', '', html)
        self.assertNotIn(r'\begin{cases}', visible_html)
        self.assertNotIn(r'\hat M', visible_html)
        self.assertEqual(html.count('<img'), 3)
        view = MarkdownBrowser(reading_style=True)
        try:
            view.set_markdown(source)
            block = view.document().begin()
            inline_block = None
            while block.isValid():
                if '经济指标' in block.text():
                    inline_block = block
                    break
                block = block.next()
            self.assertIsNotNone(inline_block)
            self.assertIn('\ufffc', inline_block.text())
            self.assertEqual(inline_block.blockFormat().lineHeight(), 150)
            self.assertEqual(inline_block.blockFormat().bottomMargin(), 6)
        finally:
            view.close()

    def test_code_currency_and_incomplete_input_stay_text(self):
        resources, sources = {}, {}
        result = markdown_html('`$x^2$`\n\n```python\n"$a_b$"\n```\n\nCosts $10 and $20.\n\n\\[unfinished', resources, sources)
        self.assertFalse(resources)
        self.assertIn('$10', result)

    def test_escaped_standalone_equations_render_without_delimiters(self):
        source = (
            '- h\\* = arg max\\_{h∈H_T} E\\_{x\\~X_T, τ\\~p\\_{W_T,π_φ,h}(·|x)}[R_T(τ,x)]\n'
            '- 固定 seed 下，完整状态转移：s̃\\_{t+1}=F_ρ(s̃_t,a_t)；\n'
            '- p_ρ(o\\_{t+1}|η_t,a_t)=Σ\\_{s̃∈S} p_ρ(s̃_t=s̃|η_t)·𝟙[o_{t+1}=Ω(F_ρ(s̃,a_t))]\n'
            '- {h^{(t+1,j)}}\\_{j=1}^{k_t} ← P(I_t)；\n'
            '- D\\_{t+1}=D_t ∪ {EvalDir(h^{(t+1,j)})}\\_{j=1}^{k_t}\n'
            '- API_KEY = value\n'
            '```text\nh\\* = raw\\_text\n```'
        )
        resources, sources = {}, {}
        result = markdown_html(source, resources, sources)
        self.assertEqual(len(resources), 5)
        self.assertTrue(all(not image.isNull() for image in resources.values()))
        self.assertIn('h^{*}', next(iter(sources.values())))
        self.assertTrue(any(r'\{h^{(t+1,j)}\}' in math for math in sources.values()))
        self.assertIn('API_KEY = value', result)
        self.assertIn('h\\* = raw\\_text', result)

    def test_report_equations_in_inline_code_are_typeset(self):
        source = (
            '- 目标函数（第3页）：`h* = arg max_{h∈H_T} E_{x~X_T, τ~p_{W_T,π_φ,h}(·|x)}[R_T(τ,x)]`\n'
            '- 固定 seed 下：`s̃_{t+1}=F_ρ(s̃_t,a_t)`；\n'
            '- `p_ρ(o_{t+1}|η_t,a_t)=Σ_{s̃∈S} p_ρ(s̃_t=s̃|η_t)·1[o_{t+1}=Ω(F_ρ(s̃,a_t))]`。\n'
            '- `API_KEY = value` 保持代码。'
        )
        resources, sources = {}, {}
        result = markdown_html(source, resources, sources)
        self.assertEqual(len(resources), 3)
        self.assertEqual(result.count('paperreader-math:'), 3)
        self.assertIn('API_KEY = value</span>', result)
        self.assertTrue(any('h^{*}' in math for math in sources.values()))

    def test_research_flow_block_renders_as_narrow_diagram(self):
        source = ('## 研究流程图\n\n```paperreader-flow\n'
                  '任务输入 | 给出原始任务和约束（第2页）\n'
                  '候选生成 | 生成可执行方案（第3页）\n'
                  '评估反馈 | 按奖励筛选，再回到候选生成（第4页）\n'
                  '```\n\n后续分析。')
        resources = {}
        result = markdown_html(source, resources, {}, width=320)
        self.assertIn('<img src="paperreader-flow:', result)
        self.assertNotIn('<table', result)
        self.assertEqual(len(resources), 1)
        self.assertLessEqual(next(iter(resources.values())).width() / 2, 320)
        self.assertNotIn('<pre', result)
        self.assertIn('后续分析', result)
        from paperreader.ui.math_render import _flow_plain_text
        self.assertEqual(_flow_plain_text(r'模板 \(W_{\text{temp}}\)'), '模板 W₍temp₎')
        view = MarkdownBrowser(reading_style=True)
        view.resize(340, 500)
        view.set_markdown(source)
        view.show()
        self.app.processEvents()
        self.assertLessEqual(view.document().size().width(), view.viewport().width())
        view.close()
        invalid = markdown_html('```paperreader-flow\nA | one\nB | two\n```', {}, {})
        self.assertIn('A | one', invalid)
        unsafe = markdown_html('```paperreader-flow\nA | <script>\nB | b\nC | c\n```', {}, {})
        self.assertIn('&lt;script&gt;', unsafe)

    def test_research_flow_accepts_windows_lines_and_connector_arrows(self):
        steps = [f'步骤{i} | 执行并核对第{i}步的结果（第{i}页）'
                 for i in range(1, 9)]
        source = ('```paperreader-flow\n' + '\n↓\n'.join(steps)
                  + '\n```\n\n后续内容').replace('\n', '\r\n')
        resources = {}
        result = markdown_html(source, resources, {}, width=360)
        self.assertIn('<img src="paperreader-flow:', result)
        self.assertNotIn('<pre', result)
        self.assertEqual(len(resources), 1)
        self.assertIn('后续内容', result)

    def test_research_flow_accepts_fifty_nodes(self):
        steps = '\n'.join(f'步骤{i} | 执行步骤{i}' for i in range(1, 51))
        resources = {}
        result = markdown_html(f'```paperreader-flow\n{steps}\n```', resources, {}, width=260)
        self.assertIn('<img src="paperreader-flow:', result)
        self.assertEqual(len(resources), 1)
        too_many = markdown_html(f'```paperreader-flow\n{steps}\n步骤51 | 额外一步\n```', {}, {})
        self.assertIn('步骤51', too_many)

    def test_structured_flow_renders_branches_loops_and_merge(self):
        source = ('```paperreader-flow\n'
                  'N1 | start | 开始 | 接收研究任务（第1页）\n'
                  'N2 | input | 输入 | 收集数据（第2页）\n'
                  'N3 | decision | 条件判断 | 数据是否足够（第3页）\n'
                  'N4 | process | 补充数据 | 继续收集（第3页）\n'
                  'N5 | parallel | 并行实验 | 启动两项实验（第4页）\n'
                  'N6 | data | 实验记录 | 保存结果（第5页）\n'
                  'N7 | merge | 汇合 | 汇总结果（第6页）\n'
                  'N8 | end | 结束 | 得到结论（第7页）\n'
                  'N1 -> N2\nN2 -> N3\n'
                  'N3 -[否]-> N4\nN4 -[重试]-> N2\n'
                  'N3 -[是]-> N5\nN5 -> N6\nN6 -> N7\nN7 -> N8\n'
                  '```')
        parsed = parse_flow(source.removeprefix('```paperreader-flow\n').removesuffix('\n```'))
        self.assertEqual(len(parsed[0]), 8)
        self.assertIn(('N4', 'N2', '重试'), parsed[1])
        resources = {}
        result = markdown_html(source.replace('\n', '\r\n'), resources, {}, width=340)
        self.assertIn('<img src="paperreader-flow:', result)
        self.assertNotIn('<pre', result)
        self.assertEqual(len(resources), 1)
        self.assertLessEqual(next(iter(resources.values())).width() / 2, 340)

    def test_structured_flow_rejects_undefined_connection(self):
        source = ('N1 | start | 开始 | 输入\n'
                  'N2 | process | 操作 | 处理\n'
                  'N3 | end | 完成 | 输出\n'
                  'N1 -> N2\nN2 -> N4')
        self.assertIsNone(parse_flow(source))

    def test_structured_flow_accepts_fifty_nodes(self):
        nodes = ['N1 | start | 开始 | 开始（第1页）']
        nodes += [f'N{i} | process | 步骤{i} | 执行（第{i}页）' for i in range(2, 50)]
        nodes.append('N50 | end | 完成 | 得到结果（第50页）')
        edges = [f'N{i} -> N{i + 1}' for i in range(1, 50)]
        source = '\n'.join(nodes + edges)
        self.assertEqual(len(parse_flow(source)[0]), 50)
        resources = {}
        result = markdown_html(f'```paperreader-flow\n{source}\n```', resources, {}, width=260)
        self.assertIn('<img src="paperreader-flow:', result)
        self.assertEqual(len(resources), 1)

    def test_analysis_heading_paragraph_and_list_share_line_spacing(self):
        view = MarkdownBrowser(reading_style=True)
        try:
            view.set_markdown('## 章节\n\n普通段落第一行。\n普通段落第二行。\n\n- 列表第一项\n- 列表第二项')
            blocks = []
            block = view.document().begin()
            while block.isValid():
                if block.text().strip():
                    blocks.append(block)
                block = block.next()
            self.assertGreaterEqual(len(blocks), 3)
            self.assertEqual({block.blockFormat().lineHeight() for block in blocks}, {150})
            self.assertEqual({block.blockFormat().bottomMargin() for block in blocks}, {6})
        finally:
            view.close()

    def test_resources_are_local_only(self):
        view = MarkdownBrowser()
        view.set_markdown(r'## Formula\n\n\(x_i^2\)')
        self.assertEqual(len(view.math_resources), 1)
        from PySide6.QtCore import QUrl
        self.assertIsNone(view.loadResource(2, QUrl('https://example.org/a.png')))
        key = next(iter(view.math_resources))
        self.assertIsNotNone(view.loadResource(2, QUrl(key)))

    def test_inline_formula_uses_matching_body_font_size(self):
        reading = MarkdownBrowser(reading_style=True)
        standard = MarkdownBrowser()
        for view in (reading, standard):
            view.set_markdown(r'正文 \(x_i^2\)')
        reading_image = next(iter(reading.math_resources.values()))
        standard_image = next(iter(standard.math_resources.values()))
        self.assertLess(reading_image.height(), standard_image.height())

    def test_bold_cjk_evidence_label_next_to_text(self):
        rendered = markdown_html('**【推断】**实验说明。\n\n`**【事实】**原样`', {}, {})
        self.assertIn('font-weight:700;">【推断】</span>实验说明', rendered)
        self.assertNotIn('**【推断】**实验说明', rendered)
        self.assertIn('**【事实】**原样', rendered)

    def test_mermaid_block_uses_rendered_resource(self):
        from PySide6.QtGui import QImage
        image = QImage(400, 200, QImage.Format.Format_ARGB32)
        image.fill(0)
        image.setDevicePixelRatio(2)
        resources = {}
        source = '```mermaid\nflowchart TD\nA([开始]) --> B{判断}\n```'
        result = markdown_html(source, resources, {}, width=180,
                               mermaid_renderer=lambda code: image)
        self.assertIn('paperreader-mermaid:', result)
        self.assertIn('width="180"', result)
        self.assertEqual(len(resources), 1)
        self.assertNotIn('flowchart TD', result)

    def test_mermaid_pending_and_unsafe_config(self):
        source = '```mermaid\nflowchart TD\nA --> B\n```'
        def pending(_): raise LookupError()
        self.assertIn('正在渲染流程图', markdown_html(
            source, {}, {}, mermaid_renderer=pending))
        self.assertIn('%%{init', markdown_html(
            '```mermaid\n%%{init: {}}%%\nflowchart TD\nA --> B\n```', {}, {},
            mermaid_renderer=lambda _: self.fail('unsafe config rendered')))
        oversized = '```mermaid\nflowchart TD\n' + '\n'.join(
            f'N{i}[节点{i}]' for i in range(51)) + '\n```'
        self.assertIn('N50', markdown_html(oversized, {}, {},
            mermaid_renderer=lambda _: self.fail('oversized graph rendered')))

    def test_mermaid_hides_page_citations_in_diagram(self):
        seen = []
        def pending(source):
            seen.append(source)
            raise LookupError()
        markdown_html('```mermaid\nflowchart TD\nA[处理（第3页）] --> B[结果 第4页]\n```',
                      {}, {}, mermaid_renderer=pending)
        self.assertEqual(seen, ['flowchart TD\nA[处理] --> B[结果]'])


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
