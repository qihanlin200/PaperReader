"""Skill library persistence and package boundaries."""

import json
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from paperreader.research_agent import domain_registry
from paperreader.research_agent.skill_library import (
    delete_domain_skill, export_skill, import_domain_skill, list_disabled_skills,
    list_skills, read_skill, restore_domain_skill, save_domain_skill,
)


def definition(skill_id="example"):
    manifest = {"id": skill_id, "description": "测试领域", "when": "研究测试问题时",
                "workflow": {"min_tasks": 1, "max_tasks": 2}}
    instructions = {key: f"{key} 阶段先核对证据"
                    for key in ("plan", "draft", "answer", "evaluate", "summary")}
    return manifest, instructions


class SkillLibraryTests(unittest.TestCase):
    def test_builtin_system_and_user_override(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            entries = list_skills(user_root=root)
            self.assertEqual(len(entries), 8)
            self.assertEqual({item["category"] for item in entries},
                             {"domain", "task", "workflow", "postprocess"})
            self.assertFalse(read_skill("answer_layout", "postprocess")["editable"])
            builtin = read_skill("game", user_root=root)
            self.assertEqual(builtin["origin"], "builtin")
            manifest = dict(builtin["manifest"], description="用户版本")
            save_domain_skill(manifest, builtin["instructions"], user_root=root)
            changed = read_skill("game", user_root=root)
            self.assertEqual(changed["origin"], "user")
            self.assertTrue(changed["overridden"])
            self.assertEqual(changed["manifest"]["description"], "用户版本")
            delete_domain_skill("game", user_root=root)
            self.assertNotIn("game", {item["id"] for item in list_skills(user_root=root)})
            self.assertEqual([item["id"] for item in list_disabled_skills(user_root=root)], ["game"])
            with patch.object(domain_registry, "USER_DOMAIN_ROOT", root):
                self.assertNotIn("game", domain_registry.discover_domain_skills())
                self.assertIsNone(domain_registry.load_domain_skill("game"))
            self.assertEqual(restore_domain_skill("game", user_root=root)["origin"], "builtin")
            self.assertEqual(read_skill("game", user_root=root)["origin"], "builtin")
            with self.assertRaises(FileNotFoundError):
                restore_domain_skill("game", user_root=root)

    def test_create_export_import_and_conflict(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            user_root, second_root = root / "skills", root / "other"
            manifest, instructions = definition()
            saved = save_domain_skill(manifest, instructions, user_root=user_root)
            self.assertEqual(saved["instructions"], instructions)
            archive = export_skill("example", root / "example.zip", user_root=user_root)
            with zipfile.ZipFile(archive) as package:
                self.assertEqual(set(package.namelist()), {"manifest.json", "instructions.json"})
            imported = import_domain_skill(archive, user_root=second_root)
            self.assertEqual(imported["manifest"], manifest)
            with self.assertRaises(FileExistsError):
                import_domain_skill(archive, user_root=second_root)
            self.assertEqual(import_domain_skill(archive, replace=True, user_root=second_root)
                             ["instructions"], instructions)
            system_archive = export_skill("library_qa", root / "system.zip", "task")
            with zipfile.ZipFile(system_archive) as package:
                self.assertEqual(package.namelist(), ["system_skill.json"])
            delete_domain_skill("example", user_root=user_root)
            self.assertNotIn("example", {item["id"] for item in list_skills(user_root=user_root)})
            self.assertEqual(list_disabled_skills(user_root=user_root), [])

    def test_save_restores_a_disabled_builtin(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            delete_domain_skill("medicine", user_root=root)
            self.assertIn("medicine", {item["id"] for item in list_disabled_skills(user_root=root)})
            builtin = domain_registry.load_domain_skill("medicine")
            manifest = {"id": "medicine", "description": "更新后的医学技能", "when": "医学研究"}
            save_domain_skill(manifest, builtin.instructions, user_root=root)
            self.assertEqual(list_disabled_skills(user_root=root), [])
            self.assertEqual(read_skill("medicine", user_root=root)["origin"], "user")

    def test_reject_invalid_and_unsafe_packages_without_writing(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, instructions = definition()
            with self.assertRaises(ValueError):
                save_domain_skill(dict(manifest, id="../outside"), instructions,
                                  user_root=root / "skills")
            self.assertFalse((root / "skills").exists())
            invalid = root / "unsafe.zip"
            with zipfile.ZipFile(invalid, "w") as package:
                package.writestr("../manifest.json", json.dumps(manifest))
                package.writestr("instructions.json", json.dumps(instructions))
            with self.assertRaises(ValueError):
                import_domain_skill(invalid, user_root=root / "skills")
            self.assertFalse((root / "skills").exists())
            bad = root / "bad.zip"
            bad.write_text("not zip", encoding="utf-8")
            with self.assertRaises(ValueError):
                import_domain_skill(bad, user_root=root / "skills")


if __name__ == "__main__":
    unittest.main()
