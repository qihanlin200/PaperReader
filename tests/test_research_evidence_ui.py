"""Acceptance checks for task-grouped research citations."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PySide6.QtWidgets import QApplication, QLabel

from paperreader.ui.research_evidence import EvidenceMatrix
from paperreader.ui.theme import apply_theme


def sample_groups():
    return [
        {"key": "run-1", "title": "任务 1 · 比较方案", "subtitle": "2026-11-17 12:00 · 2 个子任务",
         "status": "已完成", "task_number": 1, "subtasks": [
             {"key": (0, 1), "title": "子任务 2 · 核对结论", "status": "已完成",
              "entries": [
                  ("E3 · 本地笔记", "用户笔记", "第 4 行", "research-content:0-3", "text"),
                  ("E2 · 官方网页", "网页正文", "原文", "research-content:0-2", "web"),
              ]},
             {"key": (0, 0), "title": "子任务 1 · 收集资料", "status": "已完成",
              "entries": [
                  ("E2 · 官方网页", "网页正文", "原文", "research-content:0-2", "web"),
                  ("E1 · 论文", "本地段落", "PDF 第 2 页", "research-content:0-1", "paper"),
              ]},
         ]},
    ]


class EvidenceMatrixUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        apply_theme("dark")
        self.matrix = EvidenceMatrix()
        self.matrix.resize(920, 600)
        self.matrix.show()
        self.app.processEvents()

    def tearDown(self):
        self.matrix.close()
        apply_theme("dark")

    def test_task_rows_keep_duplicate_reference_and_click_target(self):
        self.matrix.set_groups(sample_groups())
        self.app.processEvents()
        self.assertEqual(len(self.matrix.group_rows), 1)
        first, second = self.matrix.subtask_rows
        self.assertEqual(len(first["cards"]), 2)
        self.assertEqual(len(second["cards"]), 2)
        self.assertEqual(first["cards"][0].objectName(), "ResearchEvidenceLocal")
        self.assertEqual(first["cards"][1].objectName(), "ResearchEvidenceWeb")
        self.assertEqual(second["cards"][0].objectName(), "ResearchEvidenceWeb")
        self.assertEqual(second["cards"][1].objectName(), "ResearchEvidenceLocal")

        opened = []
        self.matrix.anchorClicked.connect(lambda url: opened.append(url.toString()))
        second["cards"][0].click()
        self.assertEqual(opened, ["research-content:0-2"])

        first["header"].click()
        self.assertFalse(first["cards_widget"].isVisible())
        self.assertTrue(second["cards_widget"].isVisible())
        self.matrix.group_rows[0]["header"].click()
        self.assertFalse(self.matrix.group_rows[0]["content_widget"].isVisible())
        self.matrix.set_groups(sample_groups() + [{"key": "run-2", "title": "任务 2 · 旧任务",
            "subtitle": "旧记录", "status": "", "task_number": 2,
            "subtasks": [{"key": (1, "unassigned"), "title": "未归入任务",
                          "status": "", "entries": []}]}])
        self.app.processEvents()
        self.assertFalse(self.matrix.group_rows[0]["content_widget"].isVisible())
        self.assertFalse(self.matrix.subtask_rows[0]["cards_widget"].isVisible())

    def test_source_badges_and_empty_task(self):
        groups = sample_groups()
        groups[0]["subtasks"][0]["entries"].append(
            ("E4 · 学术题录", "摘要", "摘要", "research-content:0-4", "academic"))
        groups[0]["subtasks"].append({"key": (0, 2), "title": "子任务 3 · 补查",
                                       "status": "待执行", "entries": []})
        self.matrix.set_groups(groups)
        self.app.processEvents()
        local_text = self.matrix.subtask_rows[0]["cards"][0]
        web = self.matrix.subtask_rows[0]["cards"][1]
        academic = self.matrix.subtask_rows[0]["cards"][2]
        local = self.matrix.subtask_rows[1]["cards"][1]
        self.assertIn("本地论文", [label.text() for label in local.findChildren(QLabel)])
        self.assertIn("本地资料", [label.text() for label in local_text.findChildren(QLabel)])
        self.assertIn("网页检索", [label.text() for label in web.findChildren(QLabel)])
        self.assertIn("学术来源", [label.text() for label in academic.findChildren(QLabel)])
        self.assertEqual(academic.objectName(), "ResearchEvidenceWeb")
        self.assertIn("该子任务暂无可展示的引用。",
                      [label.text() for label in self.matrix.subtask_rows[2]["cards"]])


if __name__ == "__main__":
    unittest.main()
