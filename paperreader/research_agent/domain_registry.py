"""Discover domain research skills without loading their instructions eagerly."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from platformdirs import user_data_dir


DOMAIN_ROOT = Path(__file__).with_name("domain_skills")
USER_DOMAIN_ROOT = Path(user_data_dir("PaperReader", appauthor=False)) / "skills" / "domains"
SKILL_ID = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class DomainSkill:
    id: str
    description: str
    when: str
    workflow: dict
    instructions: dict


def _read_manifest(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("id") != path.parent.name or not SKILL_ID.fullmatch(path.parent.name):
        raise ValueError("领域技能 ID 与目录不一致")
    if not all(isinstance(data.get(key), str) and data[key].strip()
               for key in ("description", "when")):
        raise ValueError("领域技能缺少描述或适用条件")
    profile = data.get("workflow", {})
    if not isinstance(profile, dict):
        raise ValueError("领域工作流配置无效")
    minimum = profile.get("min_tasks", 2)
    maximum = profile.get("max_tasks", 3)
    supplements = profile.get("max_supplements", 1)
    if (type(minimum) is not int or type(maximum) is not int or
            type(supplements) is not int or not 1 <= minimum <= maximum <= 5 or
            not 0 <= supplements <= 3 or
            profile.get("default_external_source", "academic") not in ("academic", "web")):
        raise ValueError("领域工作流范围无效")
    return data


def _roots(root):
    return (Path(root),) if root is not None else (DOMAIN_ROOT, USER_DOMAIN_ROOT)


def _disabled_root(root):
    return (Path(root) if root is not None else USER_DOMAIN_ROOT) / ".disabled"


def _is_disabled(skill_id, root=None):
    return (_disabled_root(root) / skill_id).is_file()


def discover_domain_skills(root=None):
    """Return validated metadata; full instructions are read only on selection."""
    catalog = {}
    for folder in _roots(root):
        for path in sorted(folder.glob("*/manifest.json")):
            if _is_disabled(path.parent.name, root):
                continue
            try:
                data = _read_manifest(path)
            except (OSError, ValueError, TypeError):
                continue
            catalog[data["id"]] = {key: data[key] for key in ("id", "description", "when")}
    return catalog


def domain_skill_catalog(root=None):
    return "；".join(f"{skill['id']}：{skill['description']}。适用：{skill['when']}"
                    for skill in discover_domain_skills(root).values())


def load_domain_skill(skill_id, root=None):
    """Load one selected skill. Invalid or unavailable skills cannot enter a run."""
    if not isinstance(skill_id, str) or not SKILL_ID.fullmatch(skill_id):
        return None
    if _is_disabled(skill_id, root):
        return None
    keys = ("plan", "draft", "answer", "evaluate", "summary")
    for folder in reversed(_roots(root)):
        path = folder / skill_id
        try:
            metadata = _read_manifest(path / "manifest.json")
            instructions = json.loads((path / "instructions.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(instructions, dict) and all(
                isinstance(instructions.get(key), str) and instructions[key].strip() for key in keys):
            return DomainSkill(skill_id, metadata["description"], metadata["when"],
                               metadata.get("workflow", {}),
                               {key: instructions[key] for key in keys})
    return None
