"""System settings UI and model profile editing for the reader window."""

import copy
import json
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QSignalBlocker, QTimer
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget,
    QMessageBox, QPushButton, QScrollArea, QSpinBox, QStackedWidget,
    QVBoxLayout, QWidget,
)

from paperreader.services.lazy import keyring
from paperreader.services.network import complete
from paperreader.logger import configure_logging, export_logs, limits
from paperreader.services.profiles import (
    active_profile, export_profiles, import_profiles, new_profile,
)
from paperreader.services.themes import THEMES
from paperreader.ui.markdown import MarkdownBrowser
from paperreader.ui.typography import FONT_OPTIONS, SIZE_OPTIONS


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

    existing = getattr(window, "_settings_dialog", None)
    if existing is not None and existing.isVisible():
        existing.raise_()
        existing.activateWindow()
        return existing

    dialog = SettingsDialog()
    window._settings_dialog = dialog
    dialog.setWindowTitle("系统设置")
    dialog.resize(940, 700)
    resize_settings_dialog(dialog, window.profile_config["font_size"])
    dialog.setMinimumWidth(820)
    layout = QHBoxLayout(dialog)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    navigation = QListWidget()
    navigation.setObjectName("SettingsNavigation")
    navigation.setFixedWidth(166)
    navigation.addItems(["常规设置", "模型设置", "搜索 API"])
    layout.addWidget(navigation)
    pages = QStackedWidget()
    layout.addWidget(pages, 1)

    def settings_page(title_text, description):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(26, 24, 26, 20)
        page_layout.setSpacing(14)
        title = settings_heading(title_text)
        title.setObjectName("SettingsPageTitle")
        page_layout.addWidget(title)
        intro = QLabel(description)
        intro.setObjectName("SettingsPageSubtitle")
        intro.setWordWrap(True)
        page_layout.addWidget(intro)
        scroll = QScrollArea()
        scroll.setObjectName("SettingsScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_content = QWidget()
        scroll_content.setObjectName("SettingsScrollContent")
        scroll_row = QHBoxLayout(scroll_content)
        scroll_row.setContentsMargins(0, 4, 0, 4)
        scroll_row.addStretch(1)
        cards = QWidget()
        cards.setObjectName("SettingsCards")
        cards.setMaximumWidth(690)
        card_layout = QVBoxLayout(cards)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(14)
        scroll_row.addWidget(cards, 20)
        scroll_row.addStretch(1)
        scroll.setWidget(scroll_content)
        page_layout.addWidget(scroll, 1)
        return page, page_layout, card_layout

    def settings_card(target_layout, title_text, description):
        card = QFrame()
        card.setObjectName("SettingsCard")
        content = QVBoxLayout(card)
        content.setContentsMargins(20, 18, 20, 18)
        content.setSpacing(11)
        heading = QLabel(title_text)
        heading.setObjectName("SettingsCardTitle")
        content.addWidget(heading)
        if description:
            detail = QLabel(description)
            detail.setObjectName("SettingsCardDescription")
            detail.setWordWrap(True)
            content.addWidget(detail)
        grid = QGridLayout()
        grid.setContentsMargins(0, 5, 0, 0)
        grid.setHorizontalSpacing(22)
        grid.setVerticalSpacing(13)
        grid.setColumnStretch(0, 1)
        content.addLayout(grid)
        target_layout.addWidget(card)
        return content, grid

    def settings_row(grid, row, label_text, detail_text, control):
        labels = QWidget()
        labels_layout = QVBoxLayout(labels)
        labels_layout.setContentsMargins(0, 0, 0, 0)
        labels_layout.setSpacing(3)
        label = QLabel(label_text)
        label.setObjectName("SettingsFieldLabel")
        labels_layout.addWidget(label)
        detail = QLabel(detail_text)
        detail.setObjectName("SettingsFieldDetail")
        detail.setWordWrap(True)
        labels_layout.addWidget(detail)
        control.setMinimumWidth(250)
        control.setMaximumWidth(320)
        grid.addWidget(labels, row, 0)
        grid.addWidget(control, row, 1)

    general, general_layout, card_layout = settings_page(
        "常规设置", "调整阅读工作台的外观与本地日志。")
    _, appearance = settings_card(card_layout, "外观", "字体与字号作用于界面和 AI 内容；PDF 原文保留论文自身排版。")
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
    settings_row(appearance, 0, "界面主题", "选择配色和界面风格", theme_picker)
    font_picker = QComboBox()
    font_picker.setObjectName("FontPicker")
    font_picker.setView(QListView(font_picker))
    font_picker.view().setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    for key, label, _ in FONT_OPTIONS:
        font_picker.addItem(label, key)
    font_picker.setCurrentIndex(font_picker.findData(window.profile_config["font_family"]))
    settings_row(appearance, 1, "字体", "默认跟随操作系统", font_picker)
    size_picker = QComboBox()
    size_picker.setObjectName("FontSizePicker")
    size_picker.setView(QListView(size_picker))
    size_picker.view().setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    for key, label, _ in SIZE_OPTIONS:
        size_picker.addItem(label, key)
    size_picker.setCurrentIndex(size_picker.findData(window.profile_config["font_size"]))
    settings_row(appearance, 2, "字号", "按屏幕尺寸与观看距离选择", size_picker)
    for picker in (font_picker, size_picker):
        view = picker.view()
        view.ensurePolished()
        height = sum(view.sizeHintForRow(i) for i in range(picker.count()))
        view.setMinimumHeight(height + 2 * view.frameWidth() + 8)
    stored_logs = window.library.config()
    try:
        initial_size, initial_days = limits(stored_logs.get("log_size_mb", 10),
                                            stored_logs.get("log_retention_days", 14))
    except ValueError:
        initial_size, initial_days = 10, 14
    log_content, log_form = settings_card(card_layout, "日志", "控制本地诊断日志的占用空间与保留时间。")
    log_size = QSpinBox()
    log_size.setObjectName("LogSizeMb")
    log_size.setRange(1, 100)
    log_size.setSuffix(" MB")
    log_size.setValue(initial_size)
    log_days = QSpinBox()
    log_days.setObjectName("LogRetentionDays")
    log_days.setRange(1, 90)
    log_days.setSuffix(" 天")
    log_days.setValue(initial_days)
    settings_row(log_form, 0, "总大小上限", "超过上限后清理较早记录", log_size)
    settings_row(log_form, 1, "保留周期", "到期后自动清理", log_days)
    actions = QHBoxLayout()
    save_logs = QPushButton("保存设置")
    save_logs.setObjectName("SettingsSaveButton")
    export_button = QPushButton("导出全部日志")
    actions.addStretch()
    actions.addWidget(export_button)
    actions.addWidget(save_logs)
    log_content.addLayout(actions)

    def save_log_settings():
        try:
            size_mb, days = limits(log_size.value(), log_days.value())
            window.library.save_config(dict(window.library.config(), log_size_mb=size_mb,
                                            log_retention_days=days))
            configure_logging(window.library.root, size_mb=size_mb, retention_days=days)
            window.statusBar().showMessage("日志设置已保存", 3000)
        except (OSError, ValueError) as exc:
            window.error("日志设置保存失败：" + str(exc))

    def export_all_logs():
        path, _ = QFileDialog.getSaveFileName(dialog, "导出全部日志", "PaperReader-日志.zip", "ZIP 文件 (*.zip)")
        if not path:
            return
        try:
            count = export_logs(path)
            window.statusBar().showMessage(f"已导出 {count} 个日志文件", 5000)
        except (OSError, ValueError, RuntimeError) as exc:
            window.error("日志导出失败：" + str(exc))

    save_logs.clicked.connect(save_log_settings)
    export_button.clicked.connect(export_all_logs)
    card_layout.addStretch()
    close = QPushButton("关闭")
    close.setObjectName("SettingsCloseButton")
    close.clicked.connect(dialog.reject)
    footer = QHBoxLayout()
    footer.addStretch()
    footer.addWidget(close)
    general_layout.addLayout(footer)
    pages.addWidget(general)

    models, _, model_cards = settings_page(
        "模型设置", "管理模型连接；API Key 保存在系统密钥库，保存时才写入修改。")
    _, model_grid = settings_card(model_cards, "模型配置", "")
    model_cards.addStretch()
    pages.addWidget(models)

    from paperreader.research_agent.search import (
        BRIGHTDATA_ZONE_ACCOUNT, SEARCH_ACCOUNTS, SEARCH_ENGINES, brightdata_zone, search_key,
    )

    search, search_layout, search_cards = settings_page(
        "搜索 API", "配置研究空间使用的外部网页搜索；论文检索使用 Crossref，无需在此设置。")
    _, search_form = settings_card(search_cards, "网页搜索 · Bright Data",
                                   "设置 API Key、SERP Zone 和搜索引擎；密钥与 Zone 分别保存。")
    search_fields = [(provider + " API Key", account, search_key(provider), True)
                     for provider, account in SEARCH_ACCOUNTS.items()]
    search_fields.insert(1, ("Bright Data SERP Zone", BRIGHTDATA_ZONE_ACCOUNT,
                             brightdata_zone(), False))
    for index, (label, account, value, secret_field) in enumerate(search_fields):
        field = QLineEdit(value)
        field.setObjectName("SearchKey" if secret_field else "SearchZone")
        if secret_field:
            field.setEchoMode(QLineEdit.EchoMode.Password)
        save_key = QPushButton("保存")
        save_key.setObjectName("SettingsInlineSave")
        control = QWidget()
        row = QHBoxLayout()
        control.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(field, 1)
        row.addWidget(save_key)
        settings_row(search_form, index, label,
                     "用于网页搜索" if secret_field else "请求区名称，由 Bright Data 提供", control)

        def save_search_key(checked=False, field=field, account=account):
            try:
                secret = field.text().strip()
                if secret:
                    keyring.set_password("PaperReader", account, secret)
                else:
                    try:
                        keyring.delete_password("PaperReader", account)
                    except keyring.errors.PasswordDeleteError:
                        pass
                window.statusBar().showMessage("搜索 API 设置已保存", 3000)
            except keyring.errors.KeyringError:
                window.error("无法保存搜索 API Key，请检查系统密钥环。")

        save_key.clicked.connect(save_search_key)
    engine_picker = QComboBox()
    engine_picker.setObjectName("BrightDataEnginePicker")
    for identifier, label in SEARCH_ENGINES.items():
        engine_picker.addItem(label, identifier)
    engine_picker.setCurrentIndex(engine_picker.findData(window.profile_config.get("brightdata_engine", "bing")))
    settings_row(search_form, len(search_fields), "搜索引擎", "选择 Bing 或 Google", engine_picker)

    def save_search_engine(index):
        engine = engine_picker.itemData(index)
        if engine not in SEARCH_ENGINES:
            return
        try:
            window.library.save_config(dict(window.library.config(), brightdata_engine=engine))
        except (OSError, ValueError) as exc:
            window.error("无法保存搜索引擎设置：" + str(exc))
            with QSignalBlocker(engine_picker):
                engine_picker.setCurrentIndex(engine_picker.findData(
                    window.profile_config.get("brightdata_engine", "bing")))
            return
        window.profile_config["brightdata_engine"] = engine
        window.statusBar().showMessage("搜索引擎设置已保存", 3000)

    engine_picker.currentIndexChanged.connect(save_search_engine)
    search_cards.addStretch()
    close_search = QPushButton("关闭")
    close_search.setObjectName("SettingsCloseButton")
    close_search.clicked.connect(dialog.reject)
    search_footer = QHBoxLayout()
    search_footer.addStretch()
    search_footer.addWidget(close_search)
    search_layout.addLayout(search_footer)
    pages.addWidget(search)

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
            model_grid.addLayout(form, 0, 0, 1, 2)
        pages.setCurrentIndex(index)

    def choose_theme():
        if not window.change_theme(theme_picker.currentData()):
            with QSignalBlocker(theme_picker):
                theme_picker.setCurrentIndex(theme_picker.findData(window.profile_config["theme"]))

    theme_picker.currentIndexChanged.connect(choose_theme)
    typography_pending = False

    def choose_typography():
        nonlocal typography_pending
        if typography_pending:
            return
        font_key, size_key = font_picker.currentData(), size_picker.currentData()
        if (font_key, size_key) == (window.profile_config["font_family"],
                                    window.profile_config["font_size"]):
            return
        typography_pending = True
        overlay = QFrame(dialog)
        overlay.setObjectName("TypographyOverlay")
        overlay.setGeometry(dialog.rect())
        overlay_layout = QVBoxLayout(overlay)
        message = QLabel("正在应用字体与字号…")
        message.setObjectName("TypographyOverlayMessage")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overlay_layout.addWidget(message)
        overlay.show()
        overlay.raise_()
        overlay.repaint()

        def apply_selection():
            nonlocal typography_pending
            try:
                if not window.change_typography(font_key, size_key):
                    with QSignalBlocker(font_picker), QSignalBlocker(size_picker):
                        font_picker.setCurrentIndex(font_picker.findData(window.profile_config["font_family"]))
                        size_picker.setCurrentIndex(size_picker.findData(window.profile_config["font_size"]))
                resize_settings_dialog(dialog, window.profile_config["font_size"])
                overlay.setGeometry(dialog.rect())
            finally:
                def finish_overlay():
                    nonlocal typography_pending
                    overlay.hide()
                    overlay.deleteLater()
                    typography_pending = False
                    if (font_picker.currentData(), size_picker.currentData()) != (
                            window.profile_config["font_family"], window.profile_config["font_size"]):
                        QTimer.singleShot(0, choose_typography)

                QTimer.singleShot(0, finish_overlay)

        QTimer.singleShot(0, apply_selection)

    font_picker.currentIndexChanged.connect(choose_typography)
    size_picker.currentIndexChanged.connect(choose_typography)
    navigation.currentRowChanged.connect(show_page)
    navigation.setCurrentRow(0)

    def finish(result):
        try:
            if result and save_model:
                save_model()
        finally:
            if getattr(window, "_settings_dialog", None) is dialog:
                window._settings_dialog = None
            dialog.deleteLater()

    dialog.finished.connect(finish)
    dialog.show()
    return dialog


def settings_heading(text):
    label = QLabel(text)
    label.setObjectName("SettingsHeading")
    return label


def resize_settings_dialog(dialog, size_key):
    """Use more space for larger text when the current display provides it."""
    dimensions = {
        "standard": (940, 700),
        "medium": (980, 750),
        "large": (1040, 810),
        "extra-large": (1120, 880),
    }
    width, height = dimensions.get(size_key, dimensions["standard"])
    screen = dialog.screen()
    if screen is not None:
        available = screen.availableGeometry()
        if available.width() >= width + 32 and available.height() >= height + 32:
            dialog.resize(width, height)



def build_model_settings(window, dialog, form, job_type):
    """Build an editable profile draft; return its save callback."""

    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setHorizontalSpacing(16)
    form.setVerticalSpacing(8)
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
    actions.setContentsMargins(0, 0, 0, 0)
    actions.setSpacing(7)
    add.setMaximumWidth(92); remove.setMaximumWidth(92)
    actions.addWidget(picker, 1); actions.addWidget(add); actions.addWidget(remove)
    form.addRow("已保存模型", actions); form.addRow("配置名称", name)
    form.addRow("API 基础地址（包含 /v1）", endpoint); form.addRow("模型名称", model); form.addRow("API Key", key)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存配置")
    buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("SettingsSaveButton")
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
    buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
    import_button = QPushButton("导入配置"); import_button.setObjectName("ImportModelConfig")
    export_button = QPushButton("导出配置"); export_button.setObjectName("ExportModelConfig")
    footer = QHBoxLayout(); footer.addWidget(import_button); footer.addWidget(export_button)
    footer.addStretch(1); footer.addWidget(buttons)
    form.addRow(footer)
    test = QPushButton("测试模型连接")
    test.setMaximumWidth(150)
    status = MarkdownBrowser(); status.setMinimumHeight(110); status.setMaximumHeight(150)
    status.setObjectName("SettingsConnectionStatus")
    status.set_markdown("使用当前输入测试，无需先保存；会向 /chat/completions 发送一条简短的流式请求，可能产生少量费用。")
    form.addRow("连接测试", test); form.addRow(status)
    def stash():
        profile = draft["profiles"][selected[0]]
        profile.update(name=name.text().strip() or "未命名模型", endpoint=endpoint.text().strip(), model=model.text().strip())
        secrets[profile["id"]] = key.text()
        picker.setItemText(selected[0], profile["name"])
    def show_profile(index):
        selected[0] = index; profile = draft["profiles"][index]
        name.setText(profile["name"]); endpoint.setText(profile["endpoint"]); model.setText(profile["model"])
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
        config = {"endpoint": endpoint.text().strip(), "model": model.text().strip()}
        secret = key.text()
        test.setEnabled(False); buttons.setEnabled(False); dialog.testing = True
        for widget in (picker, add, remove, import_button, export_button, name, endpoint, model, key): widget.setEnabled(False)
        status.set_markdown("正在测试流式 Chat Completions 接口…")
        job = job_type(lambda emit: complete(config, secret, [{"role": "user", "content": "Reply only OK."}], on_chunk=emit), streaming=True)
        chunks = []
        def progress(text):
            chunks.append(text); status.set_markdown("正在测试流式 Chat Completions 接口…\n\n" + "".join(chunks))
        job.signals.chunk.connect(progress)
        dialog.test_job = job
        def finished(message):
            test.setEnabled(True); buttons.setEnabled(True); dialog.testing = False
            for widget in (picker, add, remove, import_button, export_button, name, endpoint, model, key): widget.setEnabled(True)
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
            draft.update({key: value for key, value in window.library.config().items()
                          if key not in ('profiles', 'active_id', 'endpoint', 'model', 'theme', 'max_input_chars')})
            window.library.save_config(draft)
            old_profiles = window.profile_config["profiles"]
            window.profile_config = draft; window.config = active_profile(draft); window.refresh_models()
            for old in old_profiles:
                if old["id"] not in [p["id"] for p in draft["profiles"]]:
                    try: keyring.delete_password("PaperReader", old["key_account"])
                    except keyring.errors.PasswordDeleteError: pass
        except Exception as exc: window.error("配置保存失败：" + str(exc))
    return save
