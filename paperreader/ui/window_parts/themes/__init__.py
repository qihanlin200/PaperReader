"""Themes behavior for the main window."""
from pathlib import Path
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtCore import Qt
from paperreader.ui.markdown import MarkdownBrowser
from paperreader.ui.work_rail import menu_symbol_icon
from paperreader.services.themes import THEMES, get_theme
from paperreader.ui.theme import apply_theme
from paperreader.ui.settings import open_settings, build_model_settings
from paperreader.services.persona import assistant_name
from paperreader.ui.window_parts.jobs import Job

class ThemesMixin:
    def settings(self):
        return open_settings(self)

    def change_theme(self, theme):
        if not isinstance(theme, str) or theme not in THEMES:
            return False
        if theme == self.profile_config["theme"]:
            return True
        try:
            self.library.save_config(dict(self.library.config(), theme=theme))
        except Exception as exc:
            self.error("主题保存失败：" + str(exc))
            return False
        self.profile_config["theme"] = theme
        apply_theme(theme)
        if self.skill_library is not None:
            self.skill_library.refresh_palette()
        self.centralWidget().update()
        self.update_theme_art()
        self.view.refresh_theme()
        self.update_chat_avatar()
        for browser in self.findChildren(MarkdownBrowser):
            browser.refresh_theme()
        return True

    def change_pdf_follow_theme(self, enabled):
        if self.paper is None:
            return False
        enabled = bool(enabled)
        try:
            self.library.save(dict(self.paper, pdf_follow_theme=enabled))
        except Exception as exc:
            self.error("论文背景设置保存失败：" + str(exc))
            return False
        self.paper["pdf_follow_theme"] = enabled
        self.view.set_follow_theme(enabled)
        self.pdf_color_button.setText("黑白色" if enabled else "主题色")
        return True

    @property
    def reading_assistant_name(self):
        return assistant_name(self.profile_config["theme"])

    def update_theme_art(self):
        for columns, control in self.pdf_layout_buttons.items():
            control.setIcon(menu_symbol_icon(f"pages-{columns}", size=20))
        self.pdf_fullscreen_button.setIcon(menu_symbol_icon(
            "contract" if self.pdf_fullscreen_state else "expand", size=18))
        pack = get_theme(self.profile_config["theme"])
        self.list.refresh_paper_icons(pack.identifier)
        if self.research_workspace is not None:
            self.research_workspace.refresh_space_icons()
            self.research_workspace.refresh_sources()
        self.work_rail.update()
        self.reading_home.set_theme(pack.identifier)
        self.update_reading_home()
        avatar = pack.avatar if pack.identifier != "dark" else None
        self.sage_card.setVisible(bool(avatar or pack.tagline))
        self.sage_title.setText(pack.assistant_name)
        self.sage_badge.setText(pack.tagline)
        self.sage_badge.setVisible(bool(pack.tagline))
        self.sage_avatar.setVisible(bool(avatar))
        self.sage_avatar.setPixmap(QIcon(str(avatar)).pixmap(QSize(76, 76)) if avatar else QPixmap())
        self.top_bar.setFixedHeight(pack.header_height)
        self.top_bar.set_animation(pack.header_animation, pack.banner_animation)
        self.top_bar.layout().setAlignment(Qt.AlignmentFlag.AlignTop if pack.banner else Qt.AlignmentFlag(0))
        self.top_bar.update()
        inset = pack.panel_inset
        for pane in self.reading_panes:
            pane.layout().setContentsMargins(inset, inset, inset, inset)
        default_mark = Path(__file__).resolve().parent.parent.parent.parent / "assets" / "brand-diamond.svg"
        self.brand_icon.setPixmap(QIcon(str(pack.brand_icon or default_mark)).pixmap(QSize(24, 24)))
        self.question.setPlaceholderText(pack.question_placeholder)

    def build_model_settings(self, dialog, form):
        return build_model_settings(self, dialog, form, Job)
