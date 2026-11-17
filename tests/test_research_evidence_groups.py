"""Task ownership and source type for the research evidence matrix."""

import unittest

from paperreader.ui.research import ResearchWorkspace


class EvidenceGroupTests(unittest.TestCase):
    def test_task_refs_keep_global_numbers_and_source_types(self):
        space = {"runs": [{
            "question": "比较方案", "status": "已完成",
            "workflow": {"tasks": [
                {"title": "检索论文", "status": "已完成", "refs": [1, 2, 2]},
                {"title": "核对网页", "status": "已完成", "refs": [2, 3, 99]},
            ]},
            "evidence": [
                {"kind": "paper", "title": "本地论文", "text": "论文段落", "page": 0},
                {"kind": "web", "title": "网页", "text": "网页正文", "level": "原文"},
                {"kind": "academic", "title": "学术题录", "text": "摘要", "level": "摘要"},
                {"kind": "text", "title": "本地笔记", "text": "笔记", "line": 2},
            ],
        }]}
        groups = ResearchWorkspace.evidence_groups(space)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["title"], "任务 1 · 比较方案")
        subtasks = groups[0]["subtasks"]
        self.assertEqual([item["title"] for item in subtasks],
                         ["子任务 2 · 核对网页", "子任务 1 · 检索论文", "未归入任务"])
        self.assertEqual([[entry[4] for entry in item["entries"]] for item in subtasks],
                         [["academic", "web"], ["web", "paper"], ["text"]])
        self.assertEqual(subtasks[0]["entries"][1][3], "research-content:0-2")
        self.assertEqual(subtasks[2]["entries"][0][3], "research-content:0-4")

    def test_old_run_without_refs_still_exposes_all_evidence(self):
        space = {"runs": [{"question": "旧任务", "workflow": {"tasks": [{"title": "旧步骤"}]},
                           "evidence": [{"kind": "web", "title": "旧网页", "text": "正文"}]}]}
        groups = ResearchWorkspace.evidence_groups(space)
        self.assertEqual([item["title"] for item in groups[0]["subtasks"]],
                         ["子任务 1 · 旧步骤", "未归入任务"])
        self.assertEqual(groups[0]["subtasks"][0]["entries"], [])
        self.assertEqual(groups[0]["subtasks"][1]["entries"][0][3], "research-content:0-1")

    def test_newest_run_time_is_first_without_changing_citation_index(self):
        space = {"runs": [
            {"id": "old", "question": "较旧任务", "trace": [["2026-11-16T12:00:00", "开始"]],
             "workflow": {"tasks": [{"title": "旧子任务", "refs": [1]}]},
             "evidence": [{"kind": "paper", "title": "旧论文", "text": "旧内容", "page": 0}]},
            {"id": "new", "question": "较新任务", "trace": [["2026-11-17T12:00:00", "开始"]],
             "workflow": {"tasks": [{"title": "新子任务", "refs": [1]}]},
             "evidence": [{"kind": "web", "title": "新网页", "text": "新内容"}]},
        ]}
        groups = ResearchWorkspace.evidence_groups(space)
        self.assertEqual([group["key"] for group in groups], ["new", "old"])
        self.assertEqual(groups[0]["subtasks"][0]["entries"][0][3], "research-content:1-1")
        self.assertEqual(groups[1]["subtasks"][0]["entries"][0][3], "research-content:0-1")


if __name__ == "__main__":
    unittest.main()
