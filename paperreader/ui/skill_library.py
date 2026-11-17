"""Browse and manage research skills in the application's theme."""

import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

from paperreader.research_agent.skill_library import (
    delete_domain_skill, export_skill, import_domain_skill, list_disabled_skills,
    list_skills, read_skill, restore_domain_skill, save_domain_skill,
)
from paperreader.ui.theme import theme_color


STAGES = (("plan", "规划"), ("draft", "初判"), ("answer", "回答"),
          ("evaluate", "评估"), ("summary", "总结"))


class SkillLibrary(QWidget):
    """One skills catalog with a read-only preview and explicit edit mode."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SkillLibrary")
        self.entries = []
        self.current_key = None
        self.current_data = None
        self.editing = False
        self.creating = False
        self._loading = False
        self._loading_fields = False
        self._dirty = False
        self.collapsed_groups = {"system", "disabled"}
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 8, 16, 12)
        root.setSpacing(8)

        heading = QHBoxLayout()
        heading.setSpacing(10)
        title = QLabel("技能库"); title.setObjectName("SkillLibraryTitle")
        separator = QLabel("|"); separator.setObjectName("SkillLibrarySeparator")
        subtitle = QLabel("管理研究技能，编辑领域指令，查看系统能力")
        subtitle.setObjectName("SkillLibraryMuted")
        heading.addWidget(title)
        heading.addWidget(separator)
        heading.addWidget(subtitle)
        heading.addStretch()
        self.import_button = self._button("导入技能", self.import_skill)
        self.new_button = self._button("＋ 新建领域技能", self.new_skill, primary=True)
        heading.addWidget(self.import_button); heading.addWidget(self.new_button)
        root.addLayout(heading)

        body = QHBoxLayout(); body.setSpacing(14)
        catalog = QFrame(); catalog.setObjectName("SkillLibraryPanel")
        catalog.setMinimumWidth(285); catalog.setMaximumWidth(360)
        catalog_layout = QVBoxLayout(catalog); catalog_layout.setContentsMargins(14, 14, 14, 14)
        catalog_layout.setSpacing(10)
        catalog_layout.addWidget(QLabel("技能目录"))
        self.search = QLineEdit(); self.search.setPlaceholderText("搜索名称、说明或适用场景")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh_catalog)
        catalog_layout.addWidget(self.search)
        self.catalog = QListWidget(); self.catalog.setObjectName("SkillCatalog")
        self.catalog.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.catalog.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.catalog.currentItemChanged.connect(self.select_item)
        self.catalog.itemClicked.connect(self.toggle_group)
        catalog_layout.addWidget(self.catalog, 1)
        body.addWidget(catalog)

        detail = QFrame(); detail.setObjectName("SkillLibraryPanel")
        detail_layout = QVBoxLayout(detail); detail_layout.setContentsMargins(22, 16, 22, 16)
        detail_layout.setSpacing(12)
        top = QHBoxLayout()
        self.name = QLabel("选择一个技能"); self.name.setObjectName("SkillLibraryDetailTitle")
        top.addWidget(self.name, 1)
        self.origin = QLabel(""); self.origin.setObjectName("SkillLibraryBadge")
        top.addWidget(self.origin)
        self.export_button = self._button("导出", self.export_current)
        self.delete_button = self._button("删除", self.delete_current)
        self.restore_button = self._button("恢复", self.restore_current)
        self.edit_button = self._button("编辑", self.edit_current)
        self.save_button = self._button("保存", self.save_current, primary=True)
        self.cancel_button = self._button("取消", self.cancel_edit)
        for widget in (self.export_button, self.delete_button, self.restore_button, self.edit_button,
                       self.save_button, self.cancel_button):
            top.addWidget(widget)
        detail_layout.addLayout(top)
        self.hint = QLabel(""); self.hint.setObjectName("SkillLibraryMuted")
        self.hint.setWordWrap(True); detail_layout.addWidget(self.hint)

        self.detail_scroll = QScrollArea()
        self.detail_scroll.setObjectName("SkillDetailScroll")
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QStackedWidget()
        self.content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.detail_scroll.setWidget(self.content)
        detail_layout.addWidget(self.detail_scroll, 1)
        self.domain_page = QWidget(); domain_layout = QVBoxLayout(self.domain_page)
        domain_layout.setContentsMargins(0, 0, 0, 0); domain_layout.setSpacing(9)
        self.domain_page.setObjectName("SkillDomainPage")
        self.domain_toggle = self._button("⌄ 领域技能内容", self.toggle_domain_content)
        self.domain_toggle.setObjectName("SkillDomainToggle")
        domain_layout.addWidget(self.domain_toggle)
        self.domain_fields = QWidget(); fields_layout = QVBoxLayout(self.domain_fields)
        fields_layout.setContentsMargins(0, 0, 0, 0); fields_layout.setSpacing(9)
        self.skill_id = self._field(fields_layout, "技能 ID", QLineEdit())
        self.description = self._field(fields_layout, "简介", QPlainTextEdit())
        self.description.setFixedHeight(66)
        self.when = self._field(fields_layout, "适用场景", QPlainTextEdit())
        self.when.setFixedHeight(66)
        self.workflow = self._field(fields_layout, "工作流配置（JSON，可留空）", QPlainTextEdit())
        self.workflow.setFixedHeight(132)
        self.stage_toggle = self._button("⌄ 执行阶段指令", self.toggle_stages)
        self.stage_toggle.setObjectName("SkillDomainToggle")
        fields_layout.addWidget(self.stage_toggle)
        self.tabs = QTabWidget(); self.tabs.setObjectName("SkillLibraryStages")
        self.stage_edits = {}
        for key, label in STAGES:
            edit = QPlainTextEdit(); edit.setPlaceholderText(f"填写{label}阶段的指令…")
            self.stage_edits[key] = edit
            self.tabs.addTab(edit, label)
        self.tabs.setMinimumHeight(286)
        fields_layout.addWidget(self.tabs, 1)
        domain_layout.addWidget(self.domain_fields, 1)
        self.content.addWidget(self.domain_page)

        self.system_page = QWidget(); system_layout = QVBoxLayout(self.system_page)
        system_layout.setContentsMargins(0, 0, 0, 0)
        self.system_page.setObjectName("SkillSystemPage")
        self.system_toggle = self._button("⌄ 系统能力定义 · 只读", self.toggle_system_content)
        self.system_toggle.setObjectName("SkillSystemToggle")
        system_layout.addWidget(self.system_toggle)
        self.system_text = QPlainTextEdit(); self.system_text.setReadOnly(True)
        self.system_text.setObjectName("SkillSystemText")
        system_layout.addWidget(self.system_text, 1)
        self.content.addWidget(self.system_page)
        body.addWidget(detail, 1)
        root.addLayout(body, 1)
        self.skill_id.textChanged.connect(self._mark_dirty)
        for field in (self.description, self.when, self.workflow, *self.stage_edits.values()):
            field.textChanged.connect(self._mark_dirty)
        self.reload()

    def _button(self, label, callback, *, primary=False):
        button = QPushButton(label)
        button.setObjectName("SkillLibraryPrimary" if primary else "SkillLibraryButton")
        button.clicked.connect(callback)
        return button

    def _field(self, layout, label, widget):
        caption = QLabel(label); caption.setObjectName("SkillLibraryFieldLabel")
        layout.addWidget(caption)
        layout.addWidget(widget)
        widget.setObjectName("SkillDomainText")
        return widget

    def _mark_dirty(self, *_):
        if self._loading_fields or not (self.editing or self.creating):
            return
        self._dirty = True
        self._update_actions()

    def toggle_group(self, item):
        key = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(key, tuple) or key[0] != "group":
            return
        group = key[1]
        if group in self.collapsed_groups:
            self.collapsed_groups.remove(group)
        else:
            self.collapsed_groups.add(group)
        self.refresh_catalog(preferred=self.current_key)

    def toggle_domain_content(self):
        visible = self.domain_fields.isHidden()
        self.domain_fields.setVisible(visible)
        self.domain_toggle.setText(("⌄" if visible else "›") + " 领域技能内容")
        self._sync_content_height()

    def toggle_stages(self):
        visible = self.tabs.isHidden()
        self.tabs.setVisible(visible)
        self.stage_toggle.setText(("⌄" if visible else "›") + " 执行阶段指令")
        self._sync_content_height()

    def toggle_system_content(self):
        visible = self.system_text.isHidden()
        self.system_text.setVisible(visible)
        self.system_toggle.setText(("⌄" if visible else "›") + " 系统能力定义 · 只读")
        self._sync_content_height()

    def _sync_content_height(self):
        if self.content.currentWidget() is self.domain_page:
            minimum = (52 if self.domain_fields.isHidden() else
                       700 if self.tabs.isHidden() else 1010)
        else:
            minimum = 52 if self.system_text.isHidden() else 690
        self.content.setMinimumHeight(minimum)
        self.content.updateGeometry()

    def confirm_leave(self):
        if not (self.editing or self.creating):
            return True
        if not self._discard_changes():
            return False
        self.cancel_edit()
        return True

    def _saved_status(self, skill_id):
        window = self.window()
        if hasattr(window, "statusBar"):
            window.statusBar().showMessage(f"已保存 · {skill_id}")

    def reload(self, preferred=None):
        try:
            self.entries = list_skills() + list_disabled_skills()
        except (OSError, ValueError) as exc:
            self._error("读取技能库失败", exc)
            return
        if preferred:
            self.collapsed_groups.discard("domain" if preferred[0] == "domain" else
                                          "disabled" if preferred[0] == "disabled" else "system")
        self.current_data = None
        self.refresh_catalog(preferred=preferred)

    def refresh_catalog(self, _text=None, *, preferred=None):
        if not hasattr(self, "entries"):
            return
        selected = preferred or self.current_key
        term = self.search.text().strip().casefold()
        self._loading = True
        self.catalog.clear()
        for category, heading in (("domain", "领域技能"),
                                  ("system", "系统能力 · 只读"),
                                  ("disabled", "已停用领域技能")):
            entries = [entry for entry in self.entries
                       if ("disabled" if entry.get("disabled") else
                           "domain" if entry["category"] == "domain" else "system") == category
                       and term in " ".join(str(entry.get(key, "")) for key in
                                            ("id", "description", "when")).casefold()]
            if not entries:
                continue
            collapsed = category in self.collapsed_groups and not term
            group = QListWidgetItem(f"{'›' if collapsed else '⌄'}  {heading}  {len(entries)}")
            group.setFlags(Qt.ItemFlag.ItemIsEnabled)
            group.setData(Qt.ItemDataRole.UserRole, ("group", category))
            group.setForeground(QColor(theme_color("#66ddda" if category == "domain" else "#a6b8ce")))
            group.setBackground(QColor(theme_color("#17313c" if category == "domain" else "#252d36")))
            self.catalog.addItem(group)
            if collapsed:
                continue
            for entry in entries:
                badge = ("已停用" if entry.get("disabled") else
                         "系统" if entry["origin"] == "system" else
                         "用户覆盖" if entry["overridden"] else
                         "用户" if entry["origin"] == "user" else "内置")
                short = entry["description"].replace("\n", " ")
                short = short[:18] + "…" if len(short) > 18 else short
                item = QListWidgetItem(f"{entry['id']}   ·   {badge}\n{short}")
                item_key = ("disabled" if entry.get("disabled") else entry["category"], entry["id"])
                item.setData(Qt.ItemDataRole.UserRole, item_key)
                item.setToolTip(entry["when"])
                item.setForeground(QColor(theme_color("#eaf4ff" if category == "domain" else "#bfc9d4")))
                item.setBackground(QColor(theme_color("#172736" if category == "domain" else "#202b34")))
                self.catalog.addItem(item)
                if selected == item_key:
                    self.catalog.setCurrentItem(item)
        if self.catalog.currentItem() is None:
            for row in range(self.catalog.count()):
                item = self.catalog.item(row)
                key = item.data(Qt.ItemDataRole.UserRole)
                if key and key[0] != "group":
                    self.catalog.setCurrentItem(item)
                    break
        self._loading = False
        if self.catalog.currentItem() is None:
            self.current_key = self.current_data = None
            self.name.setText("没有匹配的技能")
            self.origin.clear()
            self.hint.setText("调整搜索词，或导入、新建一个领域技能。")
            self.content.hide()
            self._update_actions()
            return
        self.content.show()
        self.select_item(self.catalog.currentItem(), None)

    def refresh_palette(self):
        """Recolor existing catalog rows after an application theme change."""
        for row in range(self.catalog.count()):
            item = self.catalog.item(row)
            key = item.data(Qt.ItemDataRole.UserRole)
            if not key:
                continue
            category = key[1] if key[0] == "group" else key[0]
            domain = category == "domain"
            if key[0] == "group":
                foreground, background = (("#66ddda", "#17313c") if domain else
                                          ("#a6b8ce", "#252d36"))
            else:
                foreground, background = (("#eaf4ff", "#172736") if domain else
                                          ("#bfc9d4", "#202b34"))
            item.setForeground(QColor(theme_color(foreground)))
            item.setBackground(QColor(theme_color(background)))

    def select_item(self, item, previous):
        if self._loading or item is None:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if key is None or key[0] == "group" or (key == self.current_key and self.current_data is not None and not self.creating):
            return
        if (self.editing or self.creating) and not self._discard_changes():
            self._loading = True
            if previous is not None:
                self.catalog.setCurrentItem(previous)
            self._loading = False
            return
        self._load_key(key)

    def _load_key(self, key):
        if key[0] == "disabled":
            entry = next((item for item in self.entries if item["id"] == key[1] and
                          item.get("disabled")), None)
            if entry is None:
                return
            self.current_key = key
            self.current_data = dict(entry)
            self.editing = self.creating = False
            self._dirty = False
            self._show_data()
            return
        try:
            data = read_skill(key[1], key[0])
        except (OSError, ValueError) as exc:
            self._error("读取技能失败", exc)
            return
        self.current_key, self.current_data = key, data
        self.editing = self.creating = False
        self._dirty = False
        self._show_data()

    def _show_data(self):
        data = self.current_data
        if data is None:
            return
        disabled = bool(data.get("disabled"))
        domain = data["category"] == "domain" and not disabled
        self.content.setCurrentWidget(self.domain_page if domain else self.system_page)
        self._sync_content_height()
        self.name.setText(data["id"] if not self.creating else "新建领域技能")
        self.origin.setText("已停用" if disabled else "系统只读" if not domain else
                            "用户覆盖" if data.get("overridden") else
                            "用户" if data["origin"] == "user" else "内置")
        self.hint.setText(("该内置领域技能已停用，不会参与研究任务。点击恢复可重新启用。" if disabled else
                           "系统能力由程序提供，可查看与导出定义。" if not domain else
                           "内置技能可编辑并保存为用户覆盖版本。" if data["origin"] == "builtin" else
                           "可编辑或停用该技能。" if data.get("overridden") else
                           "用户技能可编辑、导出或删除。"))
        self._loading_fields = True
        if domain:
            manifest, instructions = data["manifest"], data["instructions"]
            self.skill_id.setText(manifest["id"])
            self.description.setPlainText(manifest["description"])
            self.when.setPlainText(manifest["when"])
            self.workflow.setPlainText(json.dumps(manifest.get("workflow", {}), ensure_ascii=False, indent=2))
            for key, _ in STAGES:
                self.stage_edits[key].setPlainText(instructions[key])
        elif disabled:
            self.system_text.setPlainText(
                f"技能 ID：{data['id']}\n\n简介：{data['description']}\n\n适用场景：{data['when']}\n\n状态：已停用")
        else:
            self.system_text.setPlainText(json.dumps(data["spec"], ensure_ascii=False, indent=2))
        self._loading_fields = False
        self._update_actions()

    def _update_actions(self):
        data = self.current_data
        domain = data is not None and data["category"] == "domain" and not data.get("disabled")
        editing = self.editing or self.creating
        for widget in (self.skill_id, self.description, self.when, self.workflow,
                       *self.stage_edits.values()):
            widget.setReadOnly(not editing)
        self.skill_id.setReadOnly(not self.creating)
        self.catalog.setEnabled(not editing)
        self.search.setEnabled(not editing)
        self.import_button.setEnabled(not editing)
        self.new_button.setEnabled(not editing)
        self.export_button.setVisible(bool(data) and not editing and not data.get("disabled"))
        self.edit_button.setVisible(domain and not editing)
        self.delete_button.setVisible(domain and not editing)
        self.delete_button.setText("停用" if domain and
                                   (data["origin"] == "builtin" or data.get("overridden"))
                                   else "删除")
        self.restore_button.setVisible(bool(data) and bool(data.get("disabled")) and not editing)
        self.save_button.setVisible(editing)
        self.save_button.setEnabled(editing and self._dirty)
        self.cancel_button.setVisible(editing)

    def _discard_changes(self):
        if not self._dirty:
            return True
        result = QMessageBox.question(self, "放弃修改？", "当前技能尚未保存，确定放弃修改吗？",
                                      QMessageBox.StandardButton.Discard |
                                      QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        return result == QMessageBox.StandardButton.Discard

    def new_skill(self):
        if self.editing and not self._discard_changes():
            return
        self.current_key = None
        self.current_data = {"id": "", "category": "domain", "origin": "user",
                             "manifest": {"id": "", "description": "", "when": ""},
                             "instructions": {key: "" for key, _ in STAGES}}
        self.creating, self.editing = True, False
        self._dirty = False
        self._show_data()
        self.origin.setText("新建")
        self.hint.setText("填写技能 ID、简介、适用场景和五段指令后保存。")
        self.skill_id.setFocus()

    def edit_current(self):
        if self.current_data is None or self.current_data["category"] != "domain":
            return
        self.editing = True
        self._dirty = False
        self._update_actions()
        self.description.setFocus()

    def cancel_edit(self):
        if self.creating:
            self.creating = False
            self._dirty = False
            self.current_data = None
            self.refresh_catalog()
        elif self.current_key:
            self._load_key(self.current_key)

    def save_current(self):
        if not (self.editing or self.creating) or not self._dirty:
            return
        try:
            workflow_text = self.workflow.toPlainText().strip()
            workflow = json.loads(workflow_text) if workflow_text else {}
            manifest = {"id": self.skill_id.text().strip(),
                        "description": self.description.toPlainText().strip(),
                        "when": self.when.toPlainText().strip()}
            if workflow:
                manifest["workflow"] = workflow
            instructions = {key: self.stage_edits[key].toPlainText().strip()
                            for key, _ in STAGES}
            if self.creating and any(entry["id"] == manifest["id"] and
                                     entry["category"] == "domain" for entry in self.entries):
                raise ValueError("技能 ID 已存在；请选中已有技能进行编辑。")
            saved = save_domain_skill(manifest, instructions)
        except (OSError, ValueError, TypeError) as exc:
            self._error("保存技能失败", exc)
            return
        self.editing = self.creating = False
        preferred = ("domain", saved["id"])
        self.current_key = None
        self.current_data = None
        self.reload(preferred=preferred)
        self._saved_status(saved["id"])

    def delete_current(self):
        data = self.current_data
        if data is None or data["category"] != "domain" or data.get("disabled"):
            return
        action = "停用内置领域技能" if data["origin"] == "builtin" or data.get("overridden") else "永久删除用户技能"
        answer = QMessageBox.question(self, "删除技能", f"确定{action}“{data['id']}”吗？",
                                      QMessageBox.StandardButton.Yes |
                                      QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_domain_skill(data["id"])
        except (OSError, ValueError) as exc:
            self._error("删除技能失败", exc)
            return
        preferred = (("disabled", data["id"]) if data["origin"] == "builtin" or
                     data.get("overridden") else None)
        self.current_key = None
        self.current_data = None
        self.reload(preferred=preferred)

    def restore_current(self):
        data = self.current_data
        if data is None or not data.get("disabled"):
            return
        try:
            restore_domain_skill(data["id"])
        except (OSError, ValueError) as exc:
            self._error("恢复技能失败", exc)
            return
        self.current_key = None
        self.current_data = None
        self.reload(preferred=("domain", data["id"]))

    def import_skill(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入领域技能", "", "技能包 (*.zip)")
        if not path:
            return
        try:
            loaded = import_domain_skill(path)
        except FileExistsError:
            answer = QMessageBox.question(self, "覆盖已有技能？",
                                          "同 ID 的用户技能已存在。确定用导入文件覆盖吗？",
                                          QMessageBox.StandardButton.Yes |
                                          QMessageBox.StandardButton.Cancel,
                                          QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Yes:
                return
            try:
                loaded = import_domain_skill(path, replace=True)
            except (OSError, ValueError, TypeError) as exc:
                self._error("导入技能失败", exc); return
        except (OSError, ValueError, TypeError) as exc:
            self._error("导入技能失败", exc); return
        self.reload(preferred=("domain", loaded["id"]))

    def export_current(self):
        if self.current_data is None:
            return
        data = self.current_data
        path, _ = QFileDialog.getSaveFileName(
            self, "导出技能", f"{data['id']}.zip", "技能包 (*.zip)")
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"
        try:
            export_skill(data["id"], path, data["category"])
        except (OSError, ValueError, TypeError) as exc:
            self._error("导出技能失败", exc)

    def _error(self, title, error):
        QMessageBox.warning(self, title, str(error))
