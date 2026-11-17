"""Manage the editable domain skills shown in the research skill library."""

import json
import os
import tempfile
import zipfile
from dataclasses import asdict
from pathlib import Path

from . import domain_registry
from .skills import POSTPROCESS_SKILLS, SKILLS, WORKFLOW_SKILLS


INSTRUCTION_KEYS = ("plan", "draft", "answer", "evaluate", "summary")
MAX_FILE_BYTES = 1024 * 1024
SYSTEM_SKILLS = (
    ("task", SKILLS),
    ("workflow", WORKFLOW_SKILLS),
    ("postprocess", POSTPROCESS_SKILLS),
)


def _roots(user_root=None, builtin_root=None):
    return (Path(user_root) if user_root is not None else domain_registry.USER_DOMAIN_ROOT,
            Path(builtin_root) if builtin_root is not None else domain_registry.DOMAIN_ROOT)


def _skill_id(skill_id):
    if not isinstance(skill_id, str) or not domain_registry.SKILL_ID.fullmatch(skill_id):
        raise ValueError("技能 ID 须由小写字母、数字和下划线组成，并以字母开头")
    return skill_id


def _validate(manifest, instructions):
    if not isinstance(manifest, dict) or not isinstance(instructions, dict):
        raise ValueError("技能清单和指令必须是 JSON 对象")
    skill_id = _skill_id(manifest.get("id"))
    if not all(isinstance(manifest.get(key), str) and manifest[key].strip()
               for key in ("description", "when")):
        raise ValueError("请填写技能描述和适用条件")
    if not all(isinstance(instructions.get(key), str) and instructions[key].strip()
               for key in INSTRUCTION_KEYS):
        raise ValueError("请填写规划、初判、回答、评估和总结五段指令")
    workflow = manifest.get("workflow", {})
    if not isinstance(workflow, dict):
        raise ValueError("工作流配置必须是 JSON 对象")
    minimum = workflow.get("min_tasks", 2)
    maximum = workflow.get("max_tasks", 3)
    supplements = workflow.get("max_supplements", 1)
    if (type(minimum) is not int or type(maximum) is not int or
            type(supplements) is not int or not 1 <= minimum <= maximum <= 5 or
            not 0 <= supplements <= 3 or
            workflow.get("default_external_source", "academic") not in ("academic", "web")):
        raise ValueError("工作流步骤范围或外部资料类型无效")
    if any(key not in INSTRUCTION_KEYS for key in instructions):
        raise ValueError("指令文件包含不支持的字段")
    if any(key not in ("id", "description", "when", "workflow") for key in manifest):
        raise ValueError("技能清单包含不支持的字段")
    if any(key not in ("min_tasks", "max_tasks", "max_supplements", "default_external_source")
           for key in workflow):
        raise ValueError("工作流配置包含不支持的字段")
    return skill_id


def _read_json(path):
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("技能文件不能超过 1 MB")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_domain(folder):
    try:
        if any((folder / name).is_symlink() for name in ("manifest.json", "instructions.json")):
            return None
        manifest = _read_json(folder / "manifest.json")
        instructions = _read_json(folder / "instructions.json")
        if _validate(manifest, instructions) != folder.name:
            return None
        return {"manifest": manifest, "instructions": instructions}
    except (OSError, ValueError, TypeError, UnicodeError):
        return None


def _domain_entries(user_root, builtin_root):
    entries = {}
    for root, origin in ((builtin_root, "builtin"), (user_root, "user")):
        if not root.is_dir():
            continue
        for folder in sorted(root.iterdir()):
            if not folder.is_dir() or folder.is_symlink() or not domain_registry.SKILL_ID.fullmatch(folder.name):
                continue
            if (user_root / ".disabled" / folder.name).is_file():
                continue
            data = _read_domain(folder)
            if data is not None:
                entries[folder.name] = {**data, "origin": origin}
    return entries


def list_skills(*, user_root=None, builtin_root=None):
    """Return every available skill, including read-only program capabilities."""
    user_root, builtin_root = _roots(user_root, builtin_root)
    domains = _domain_entries(user_root, builtin_root)
    result = []
    for skill_id, data in sorted(domains.items()):
        result.append({"id": skill_id, "category": "domain",
                       "description": data["manifest"]["description"],
                       "when": data["manifest"]["when"], "origin": data["origin"],
                       "editable": True,
                       "overridden": data["origin"] == "user" and
                       _read_domain(builtin_root / skill_id) is not None})
    for category, skills in SYSTEM_SKILLS:
        for skill_id, spec in skills.items():
            result.append({"id": skill_id, "category": category,
                           "description": spec.description, "when": spec.when,
                           "origin": "system", "editable": False, "overridden": False})
    return result


def list_disabled_skills(*, user_root=None, builtin_root=None):
    """Return disabled built-in domains so the UI can offer restoration."""
    user_root, builtin_root = _roots(user_root, builtin_root)
    markers = user_root / ".disabled"
    if not markers.is_dir():
        return []
    result = []
    for marker in sorted(markers.iterdir()):
        if not marker.is_file() or marker.is_symlink() or not domain_registry.SKILL_ID.fullmatch(marker.name):
            continue
        data = _read_domain(builtin_root / marker.name)
        if data is not None:
            result.append({"id": marker.name, "category": "domain",
                           "description": data["manifest"]["description"],
                           "when": data["manifest"]["when"], "origin": "builtin",
                           "editable": False, "overridden": False, "disabled": True})
    return result


def read_skill(skill_id, category="domain", *, user_root=None, builtin_root=None):
    """Read the exact displayed definition and its editability."""
    user_root, builtin_root = _roots(user_root, builtin_root)
    if category == "domain":
        _skill_id(skill_id)
        data = _domain_entries(user_root, builtin_root).get(skill_id)
        if data is None:
            raise FileNotFoundError(f"找不到技能：{skill_id}")
        return {"id": skill_id, "category": "domain", **data, "editable": True,
                "overridden": data["origin"] == "user" and
                _read_domain(builtin_root / skill_id) is not None}
    for kind, skills in SYSTEM_SKILLS:
        if kind == category and skill_id in skills:
            return {"id": skill_id, "category": kind, "spec": asdict(skills[skill_id]),
                    "origin": "system", "editable": False, "overridden": False}
    raise FileNotFoundError(f"找不到技能：{skill_id}")


def _json_bytes(data):
    payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(payload) > MAX_FILE_BYTES:
        raise ValueError("技能文件不能超过 1 MB")
    return payload


def save_domain_skill(manifest, instructions, *, user_root=None):
    """Create or update a user skill. Saving a built-in ID creates an override."""
    skill_id = _validate(manifest, instructions)
    files = (("manifest.json", _json_bytes(manifest)),
             ("instructions.json", _json_bytes(instructions)))
    user_root, _ = _roots(user_root)
    user_root.mkdir(parents=True, exist_ok=True)
    folder = user_root / skill_id
    if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
        raise ValueError("技能目录无效")
    folder.mkdir(exist_ok=True)
    for filename, payload in files:
        target = folder / filename
        if target.is_symlink():
            raise ValueError("技能文件不能是符号链接")
        with tempfile.NamedTemporaryFile(dir=folder, delete=False) as pending:
            temporary = Path(pending.name)
            try:
                pending.write(payload)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        os.replace(temporary, target)
    (user_root / ".disabled" / skill_id).unlink(missing_ok=True)
    return read_skill(skill_id, user_root=user_root)


def delete_domain_skill(skill_id, *, user_root=None):
    """Delete a custom skill or disable a built-in domain without altering its files."""
    user_root, builtin_root = _roots(user_root)
    folder = user_root / _skill_id(skill_id)
    builtin_exists = _read_domain(builtin_root / skill_id) is not None
    user_exists = folder.is_dir() and _read_domain(folder) is not None
    if not builtin_exists and not user_exists:
        raise FileNotFoundError(f"没有可删除的领域技能：{skill_id}")
    if folder.is_symlink():
        raise ValueError("技能目录不能是符号链接")
    if user_exists:
        for filename in ("manifest.json", "instructions.json"):
            if (folder / filename).is_symlink():
                raise ValueError("技能文件不能是符号链接")
        if {item.name for item in folder.iterdir()} != {"manifest.json", "instructions.json"}:
            raise ValueError("技能目录包含其他文件，无法安全删除")
        for filename in ("manifest.json", "instructions.json"):
            (folder / filename).unlink()
        folder.rmdir()
    if builtin_exists:
        markers = user_root / ".disabled"
        markers.mkdir(parents=True, exist_ok=True)
        (markers / skill_id).touch(exist_ok=True)
    return True


def restore_domain_skill(skill_id, *, user_root=None, builtin_root=None):
    """Restore a disabled built-in domain to the catalog and runtime."""
    user_root, builtin_root = _roots(user_root, builtin_root)
    _skill_id(skill_id)
    if _read_domain(builtin_root / skill_id) is None:
        raise FileNotFoundError(f"找不到内置领域技能：{skill_id}")
    marker = user_root / ".disabled" / skill_id
    if marker.is_symlink() or not marker.is_file():
        raise FileNotFoundError(f"技能未停用：{skill_id}")
    marker.unlink()
    return read_skill(skill_id, user_root=user_root, builtin_root=builtin_root)


def import_domain_skill(source, *, replace=False, user_root=None):
    """Import a JSON-only ZIP package after validating both files."""
    source = Path(source)
    try:
        with zipfile.ZipFile(source) as archive:
            names = archive.namelist()
            if len(names) != 2 or set(names) != {"manifest.json", "instructions.json"}:
                raise ValueError("技能压缩包只能包含 manifest.json 和 instructions.json")
            values = {}
            for name in names:
                info = archive.getinfo(name)
                if info.is_dir() or info.file_size > MAX_FILE_BYTES:
                    raise ValueError("技能压缩包文件无效或超过 1 MB")
                data = archive.read(info)
                if len(data) > MAX_FILE_BYTES:
                    raise ValueError("技能压缩包文件超过 1 MB")
                values[name] = json.loads(data.decode("utf-8"))
    except (zipfile.BadZipFile, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("技能压缩包损坏或 JSON 格式错误") from error
    manifest, instructions = values["manifest.json"], values["instructions.json"]
    skill_id = _validate(manifest, instructions)
    user_root, _ = _roots(user_root)
    if (user_root / skill_id).exists() and not replace:
        raise FileExistsError(f"用户技能 {skill_id} 已存在")
    return save_domain_skill(manifest, instructions, user_root=user_root)


def export_skill(skill_id, destination, category="domain", *, user_root=None, builtin_root=None):
    """Export a domain package or a read-only system definition as ZIP."""
    skill = read_skill(skill_id, category, user_root=user_root, builtin_root=builtin_root)
    destination = Path(destination)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if category == "domain":
            archive.writestr("manifest.json", _json_bytes(skill["manifest"]))
            archive.writestr("instructions.json", _json_bytes(skill["instructions"]))
        else:
            archive.writestr("system_skill.json", _json_bytes({
                "id": skill_id, "category": category, "spec": skill["spec"],
                "note": "程序内置能力定义，仅供阅读和备份，不能作为领域技能导入。",
            }))
    return destination
