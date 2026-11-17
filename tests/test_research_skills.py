"""Focused checks for research skill selection and semantic layout safety."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from paperreader.research_agent.answer_layout import generate_answer_layout, validate_layout
from paperreader.research_agent.domain_registry import discover_domain_skills, load_domain_skill
from paperreader.research_agent.nodes.evaluate import evaluate_node
from paperreader.research_agent.nodes.intent import intent_node
from paperreader.research_agent.nodes.plan import plan_node
from paperreader.research_agent.nodes.subtask import subtask_node
from paperreader.research_agent.nodes.summarize import summarize_node
from paperreader.research_agent.operations import RunLimit, answer_question
from paperreader.research_agent.skills import POSTPROCESS_SKILLS, SKILLS, WORKFLOW_SKILLS, should_layout
from paperreader.research_agent.workflow import execute
from paperreader.ui.research import ResearchWorkspace


class ResearchSkillTests(unittest.TestCase):
    def classify(self, question, decision, sources=(), *, academic=False, history=""):
        state = {"phase": "规划", "tasks": []}
        events = []
        result = intent_node(None, run={"question": question, "history": history, "academic": academic},
                             state=state, publish=lambda phase: events.append(phase),
                             emit=lambda *args: None, call=lambda *args: json.dumps(decision),
                             sources=list(sources))
        return result, state

    def test_library_question_uses_bounded_library_skill(self):
        sources = [{"id": "paper-1", "title": "第一篇文章"}]
        result, state = self.classify(
            "知识库里这篇文章的结论是什么？",
            {"mode": "chat", "source": "model", "skill": "", "documents": [1]}, sources)
        self.assertEqual(result["route"], "skill")
        self.assertEqual(state["mode"], "lookup")
        self.assertEqual(state["source"], "library")
        self.assertEqual(state["skill"], "library_qa")
        self.assertEqual(state["documents"], ["paper-1"])
        self.assertIn("知识库原文", SKILLS[state["skill"]].prompt)

    def test_library_comparison_requires_two_articles(self):
        sources = [{"id": str(i), "title": f"文章 {i}"} for i in range(2)]
        result, state = self.classify(
            "知识库这两篇文章有什么区别？",
            {"mode": "lookup", "source": "library", "skill": "library_qa",
             "documents": [1, 2]}, sources)
        self.assertEqual(result["route"], "skill")
        self.assertEqual(state["mode"], "research")
        self.assertEqual(state["skill"], "literature_compare")
        self.assertIn("逐篇取证", SKILLS[state["skill"]].description)

    def test_comparison_without_articles_asks_for_sources(self):
        result, _ = self.classify(
            "比较两篇论文", {"mode": "research", "source": "academic",
                       "skill": "literature_compare", "documents": []})
        self.assertEqual(result["route"], "end")
        self.assertEqual(result["result"][0], "等待补充")

    def test_empty_state_still_classifies(self):
        state = {}
        result = intent_node(None, run={"question": "你好", "history": ""}, state=state,
                             publish=lambda _: None, emit=lambda *args: None,
                             call=lambda *args: '{"mode":"chat","source":"model"}', sources=[])
        self.assertEqual(result["route"], "skill")
        self.assertEqual(state["mode"], "chat")

    def test_domain_skill_does_not_turn_simple_game_question_into_research(self):
        _, state = self.classify("幻影刺客的幻影突袭怎么释放？", {
            "intent": "ordinary", "mode": "chat", "source": "model", "domain_skills": ["game"]})
        self.assertEqual(state["mode"], "chat")
        self.assertEqual(state["presentation_skill"], "")
        self.assertFalse(ResearchWorkspace.is_research({"workflow": state}))
        self.assertEqual(state["domain_skills"], ["game"])

    def test_specific_hero_strategy_uses_task_intent_not_keyword(self):
        _, research = self.classify("如何玩好幻影刺客？", {
            "intent": "research", "mode": "chat", "source": "web", "domain_skills": ["game"]})
        _, ordinary = self.classify("如何玩好幻影刺客？只给我一句入门建议。", {
            "intent": "ordinary", "mode": "chat", "source": "model", "domain_skills": ["game"]})
        self.assertEqual(research["mode"], "research")
        self.assertEqual(research["presentation_skill"], "research_card")
        self.assertEqual(ordinary["mode"], "chat")
        self.assertEqual(ordinary["presentation_skill"], "")

    def test_game_research_loads_card_independently_of_domain(self):
        _, state = self.classify("分析 Dota 三号位的对线问题并设计解决方案", {
            "intent": "research", "mode": "chat", "source": "model", "domain_skills": ["game"]})
        self.assertEqual(state["mode"], "research")
        self.assertEqual(state["presentation_skill"], "research_card")
        self.assertTrue(ResearchWorkspace.is_research({"workflow": state}))
        self.assertIn("研究目标", WORKFLOW_SKILLS["research_card"].description)

    def test_research_followup_and_ordinary_followup_have_different_presentation(self):
        history = "问：如何实现 Agent 自进化\n答：已完成研究结论"
        _, ordinary = self.classify("其中的评估协议是什么意思？", {
            "intent": "ordinary", "mode": "chat", "source": "model"}, history=history)
        _, research = self.classify("围绕评估协议继续研究，补充知识库文章并重新分析", {
            "intent": "research", "mode": "chat", "source": "mixed"},
            [{"id": "paper-1", "title": "评估协议"}], history=history)
        self.assertEqual(ordinary["presentation_skill"], "")
        self.assertEqual(research["presentation_skill"], "research_card")

    def test_common_knowledge_and_solution_design_split_before_loading_card(self):
        _, ordinary = self.classify("水的沸点是多少？", {
            "intent": "ordinary", "mode": "chat", "source": "model"})
        _, research = self.classify("如何实现一个可审计的知识库检索方案？", {
            "intent": "research", "mode": "chat", "source": "model"})
        self.assertEqual(ordinary["mode"], "chat")
        self.assertEqual(ordinary["presentation_skill"], "")
        self.assertEqual(research["mode"], "research")
        self.assertEqual(research["presentation_skill"], "research_card")

    def test_research_card_skill_loads_only_for_research_runs(self):
        def run_turn(intent):
            run = {"workflow": {}, "evidence": [], "scanned": 0, "academic": False,
                   "question": "设计一个检索方案", "history": "", "plan": "", "query": "检索方案"}
            events = []

            def model(config, key, messages, on_chunk=None, *, cancel=None):
                system = messages[0]["content"]
                if "判断用户当前的意图" in system:
                    return json.dumps({"intent": intent, "mode": "chat", "source": "model"})
                if "制定研究计划" in system:
                    return json.dumps({"goal": "检索方案", "tasks": [
                        {"title": "设计", "question": "如何设计", "query": "检索方案", "web": False}]})
                if "评估关键主张" in system:
                    return '{"assessment":"待验证","query":""}'
                if "生成思维脑图" in system:
                    return '{"title":"检索方案","branches":[{"label":"设计","points":["方案"]}]}'
                return "根据问题设计方案。"

            execute(run, [], {"model": "fake"}, "", "dark", RunLimit(),
                    lambda kind, value: events.append((kind, value)), model=model)
            return [value for kind, value in events if kind == "trace"]

        self.assertFalse(any("加载 Skill · research_card" in event for event in run_turn("ordinary")))
        self.assertTrue(any("加载 Skill · research_card" in event for event in run_turn("research")))

    def test_direct_answer_keeps_web_evidence_in_final_workflow_snapshot(self):
        run = {"workflow": {}, "evidence": [], "scanned": 0, "academic": True,
               "paper_search": False, "web_search": True, "question": "幻影刺客是谁？",
               "history": "", "plan": "", "query": "幻影刺客"}
        source = {"kind": "web", "id": "https://example.org/hero", "url": "https://example.org/hero",
                  "title": "英雄介绍", "level": "原文", "text": "幻影刺客是一名英雄。"}
        events = []

        def model(config, key, messages, on_chunk=None, *, cancel=None):
            if "判断用户当前的意图" in messages[0]["content"]:
                return json.dumps({"intent": "ordinary", "mode": "chat", "source": "web"})
            return "幻影刺客是一名英雄。【E1】"

        with patch("paperreader.research_agent.workflow.retrieve_web_evidence", return_value=[source]):
            status, answer = execute(run, [], {"model": "fake"}, "", "dark", RunLimit(),
                                     lambda kind, value: events.append((kind, value)), model=model)
        snapshots = [value for kind, value in events if kind == "workflow"]
        self.assertEqual(status, "已完成")
        self.assertIn("【E1】", answer)
        self.assertEqual(snapshots[-1][1], [source])

    def test_web_citation_exposes_detail_and_source_links(self):
        source = {"kind": "web", "url": "http://example.org/hero", "title": "英雄介绍", "text": "内容"}

        class CitationView:
            citation_href = ResearchWorkspace.citation_href
            web_citation_href = ResearchWorkspace.web_citation_href
            citation_html = ResearchWorkspace.citation_html

            def selected(self):
                return {"runs": [{"evidence": [source]}]}

        markup = CitationView().citation_html(0, 1, "【E1】")
        self.assertIn("research-content:0-1", markup)
        self.assertIn("research-web:0-1", markup)

    def test_later_subtask_reuses_prior_evidence_when_new_search_fails(self):
        source = {"id": "https://example.org/guide", "url": "https://example.org/guide",
                  "kind": "web", "title": "英雄攻略", "text": "对线与出装策略", "level": "原文"}
        evidence = [source]
        tasks = [{"title": "核对版本", "answer": "已核对", "status": "已完成"},
                 {"title": "形成策略", "question": "如何出装", "query": "幻影刺客出装",
                  "external_query": "Phantom Assassin build", "web": True,
                  "status": "待执行", "answer": "", "refs": []}]
        state = {"tasks": tasks}
        seen = []

        def answer(local, *args, **kwargs):
            seen.extend(local["evidence"])
            return "已完成", "沿用已核对的资料【E1】"

        with patch("paperreader.research_agent.nodes.subtask.answer_question", side_effect=answer):
            result = subtask_node({"cursor": 1}, state=state,
                                  run={"question": "如何玩好幻影刺客", "query": "幻影刺客", "plan": ""},
                                  limit=RunLimit(), publish=lambda _: None, emit=lambda *args: None,
                                  evidence=evidence, sources=[], model_config={"model": "fake"},
                                  key="", theme="dark", model=None, academic=None, call=None)
        self.assertEqual(result["route"], "next_task")
        self.assertEqual(seen, [source])
        self.assertEqual(evidence, [source])
        self.assertEqual(tasks[1]["refs"], [1])
        self.assertIn("【E1】", tasks[1]["answer"])

    def test_short_game_definition_remains_plain_reply(self):
        _, state = self.classify("Dota 是什么？", {
            "mode": "chat", "source": "model", "domain_skills": ["game"]})
        self.assertEqual(state["mode"], "chat")

    def test_domain_catalog_and_independent_loading(self):
        catalog = discover_domain_skills()
        self.assertEqual(set(catalog), {"computer_science", "medicine", "architecture", "game"})
        self.assertIn("版本", load_domain_skill("game").instructions["answer"])
        self.assertEqual(load_domain_skill("game").workflow["max_supplements"], 0)
        self.assertIn("当前最新正式版本", load_domain_skill("game").instructions["plan"])
        self.assertIn("不猜测具体版本号", load_domain_skill("game").instructions["draft"])
        with TemporaryDirectory() as directory:
            folder = Path(directory) / "new_field"
            folder.mkdir()
            (folder / "manifest.json").write_text(json.dumps({
                "id": "new_field", "description": "新领域", "when": "测试",
                "workflow": {"max_tasks": 2}}, ensure_ascii=False), encoding="utf-8")
            self.assertIn("new_field", discover_domain_skills(directory))
            self.assertIsNone(load_domain_skill("new_field", directory))
            (folder / "instructions.json").write_text(json.dumps({
                key: "测试指令" for key in ("plan", "draft", "answer", "evaluate", "summary")
            }, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(load_domain_skill("new_field", directory).id, "new_field")
            with patch("paperreader.research_agent.domain_registry.USER_DOMAIN_ROOT", Path(directory)):
                self.assertIn("new_field", discover_domain_skills())
                self.assertEqual(load_domain_skill("new_field").instructions["plan"], "测试指令")

    def test_intent_selects_domain_skills_without_changing_source_boundary(self):
        result, state = self.classify("比较知识库里的医学论文", {
            "mode": "research", "source": "library", "skill": "literature_compare",
            "domain_skills": ["medicine", "computer_science", "not_installed"],
            "documents": [1, 2]},
            [{"id": "a", "title": "甲"}, {"id": "b", "title": "乙"}])
        self.assertEqual(result["route"], "skill")
        self.assertEqual(state["domain_skills"], ["medicine", "computer_science"])
        self.assertEqual(state["source"], "library")

    def test_domain_profile_changes_plan_and_supplement_loop(self):
        game = load_domain_skill("game")
        captured = []
        state = {"tasks": []}
        plan_node(None, run={"question": "游戏机制", "history": "", "query": "游戏机制",
                             "web_search": True,
                             "workflow_profile": game.workflow,
                             "domain_plan_prompt": game.instructions["plan"]},
                  state=state, publish=lambda _: None, emit=lambda *args: None,
                  call=lambda system, user: captured.append((system, user)) or json.dumps({
                      "tasks": [{"title": "核对版本", "question": "当前版本？", "web": True}]}))
        self.assertIn("1 至 2 个", captured[0][0])
        self.assertIn("平台或服务器", captured[0][0])
        self.assertIn("网页搜索：开启", captured[0][1])
        assessment = evaluate_node(None, run={"workflow_profile": game.workflow,
                                               "domain_evaluate_prompt": game.instructions["evaluate"]},
                                   state={"goal": "游戏机制", "tasks": [{"answer": "待验证"}]},
                                   evidence=[], emit=lambda *args: None,
                                   call=lambda *args: '{"assessment":"缺口","query":"补查"}')
        self.assertEqual(assessment["route"], "summarize")
        medicine = load_domain_skill("medicine")
        state = {"goal": "临床证据", "tasks": [{"answer": "待验证"}], "supplement_count": 1}
        arguments = dict(run={"workflow_profile": medicine.workflow}, state=state,
                         evidence=[], emit=lambda *args: None,
                         call=lambda *args: '{"assessment":"缺口","query":"补查"}')
        self.assertEqual(evaluate_node(None, **arguments)["route"], "supplement")
        state["supplement_count"] = 2
        self.assertEqual(evaluate_node(None, **arguments)["route"], "summarize")

    def test_workflow_loads_selected_domain_only_into_model_request(self):
        events, prompts = [], []
        run = {"workflow": {}, "evidence": [], "scanned": 0, "academic": False,
               "question": "医学论文的研究设计如何评价？", "history": "", "plan": "", "query": "研究设计"}

        def model(config, key, messages, on_chunk=None, *, cancel=None):
            system = messages[0]["content"]
            prompts.append(system)
            if "domain_skills（" in system:
                return '{"mode":"chat","source":"model","domain_skills":["medicine"]}'
            return "需要核查研究设计与研究人群。"

        status, _ = execute(run, [], {"model": "fake"}, "", "dark", RunLimit(),
                            lambda kind, value: events.append((kind, value)), model=model)
        self.assertEqual(status, "已完成")
        self.assertEqual(run["domain_skill_ids"], ["medicine"])
        self.assertIn("区分相关性与因果性", prompts[1])
        self.assertNotIn("核对数据集、版本、指标", prompts[1])
        self.assertTrue(any(kind == "trace" and "加载领域 Skill · medicine" in value
                            for kind, value in events))

    def test_structured_answer_triggers_layout_but_short_chat_does_not(self):
        self.assertFalse(should_layout("你好，我可以帮你查文章。"))
        self.assertIn("短对话保持 Markdown", POSTPROCESS_SKILLS["answer_layout"].when)
        self.assertIsNone(generate_answer_layout(
            "你好，我可以帮你查文章。", lambda *args: self.fail("短答复不应调用排版模型")))
        answer = "## 方法甲\n" + "证据与适用条件。" * 30 + "\n\n## 方法乙\n" + "限制与结果。" * 30
        self.assertTrue(should_layout(answer))

    def test_research_summary_keeps_selected_skill_requirements(self):
        captured = []
        state = {"goal": "比较两篇文章", "tasks": [
            {"title": "比较方法", "status": "已完成", "answer": "两篇方法不同【E1】"}]}
        result = summarize_node(None, run={"skill_prompt": SKILLS["literature_compare"].prompt},
                                state=state, evidence=[{"text": "方法证据", "level": "原文"}],
                                publish=lambda _: None, emit=lambda *args: None,
                                call=lambda system, user, *args: captured.append(system) or "总结【E1】")
        self.assertEqual(result["route"], "overview_map")
        self.assertIn("不同文章的证据不得互相代用", captured[0])

    def test_library_without_matching_evidence_does_not_use_model_memory(self):
        events = []
        run = {"evidence": [], "scanned": 0, "academic": False,
               "library_only": True, "query": "不匹配的内容"}
        status, answer = answer_question(
            run, [], {}, "", "dark", RunLimit(), lambda *args: events.append(args),
            model=lambda *args, **kwargs: self.fail("无证据时不应调用模型"))
        self.assertEqual(status, "已完成")
        self.assertIn("未在指定知识库资料中找到", answer)
        self.assertTrue(any("不调用模型" in value for kind, value in events if kind == "trace"))

    def test_library_answer_prompt_disallows_model_memory(self):
        captured = []
        run = {"evidence": [{"kind": "text", "id": "paper-1", "title": "文章甲",
                             "level": "原文", "text": "文章甲的明确结论"}],
               "scanned": 0, "academic": False, "library_only": True,
               "question": "结论是什么？", "query": "结论", "history": "", "plan": "",
               "skill_prompt": SKILLS["library_qa"].prompt}

        def model(config, key, messages, on_chunk=None, *, cancel=None):
            captured.append(messages[0]["content"])
            return "文章甲的结论【E1】"

        status, _ = answer_question(run, [], {"model": "fake"}, "", "dark", RunLimit(),
                                    lambda *args: None, model=model)
        self.assertEqual(status, "已完成")
        self.assertIn("不使用模型记忆", captured[0])
        self.assertNotIn("可使用模型已有知识", captured[0])

    def test_library_research_without_evidence_skips_model_summary(self):
        result = summarize_node(None, run={"library_only": True}, state={"tasks": [
            {"answer": "未找到依据", "title": "核对", "status": "已完成"}]},
            evidence=[], publish=lambda _: None, emit=lambda *args: None,
            call=lambda *args: self.fail("无证据时不应生成研究总结"))
        self.assertEqual(result["route"], "end")
        self.assertIn("未在指定知识库资料中找到", result["result"][1])

    def test_workflow_loads_library_skill_before_answering(self):
        events = []
        run = {"workflow": {"phase": "规划", "tasks": []}, "evidence": [], "scanned": 0,
               "academic": False, "question": "知识库这篇文章讲了什么？", "history": "",
               "plan": "", "query": "知识库这篇文章讲了什么？"}
        sources = [{"kind": "text", "id": "paper-1", "title": "文章甲", "text": "unrelated"}]

        def model(config, key, messages, on_chunk=None, *, cancel=None):
            self.assertIn("library_qa", messages[0]["content"])
            return '{"mode":"lookup","source":"library","documents":[1],"skill":"library_qa"}'

        status, answer = execute(run, sources, {"model": "fake"}, "", "dark", RunLimit(),
                                 lambda kind, value: events.append((kind, value)), model=model)
        self.assertEqual(status, "已完成")
        self.assertIn("未在指定知识库资料中找到", answer)
        self.assertTrue(any(kind == "trace" and "加载 Skill · library_qa" in value
                            for kind, value in events))

    def test_layout_accepts_summarized_titles_and_rejects_three_column_row(self):
        answer = "## 方法甲\n" + "证据与适用条件。" * 30 + "\n\n## 方法乙\n" + "限制与结果。" * 30
        response = {"groups": [{"component": "Row", "items": [
            {"title": "方法甲的适用条件", "blocks": [0]},
            {"title": "方法乙", "blocks": [1]},
        ]}]}
        payload = generate_answer_layout(answer, lambda *args: json.dumps(response, ensure_ascii=False))
        self.assertIsNotNone(payload)
        self.assertEqual(payload["layout"]["groups"][0]["items"][0]["title"],
                         "方法甲的适用条件")
        self.assertIn("简短提炼当前子章节", POSTPROCESS_SKILLS["answer_layout"].prompt)
        self.assertNotIn("标题只能摘取", POSTPROCESS_SKILLS["answer_layout"].prompt)
        response["groups"][0]["items"].append({"title": "", "blocks": [2]})
        self.assertFalse(validate_layout(response, 3))

    def test_layout_skill_describes_research_components_and_chooses_them(self):
        prompt = POSTPROCESS_SKILLS["answer_layout"].prompt
        for component in ("Text", "Card", "Row", "List", "Tabs", "Evidence",
                          "Table", "Timeline", "Callout", "Divider"):
            self.assertIn(component + "：", prompt)
        self.assertIn("自行选择", prompt)
        self.assertIn("每个编号必须恰好出现一次", prompt)

    def test_research_components_preserve_blocks_and_require_matching_content(self):
        blocks = ["发现支持这一结论【E1】", "| 方法 | 结果 |\n| --- | --- |\n| 甲 | 有效 |",
                  "第一阶段", "第二阶段", "因此需要审慎使用。"]
        layout = {"groups": [
            {"component": "Evidence", "items": [{"title": "", "blocks": [0]}]},
            {"component": "Divider", "items": []},
            {"component": "Table", "items": [{"title": "", "blocks": [1]}]},
            {"component": "Timeline", "items": [
                {"title": "", "blocks": [2]}, {"title": "", "blocks": [3]}]},
            {"component": "Callout", "items": [{"title": "", "blocks": [4]}]},
        ]}
        self.assertTrue(validate_layout(layout, len(blocks), blocks))
        layout["groups"][0]["items"][0]["blocks"] = [4]
        self.assertFalse(validate_layout(layout, len(blocks), blocks))
        layout["groups"][0]["items"][0]["blocks"] = [0]
        layout["groups"][2]["items"][0]["blocks"] = [4]
        self.assertFalse(validate_layout(layout, len(blocks), blocks))
        layout["groups"][2]["items"][0]["blocks"] = [1]
        layout["groups"][3]["items"].pop()
        self.assertFalse(validate_layout(layout, len(blocks), blocks))

    def test_layout_rejects_invented_content_placement(self):
        self.assertFalse(validate_layout({"groups": [
            {"component": "Divider", "items": []},
            {"component": "Text", "items": [{"title": "", "blocks": [0]}]},
        ]}, 1))
        self.assertFalse(validate_layout({"groups": [
            {"component": "Card", "items": [{"title": "", "blocks": [0, 0]}]},
        ]}, 1))


if __name__ == "__main__":
    unittest.main()
