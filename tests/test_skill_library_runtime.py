"""Saved skills must be available to the research agent's actual router."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from paperreader.research_agent import domain_registry
from paperreader.research_agent.skill_library import (
    delete_domain_skill, restore_domain_skill, save_domain_skill,
)


class SkillLibraryRuntimeTests(unittest.TestCase):
    def test_new_skill_and_builtin_override_reach_runtime(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            instructions = {stage: f"自定义{stage}指令" for stage in
                            ("plan", "draft", "answer", "evaluate", "summary")}
            with patch.object(domain_registry, "USER_DOMAIN_ROOT", root):
                save_domain_skill(
                    {"id": "new_field", "description": "新领域", "when": "需要新领域时"},
                    instructions,
                )
                self.assertIn("new_field", domain_registry.discover_domain_skills())
                self.assertEqual(domain_registry.load_domain_skill("new_field").instructions,
                                 instructions)

                builtin = domain_registry.load_domain_skill("game")
                save_domain_skill(
                    {"id": "game", "description": "用户覆盖", "when": "测试游戏研究时"},
                    instructions,
                )
                self.assertEqual(domain_registry.load_domain_skill("game").instructions,
                                 instructions)
                delete_domain_skill("game")
                self.assertNotIn("game", domain_registry.discover_domain_skills())
                self.assertIsNone(domain_registry.load_domain_skill("game"))
                restore_domain_skill("game")
                self.assertEqual(domain_registry.load_domain_skill("game"), builtin)


if __name__ == "__main__":
    unittest.main()
