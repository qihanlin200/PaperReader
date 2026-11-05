"""Load each visual theme together with its bound reading assistant."""
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


DEFAULT_THEME_ID = "dark"
THEME_ROOT = Path(__file__).resolve().parent.parent / "themes"
_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Theme:
    identifier: str
    name: str
    assistant_name: str
    voice: str = ""
    avatar: Optional[Path] = None
    tagline: str = ""
    colors: dict = field(default_factory=dict)
    warm_surfaces: bool = False
    stylesheet: str = ""
    document_css: str = ""
    arrow: Optional[Path] = None
    banner: Optional[Path] = None
    header_animation: Optional[Path] = None
    banner_crop: tuple = (0.0, 1.0)
    banner_background: str = "#111a28"
    brand_icon: Optional[Path] = None
    header_height: int = 58
    panel_inset: int = 0
    heading_background: Optional[str] = None
    question_placeholder: str = "继续追问，或引用原文…"


def _asset(folder, name):
    if name is None:
        return None
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Asset paths must be nonempty strings")
    path = (folder / name).resolve()
    if not path.is_relative_to(folder.resolve()) or not path.is_file():
        raise ValueError(f"Invalid theme asset: {name}")
    return path


def _text(folder, name):
    path = _asset(folder, name)
    return path.read_text(encoding="utf-8") if path else ""


def _label(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Theme and assistant names must be nonempty strings")
    return value.strip()


def _color(value):
    if not isinstance(value, str) or not _COLOR.fullmatch(value):
        raise ValueError("Theme colors must use #RRGGBB")
    return value.lower()


def _dimension(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"Theme layout value must be between {minimum} and {maximum}")
    return value


def _load_theme(folder):
    data = json.loads((folder / "theme.json").read_text(encoding="utf-8"))
    assistant = data["assistant"]
    tagline = assistant.get("tagline", "")
    if not isinstance(tagline, str):
        raise ValueError("Assistant tagline must be a string")
    crop_top, crop_bottom = data.get("banner_crop", [0, 1])
    if not 0 <= crop_top < crop_bottom <= 1:
        raise ValueError("Banner crop must contain increasing fractions between 0 and 1")
    return Theme(
        identifier=folder.name,
        name=_label(data["name"]),
        assistant_name=_label(assistant["name"]),
        voice=_text(folder, assistant.get("voice")).strip(),
        avatar=_asset(folder, assistant.get("avatar")),
        tagline=tagline.strip(),
        colors={_color(key): _color(value) for key, value in data.get("colors", {}).items()},
        warm_surfaces=data.get("warm_surfaces", False) is True,
        stylesheet=_text(folder, data.get("stylesheet")).replace("__THEME_DIR__", folder.as_posix()),
        document_css=_text(folder, data.get("document_css")),
        arrow=_asset(folder, data.get("arrow")),
        banner=_asset(folder, data.get("banner")),
        header_animation=_asset(folder, data.get("header_animation")),
        banner_crop=(crop_top, crop_bottom),
        banner_background=_color(data.get("banner_background", "#111a28")),
        brand_icon=_asset(folder, data.get("brand_icon")),
        header_height=_dimension(data.get("header_height", 58), 48, 180),
        panel_inset=_dimension(data.get("panel_inset", 0), 0, 8),
        heading_background=_color(data["heading_background"]) if "heading_background" in data else None,
        question_placeholder=_label(data.get("question_placeholder", "继续追问，或引用原文…")),
    )


def load_themes(root=THEME_ROOT):
    themes = {}
    for manifest in sorted(root.glob("*/theme.json")):
        folder = manifest.parent
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", folder.name):
            continue
        try:
            themes[folder.name] = _load_theme(folder)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            _LOGGER.warning("Skipping invalid theme %s: %s", folder.name, exc)
    default = themes.pop(DEFAULT_THEME_ID, Theme(DEFAULT_THEME_ID, "深色主题", "无情的阅读机器"))
    return {DEFAULT_THEME_ID: default, **themes}


THEMES = load_themes()


def get_theme(identifier):
    default = THEMES[DEFAULT_THEME_ID]
    return THEMES.get(identifier, default) if isinstance(identifier, str) else default
