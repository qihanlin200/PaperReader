"""System settings UI and model profile editing for the reader window."""

import copy
import json
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget, QMessageBox,
    QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from paperreader.services.analysis import input_limit
from paperreader.services.lazy import keyring
from paperreader.services.network import complete
from paperreader.services.profiles import (
    active_profile, export_profiles, import_profiles, new_profile,
)
from paperreader.services.themes import THEMES
from paperreader.ui.markdown import MarkdownBrowser
from paperreader.ui.theme import ThemeSwitch


class SettingsDialog(QDialog):
    """Keep settings open while a connection test is running."""

    testing = False

    def reject(self):
        if not self.testing:
            super().reject()

    def closeEvent(self, event):
        if self.testing:
            event.ignore()
        else:
            super().closeEvent(event)


def open_settings(window):
    """Show general settings and lazily build the model editor."""

    dialog = SettingsDialog(window)
    dialog.setWindowTitle("系统设置")
    dialog.resize(1000, 570)
    dialog.setMinimumWidth(820)
    layout = QHBoxLayout(dialog)
    navigation = QListWidget()
    navigation.setObjectName("SettingsNavigation")
    navigation.setFixedWidth(152)
    navigation.addItems(["常规设置", "模型设置"])
    layout.addWidget(navigation)
    pages = QStackedWidget()
    layout.addWidget(pages, 1)

    general = QWidget()
    general_layout = QVBoxLayout(general)
    general_layout.addWidget(settings_heading("常规设置"))
    appearance = QFormLayout()
    theme_picker = QComboBox()
    theme_picker.setObjectName("ThemePicker")
    theme_view = QListView(theme_picker)
    theme_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    theme_picker.setView(theme_view)
    for pack in THEMES.values():
        theme_picker.addItem(pack.name, pack.identifier)
    theme_view.ensurePolished()
    # Include the styled row padding in Qt's popup height.
    rows_height = sum(theme_view.sizeHintForRow(i) for i in range(theme_picker.count()))
    theme_view.setMinimumHeight(rows_height + 2 * theme_view.frameWidth())
    theme_picker.setCurrentIndex(theme_picker.findData(window.profile_config["theme"]))
    appearance.addRow("界面主题", theme_picker)
    pdf_follow = ThemeSwitch("跟随界面主题")
    pdf_follow.setObjectName("PdfFollowTheme")
    pdf_follow.setChecked(window.profile_config["pdf_follow_theme"])
    pdf_follow.setToolTip("关闭后，PDF 页面始终显示白底黑字。")
    appearance.addRow("论文背景", pdf_follow)
    general_layout.addLayout(appearance)
    hint = QLabel("关闭论文背景跟随主题后，PDF 始终显示白底黑字。设置即时生效并保存在本机。")
    hint.setObjectName("Muted")
    general_layout.addWidget(hint)
    general_layout.addStretch()
    close = QPushButton("关闭")
    close.clicked.connect(dialog.reject)
    general_layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
    pages.addWidget(general)

    models = QWidget()
    model_layout = QVBoxLayout(models)
    model_layout.addWidget(settings_heading("模型设置"))
    pages.addWidget(models)

    save_model = None

    def show_page(index):
        nonlocal save_model
        if index == 1 and save_model is None:
            if window.busy:
                navigation.setCurrentRow(0)
                window.error("已有后台任务，请等待完成后设置模型。")
                return
            form = QFormLayout()
            save_model = window.build_model_settings(dialog, form)
            if save_model is None:
                navigation.setCurrentRow(0)
                return
            model_layout.addLayout(form, 1)
        pages.setCurrentIndex(index)

    def choose_theme():
        if not window.change_theme(theme_picker.currentData()):
            with QSignalBlocker(theme_picker):
                theme_picker.setCurrentIndex(theme_picker.findData(window.profile_config["theme"]))

    def choose_pdf_follow(enabled):
        if not window.change_pdf_follow_theme(enabled):
            with QSignalBlocker(pdf_follow):
                pdf_follow.setChecked(window.profile_config["pdf_follow_theme"])

    theme_picker.currentIndexChanged.connect(choose_theme)
    pdf_follow.toggled.connect(choose_pdf_follow)
    navigation.currentRowChanged.connect(show_page)
    navigation.setCurrentRow(0)
    if dialog.exec() and save_model:
        save_model()


def settings_heading(text):
    label = QLabel(text)
    label.setObjectName("SettingsHeading")
    return label



def build_model_settings(window, dialog, form, job_type):
    """Build an editable profile draft; return its save callback."""

    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    endpoint = QLineEdit(window.config["endpoint"]); model = QLineEdit(window.config["model"]); key = QLineEdit()
    endpoint.setObjectName("ModelEndpoint"); model.setObjectName("ModelName"); key.setObjectName("ModelKey")
    key.setEchoMode(QLineEdit.EchoMode.Password)
    try: key.setText(keyring.get_password("PaperReader", window.config.get("key_account", "api")) or "")
    except Exception as exc: window.error("系统密钥库不可用：" + str(exc)); return
    draft = copy.deepcopy(window.profile_config)
    secrets = {window.config["id"]: key.text()}
    selected = [next(i for i, p in enumerate(draft["profiles"]) if p["id"] == draft["active_id"])]
    picker = QComboBox(); picker.addItems([p["name"] for p in draft["profiles"]]); picker.setCurrentIndex(selected[0])
    name = QLineEdit(window.config["name"]); name.setObjectName("ProfileName")
    actions = QHBoxLayout(); add = QPushButton("新增配置"); remove = QPushButton("删除配置")
    actions.addWidget(add); actions.addWidget(remove)
    form.addRow("已保存模型", picker); form.addRow(actions); form.addRow("配置名称", name)
    form.addRow("API 基础地址（包含 /v1）", endpoint); form.addRow("模型名称", model); form.addRow("API Key", key)
    limit = QSpinBox(); limit.setObjectName("MaxInputChars"); limit.setRange(4096, 2000000); limit.setSingleStep(4096)
    limit.setValue(input_limit(window.config)); limit.setSuffix(" 字符")
    form.addRow("最大输入长度", limit)
    form.addRow(QLabel("按请求全部文本字符计（含提示词和历史），不是 Token；请低于服务商上下文上限并预留输出空间。"))
    form.addRow(QLabel("使用 Chat Completions 兼容接口；模型请求可能发送论文文本。"))
    http_hint = QLabel("内网模型可填写 http:// 地址；HTTP 会明文传输论文文本和已配置的 API Key。")
    http_hint.setWordWrap(True)
    form.addRow(http_hint)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
    import_button = QPushButton("导入配置"); import_button.setObjectName("ImportModelConfig")
    export_button = QPushButton("导出配置"); export_button.setObjectName("ExportModelConfig")
    footer = QHBoxLayout(); footer.addWidget(import_button); footer.addWidget(export_button)
    footer.addStretch(1); footer.addWidget(buttons)
    form.addRow(footer)
    test = QPushButton("测试模型连接")
    status = MarkdownBrowser(); status.setMinimumHeight(110); status.set_markdown("使用当前输入测试，无需先保存；会向 /chat/completions 发送一条简短的流式请求，可能产生少量费用。")
    form.addRow(test); form.addRow(status)
    def stash():
        profile = draft["profiles"][selected[0]]
        profile.update(name=name.text().strip() or "未命名模型", endpoint=endpoint.text().strip(), model=model.text().strip(), max_input_chars=limit.value())
        secrets[profile["id"]] = key.text()
        picker.setItemText(selected[0], profile["name"])
    def show_profile(index):
        selected[0] = index; profile = draft["profiles"][index]
        name.setText(profile["name"]); endpoint.setText(profile["endpoint"]); model.setText(profile["model"]); limit.setValue(input_limit(profile))
        try:
            secret = secrets.get(profile["id"])
            if secret is None: secret = keyring.get_password("PaperReader", profile["key_account"]) or ""
            key.setText(secret)
        except Exception as exc: key.clear(); window.error(str(exc))
        status.set_markdown("使用当前配置测试连接，结果不会自动保存。")
    def choose(index):
        if index < 0: return
        stash(); show_profile(index)
    picker.currentIndexChanged.connect(choose)
    def add_profile():
        stash(); profile = new_profile(); draft["profiles"].append(profile)
        picker.addItem(profile["name"]); picker.setCurrentIndex(len(draft["profiles"])-1)
    def remove_profile():
        if len(draft["profiles"]) == 1:
            window.error("至少保留一个模型配置。"); return
        index = selected[0]; draft["profiles"].pop(index)
        picker.blockSignals(True); picker.removeItem(index); selected[0] = min(index, len(draft["profiles"])-1)
        picker.setCurrentIndex(selected[0]); picker.blockSignals(False)
        show_profile(selected[0])
    add.clicked.connect(add_profile); remove.clicked.connect(remove_profile)
    def import_config():
        path, _ = QFileDialog.getOpenFileName(dialog, "导入模型配置", "", "JSON 文件 (*.json)")
        if not path: return
        try:
            source = Path(path)
            if source.stat().st_size > 1024 * 1024:
                raise ValueError("配置文件超过 1 MB。")
            profiles, active_id, imported_secrets = import_profiles(json.loads(source.read_text(encoding="utf-8")))
            draft["profiles"] = profiles; draft["active_id"] = active_id
            secrets.clear(); secrets.update(imported_secrets)
            picker.blockSignals(True); picker.clear(); picker.addItems([p["name"] for p in profiles])
            index = next(i for i, p in enumerate(profiles) if p["id"] == active_id)
            picker.setCurrentIndex(index); picker.blockSignals(False)
            show_profile(index)
            status.set_markdown("已载入模型配置。点击“保存”后生效；未随文件导入的 API Key 需要重新填写。")
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            window.error("导入配置失败：" + str(exc))
    def export_config():
        stash()
        prompt = QMessageBox(dialog)
        prompt.setWindowTitle("导出模型配置")
        prompt.setText("导出的配置文件是否包含 API Key？")
        prompt.setInformativeText("包含密钥时，文件会以明文保存 API Key。建议只在安全的本地位置保存。")
        without_key = prompt.addButton("不包含密钥", QMessageBox.ButtonRole.AcceptRole)
        with_key = prompt.addButton("包含 API Key（明文）", QMessageBox.ButtonRole.ActionRole)
        prompt.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        prompt.setDefaultButton(without_key)
        prompt.exec()
        choice = prompt.clickedButton()
        if choice not in (without_key, with_key): return
        path, _ = QFileDialog.getSaveFileName(dialog, "导出模型配置", "PaperReader-模型配置.json", "JSON 文件 (*.json)")
        if not path: return
        try:
            included = {}
            if choice is with_key:
                for profile in draft["profiles"]:
                    secret = secrets.get(profile["id"])
                    if secret is None:
                        secret = keyring.get_password("PaperReader", profile["key_account"]) or ""
                    if secret: included[profile["id"]] = secret
            document = export_profiles(draft, included)
            target = Path(path)
            descriptor, temporary = tempfile.mkstemp(prefix=".PaperReader-", suffix=".tmp", dir=target.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                    json.dump(document, file, ensure_ascii=False, indent=2)
                    file.write("\n")
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary): os.unlink(temporary)
            status.set_markdown("模型配置已导出。" + (" 文件包含明文 API Key，请妥善保管。" if choice is with_key else " 文件不包含 API Key。"))
        except (OSError, ValueError) as exc:
            window.error("导出配置失败：" + str(exc))
    import_button.clicked.connect(import_config); export_button.clicked.connect(export_config)
    def test_connection():
        config = {"endpoint": endpoint.text().strip(), "model": model.text().strip(), "max_input_chars": limit.value()}
        secret = key.text()
        test.setEnabled(False); buttons.setEnabled(False); dialog.testing = True
        for widget in (picker, add, remove, import_button, export_button, name, endpoint, model, key, limit): widget.setEnabled(False)
        status.set_markdown("正在测试流式 Chat Completions 接口…")
        job = job_type(lambda emit: complete(config, secret, [{"role": "user", "content": "Reply only OK."}], on_chunk=emit), streaming=True)
        chunks = []
        def progress(text):
            chunks.append(text); status.set_markdown("正在测试流式 Chat Completions 接口…\n\n" + "".join(chunks))
        job.signals.chunk.connect(progress)
        dialog.test_job = job
        def finished(message):
            test.setEnabled(True); buttons.setEnabled(True); dialog.testing = False
            for widget in (picker, add, remove, import_button, export_button, name, endpoint, model, key, limit): widget.setEnabled(True)
            status.set_markdown(message)
        job.signals.done.connect(lambda text: finished("**连接成功**：模型已返回流式文本响应。\n\n" + text))
        job.signals.error.connect(lambda text: finished("连接失败：" + text))
        window.pool.start(job)
    test.clicked.connect(test_connection)
    def save():
        try:
            stash()
            draft["active_id"] = draft["profiles"][selected[0]]["id"]
            draft["theme"] = window.profile_config["theme"]
            for profile in draft["profiles"]:
                if profile["id"] in secrets:
                    keyring.set_password("PaperReader", profile["key_account"], secrets[profile["id"]])
            window.library.save_config(draft)
            old_profiles = window.profile_config["profiles"]
            window.profile_config = draft; window.config = active_profile(draft); window.refresh_models()
            for old in old_profiles:
                if old["id"] not in [p["id"] for p in draft["profiles"]]:
                    try: keyring.delete_password("PaperReader", old["key_account"])
                    except keyring.errors.PasswordDeleteError: pass
        except Exception as exc: window.error("配置保存失败：" + str(exc))
    return save
