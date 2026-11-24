"""Papers behavior for the main window."""
from datetime import datetime
import json
from html import escape
from pathlib import Path
from urllib.parse import urlsplit
from paperreader.services.lazy import fitz
from PySide6.QtCore import QPoint, QSignalBlocker
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QListWidget, QLineEdit, QFileDialog, QInputDialog, QMessageBox, QDialogButtonBox, QApplication, QMenu, QProgressDialog, QSpacerItem, QSizePolicy
from PySide6.QtCore import Qt
from paperreader.services.network import download
from paperreader.ui.paper_list import PAPER_ID_ROLE, GROUP_ID_ROLE, MACOS
from paperreader.ui.work_rail import menu_symbol_icon
from paperreader.services.sessions import ensure_sessions
from paperreader.logger import get_logger

log = get_logger(__name__)

class PapersMixin:
    def persist(self):
        try:
            if self.paper: self.library.save(self.paper)
            self.statusBar().showMessage("已保存到本地")
        except Exception as exc: self.error("本地保存失败：" + str(exc))

    def reload(self, identifier=None, *, reopen=True, refresh_metadata=True):
        if refresh_metadata:
            if hasattr(self, "timer"): self.save_notes()
            self.all_papers = self.library.list_metadata()
        groups = self.library.list_groups()
        selected = next((p for p in self.all_papers if p["id"] == identifier), None)
        if reopen and selected:
            query = self.paper_search.text().strip().casefold().split()
            if any(word not in (selected["title"] + " " + selected["source"]).casefold() for word in query):
                with QSignalBlocker(self.paper_search): self.paper_search.clear()
        query = self.paper_search.text().strip().casefold().split()
        collapsed = self.search_collapsed_groups if query else self.collapsed_groups
        if reopen and selected:
            collapsed.discard(selected["group_id"] if selected["group_id"] is not None else -1)
        self.papers = [paper for paper in self.all_papers
                       if all(word in (paper["title"] + " " + paper["source"]).casefold() for word in query)]
        by_group = {group["id"]: [] for group in groups}
        ungrouped = []
        for paper in self.papers:
            by_group.get(paper["group_id"], ungrouped).append(paper)
        with QSignalBlocker(self.list):
            self.list.clear()
            for group in groups:
                papers = by_group[group["id"]]
                if papers or not query:
                    is_collapsed = group["id"] in collapsed
                    self.list.add_group(group["name"], group["id"], len(papers), group["pinned"], is_collapsed)
                    if not is_collapsed:
                        for paper in papers:
                            self.list.add_paper(paper["title"], paper["favorite"], paper["id"])
            if ungrouped or (groups and not query):
                if groups:
                    self.list.add_group("未分组", -1, len(ungrouped), collapsed=-1 in collapsed)
                if not groups or -1 not in collapsed:
                    for paper in ungrouped:
                        self.list.add_paper(paper["title"], paper["favorite"], paper["id"])
            row = self.row_for_paper(identifier)
            if not reopen and row >= 0:
                self.list.setCurrentRow(row)
        if reopen and row >= 0:
            self.list.setCurrentRow(row)
        self.update_reading_home()

    def paper_at_row(self, row):
        item = self.list.item(row)
        identifier = item.data(PAPER_ID_ROLE) if item else None
        return next((paper for paper in self.all_papers if paper["id"] == identifier), None)

    def row_for_paper(self, identifier):
        if not identifier: return -1
        return next((row for row in range(self.list.count())
                     if self.list.item(row).data(PAPER_ID_ROLE) == identifier), -1)

    def favorite_paper_at_row(self, row):
        paper = self.paper_at_row(row)
        if paper: self.toggle_favorite(paper)

    def toggle_group_item(self, item):
        group_id = item.data(GROUP_ID_ROLE)
        if group_id is None: return
        collapsed = self.search_collapsed_groups if self.paper_search.text().strip() else self.collapsed_groups
        if group_id in collapsed:
            collapsed.remove(group_id)
        else:
            collapsed.add(group_id)
        scroll = self.list.verticalScrollBar().value()
        self.reload(self.paper["id"] if self.paper else None, reopen=False)
        self.list.verticalScrollBar().setValue(scroll)

    def search_papers(self, _text=None):
        self.search_collapsed_groups.clear()
        current = self.paper["id"] if self.paper else None
        self.reload(current, reopen=False, refresh_metadata=False)

    def show_library_add_menu(self):
        menu = self.library_add_menu
        for action in menu.actions():
            action.setIcon(menu_symbol_icon(action.data()))
        button = self.library_add_button
        menu.exec(button.mapToGlobal(QPoint(button.width() - menu.sizeHint().width(), button.height() + 4)))

    def create_paper_group(self):
        dialog = QInputDialog(self)
        dialog.setWindowTitle("新建论文分组")
        dialog.setLabelText("分组名称：")
        dialog.setOkButtonText("创建"); dialog.setCancelButtonText("取消")
        dialog.setMinimumWidth(620); dialog.resize(680, 180)
        if not dialog.exec(): return
        try:
            self.library.create_group(dialog.textValue())
        except Exception as exc:
            self.error("创建分组失败：" + str(exc)); return
        current = self.paper["id"] if self.paper else None
        self.reload(current, reopen=False)
        self.statusBar().showMessage("已创建论文分组。")

    def move_paper_to_group(self, paper, group_id):
        try:
            self.library.set_group(paper["id"], group_id)
        except Exception as exc:
            self.error("移动论文失败：" + str(exc)); return
        current = self.paper["id"] if self.paper else None
        self.reload(current, reopen=False)

    def drop_papers_into_group(self, identifiers, group_id):
        visible = {paper["id"]: paper for paper in self.all_papers}
        to_move = [identifier for identifier in identifiers
                   if identifier in visible and visible[identifier]["group_id"] != group_id]
        if not to_move:
            return
        try:
            self.library.set_groups(to_move, group_id)
        except Exception as exc:
            self.error("移动论文失败：" + str(exc))
            return
        target = -1 if group_id is None else group_id
        self.collapsed_groups.discard(target)
        self.search_collapsed_groups.discard(target)
        current = self.paper["id"] if self.paper else None
        self.reload(current, reopen=False)
        row = self.row_for_paper(to_move[0])
        if row >= 0:
            self.list.scrollToItem(self.list.item(row), QListWidget.ScrollHint.PositionAtCenter)
        self.statusBar().showMessage(f"已将 {len(to_move)} 篇论文移入" + ("未分组。" if group_id is None else "分组。"))

    def reorder_paper_group(self, group_id, target_id, after):
        try:
            self.library.reorder_group(group_id, target_id, after)
        except Exception as exc:
            self.error("调整分组顺序失败：" + str(exc))
            return
        self.reload(self.paper["id"] if self.paper else None, reopen=False)
        row = next((index for index in range(self.list.count())
                    if self.list.item(index).data(GROUP_ID_ROLE) == group_id), -1)
        if row >= 0:
            self.list.scrollToItem(self.list.item(row), QListWidget.ScrollHint.PositionAtCenter)
        self.statusBar().showMessage("分组顺序已保存。")

    def group_context_menu(self, group_id, position):
        group = next((entry for entry in self.library.list_groups() if entry["id"] == group_id), None)
        if group is None: return
        menu = QMenu(self)
        rename = menu.addAction("修改分组名")
        rename.triggered.connect(lambda: self.rename_paper_group(group))
        pin = menu.addAction("取消置顶" if group["pinned"] else "置顶分组")
        pin.triggered.connect(lambda: self.pin_paper_group(group))
        menu.addSeparator()
        delete = menu.addAction("删除分组")
        delete.triggered.connect(lambda: self.delete_paper_group(group))
        menu.exec(self.list.viewport().mapToGlobal(position))

    def rename_paper_group(self, group):
        dialog = QInputDialog(self)
        dialog.setWindowTitle("修改分组名")
        dialog.setLabelText("分组名称：")
        dialog.setTextValue(group["name"])
        dialog.setOkButtonText("保存"); dialog.setCancelButtonText("取消")
        dialog.setMinimumWidth(620); dialog.resize(680, 180)
        if not dialog.exec(): return
        try:
            self.library.rename_group(group["id"], dialog.textValue())
        except Exception as exc:
            self.error("修改分组失败：" + str(exc)); return
        self.reload(self.paper["id"] if self.paper else None, reopen=False)

    def pin_paper_group(self, group):
        try:
            self.library.set_group_pinned(group["id"], not group["pinned"])
        except Exception as exc:
            self.error("更新分组置顶失败：" + str(exc)); return
        self.reload(self.paper["id"] if self.paper else None, reopen=False)

    def delete_paper_group(self, group):
        if self.busy:
            self.error("请等待后台任务完成后删除分组。")
            return
        identifiers = self.library.paper_ids_in_group(group["id"])
        dialog = QMessageBox(self)
        dialog.setWindowTitle("删除论文分组")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setTextFormat(Qt.TextFormat.RichText)
        dialog.setText(f"<b>确定删除分组“{escape(group['name'])}”？</b>")
        dialog.setInformativeText(
            f"<p>该分组关联 {len(identifiers)} 篇论文（包括已从列表移除的论文）。</p>"
            "<p><b>仅删除分组</b>：论文移到“未分组”，原文和全部学习内容保留。</p>"
            "<p><b>删除分组及全部论文（不可恢复）</b>：彻底删除组内论文的应用内 PDF 副本、"
            "AI 分析、笔记、追问、标注和阅读进度。</p>"
            "<p>不会删除原始导入文件、手动导出的文件或备份。</p>")
        dialog.setMinimumWidth(740)
        grid = dialog.layout()
        grid.addItem(QSpacerItem(680, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum),
                     grid.rowCount(), 0, 1, grid.columnCount())
        cancel = dialog.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        keep = dialog.addButton("仅删除分组", QMessageBox.ButtonRole.ActionRole)
        purge = dialog.addButton("删除分组及全部论文", QMessageBox.ButtonRole.DestructiveRole)
        keep.setStyleSheet("font-weight: 700;")
        purge.setObjectName("Danger"); purge.setStyleSheet("font-weight: 700;")
        button_box = dialog.findChild(QDialogButtonBox)
        if button_box:
            row = button_box.layout()
            while row.count(): row.takeAt(0)
            row.addStretch(1)
            for action_button in (cancel, keep, purge): row.addWidget(action_button)
        dialog.setDefaultButton(cancel); dialog.setEscapeButton(cancel)
        dialog.exec()
        if dialog.clickedButton() not in (keep, purge): return
        permanent = dialog.clickedButton() is purge
        if permanent and self.paper and self.paper["id"] in identifiers:
            self.close_current_paper()
        try:
            self.library.delete_group(group["id"], permanent=permanent)
        except Exception as exc:
            self.reload(self.paper["id"] if self.paper else None, reopen=False)
            self.error("删除分组失败：" + str(exc)); return
        if permanent:
            for identifier in identifiers:
                self.discard_paper_drafts(identifier)
                self.analysis_status.discard_paper(identifier)
                self.chat_status.discard_paper(identifier)
            self.clear_permanent_paper_caches()
        self.collapsed_groups.discard(group["id"])
        self.search_collapsed_groups.discard(group["id"])
        self.reload(self.paper["id"] if self.paper else None, reopen=False)
        if self.paper is None:
            row = self.first_paper_row()
            if row >= 0: self.list.setCurrentRow(row)
        self.statusBar().showMessage("分组及组内论文已彻底删除。" if permanent else "分组已删除，论文已移到未分组。")

    def paper_context_menu(self, position):
        if MACOS and QApplication.keyboardModifiers() & Qt.KeyboardModifier.MetaModifier:
            return
        item = self.list.itemAt(position)
        if item is None: return
        group_id = item.data(GROUP_ID_ROLE)
        if group_id is not None:
            if group_id != -1: self.group_context_menu(group_id, position)
            return
        paper = self.paper_at_row(self.list.row(item))
        if paper is None: return
        menu = QMenu(self)
        assets = Path(__file__).resolve().parent.parent.parent.parent / "assets"
        star = self.list.favorite_icon if paper["favorite"] else self.list.outline_icon
        favorite = menu.addAction(star, "取消收藏" if paper["favorite"] else "收藏论文")
        favorite.triggered.connect(lambda: self.toggle_favorite(paper))
        rename = menu.addAction(QIcon(str(assets / "paper-edit.svg")), "修改论文标题")
        rename.triggered.connect(lambda: self.rename_paper(item))
        group_menu = menu.addMenu("移动到分组")
        group_menu.menuAction().setIcon(QIcon(str(assets / "paper-move.svg")))
        for group_id, name in [(None, "未分组")] + [(g["id"], g["name"]) for g in self.library.list_groups()]:
            group_action = group_menu.addAction(name)
            group_action.setCheckable(True)
            group_action.setChecked(paper["group_id"] == group_id)
            group_action.triggered.connect(lambda _checked=False, target=group_id: self.move_paper_to_group(paper, target))
        export = menu.addAction(QIcon(str(assets / "paper-export.svg")), "导出学习内容")
        export.triggered.connect(lambda: self.export(paper["id"]))
        menu.addSeparator()
        clear = menu.addAction(QIcon(str(assets / "paper-trash.svg")), "清除学习内容")
        clear.triggered.connect(lambda: self.clear_paper_learning(paper))
        action = menu.addAction(QIcon(str(assets / "paper-trash.svg")), "移除论文")
        action.triggered.connect(lambda: self.remove_paper(paper))
        menu.exec(self.list.viewport().mapToGlobal(position))

    def toggle_favorite(self, paper):
        try:
            self.library.set_favorite(paper["id"], not paper["favorite"])
        except Exception as exc:
            self.error("更新收藏失败：" + str(exc))
            return
        current = self.paper["id"] if self.paper else None
        self.reload(current, reopen=False)

    def clear_paper_learning(self, metadata):
        if self.busy:
            self.error("请等待后台任务完成后清除学习内容。")
            return
        identifier = metadata["id"]
        dialog = QMessageBox(self)
        dialog.setWindowTitle("清除学习内容")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setTextFormat(Qt.TextFormat.RichText)
        dialog.setText(f"<b>确定清除《{escape(metadata['title'])}》的学习内容？</b>")
        dialog.setInformativeText(
            "<p>将清除 AI 分析、个人笔记、全部追问会话及其上下文，以及阅读进度、高亮和批注。"
            "<b>此操作不可恢复。</b></p>"
            "<p>保留论文列表条目、原文 PDF 和收藏状态。</p>"
        )
        cancel = dialog.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        confirm = dialog.addButton("确认清除", QMessageBox.ButtonRole.DestructiveRole)
        confirm.setObjectName("Danger")
        dialog.setDefaultButton(cancel)
        dialog.setEscapeButton(cancel)
        dialog.exec()
        if dialog.clickedButton() is not confirm:
            return
        is_current = self.paper is not None and self.paper["id"] == identifier
        try:
            paper = self.paper if is_current else self.library.get(identifier)
            updated = self.library.clear_learning(paper)
        except Exception as exc:
            self.error("清除学习内容失败：" + str(exc))
            return

        self.discard_paper_drafts(identifier)
        self.analysis_status.discard_paper(identifier)
        self.chat_status.discard_paper(identifier)
        if is_current:
            self.paper = updated
            self.timer.stop()
            with QSignalBlocker(self.notes):
                self.notes.setPlainText("")
            self.question.clear()
            self.clear_quote()
            self.view.clear_citation()
            self.mark_preview.set_markdown("")
            self.page = 0
            self.view.jump(0)
            self.position_timer.stop()
            self.refresh()
        self.statusBar().showMessage("已清除该论文的学习内容。")

    def discard_paper_drafts(self, identifier):
        for draft in list(self.summary_drafts):
            if draft == identifier or draft.startswith(identifier + ":"):
                self.summary_drafts.pop(draft)
        self.chat_drafts.pop(identifier, None)

    def first_paper_row(self):
        return next((row for row in range(self.list.count())
                     if self.list.item(row).data(PAPER_ID_ROLE)), -1)

    def close_current_paper(self):
        self.save_notes(); self.timer.stop(); self.position_timer.stop(); self.persist()
        if self.pdf_fullscreen_state is not None:
            self.toggle_pdf_fullscreen()
        self.pdf_fullscreen_button.setEnabled(False)
        self.pdf_color_button.setEnabled(False)
        self.view.clear_document()
        if self.doc: self.doc.close()
        self.doc = None; self.paper = None
        self._figure_index = None; self._figure_images = {}
        self.passage_index = None
        self.analysis_status.set_context(None); self.chat_status.set_context(None)
        self.notes.blockSignals(True); self.notes.clear(); self.notes.blockSignals(False)
        for browser in self.analysis_browsers.values():
            browser.set_status_html("")
            browser.set_markdown("")
        self.chat.set_markdown("")
        self.marks.clear(); self.mark_preview.set_markdown(""); self.question.clear(); self.clear_quote()
        self.question_navigation.update_questions([])
        self.set_reader_title(""); self.update_pdf_page_counter()
        self.update_reading_home()

    def clear_permanent_paper_caches(self):
        from paperreader.ui.math_render import render_formula
        render_formula.cache_clear()
        for browser in (*self.analysis_browsers.values(), self.chat, self.quote_label, self.mark_preview, self.notes.preview):
            browser.math_resources.clear(); browser.math_sources.clear()

    def remove_paper(self, paper):
        if self.busy:
            self.error("请等待后台任务完成后移除论文。"); return
        paper = self.paper if self.paper and self.paper["id"] == paper["id"] else self.library.get(paper["id"])
        dialog = QMessageBox(self)
        dialog.setWindowTitle("移除论文")
        from html import escape
        dialog.setTextFormat(Qt.TextFormat.RichText)
        dialog.setText(f"<b>确定移除《{escape(paper['title'])}》？</b>")
        dialog.setInformativeText(
            '<p><span style="font-weight:700;">仅从列表移除</span><br>从列表隐藏，保留全部本地资料，重新导入相同 PDF 可恢复。</p>'
            '<p><span style="font-weight:700; color:#efb0b3;">彻底删除（不可恢复）</span><br>'
            '删除应用内 PDF 副本、笔记、AI 分析、全部历史问答与高亮批注。</p>'
            '<p>不会删除原始导入文件、手动导出或备份。</p>')
        dialog.setMinimumWidth(720)
        grid = dialog.layout()
        grid.addItem(QSpacerItem(660, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum),
                     grid.rowCount(), 0, 1, grid.columnCount())
        cancel = dialog.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        hide = dialog.addButton("仅从列表移除", QMessageBox.ButtonRole.ActionRole)
        purge = dialog.addButton("彻底删除", QMessageBox.ButtonRole.DestructiveRole)
        hide.setStyleSheet("font-weight: 700;")
        purge.setObjectName("Danger"); purge.setStyleSheet("font-weight: 700;")
        button_box = dialog.findChild(QDialogButtonBox)
        if button_box:
            row = button_box.layout()
            while row.count(): row.takeAt(0)
            row.addStretch(1)
            for action_button in (cancel, hide, purge): row.addWidget(action_button)
        dialog.setDefaultButton(cancel); dialog.exec()
        clicked = dialog.clickedButton()
        if clicked not in (hide, purge): return
        permanent = clicked is purge
        identifier = paper['id']
        if self.paper and self.paper['id'] == identifier:
            self.close_current_paper()
        try: self.library.remove(paper, permanent)
        except Exception as exc:
            self.reload(identifier); self.error("移除失败：" + str(exc)); return
        self.discard_paper_drafts(identifier)
        if permanent:
            self.analysis_status.discard_paper(identifier); self.chat_status.discard_paper(identifier)
            self.clear_permanent_paper_caches()
        current = self.paper['id'] if self.paper else None
        self.reload(current)
        if self.paper is None and self.papers:
            row = self.first_paper_row()
            if row >= 0: self.list.setCurrentRow(row)
        self.statusBar().showMessage("论文及其本地学习记录已彻底删除。" if permanent else "已从论文列表移除，重新导入相同 PDF 可恢复。")

    def rename_paper(self, item):
        row = self.list.row(item)
        if row < 0: return
        metadata = self.paper_at_row(row)
        if metadata is None: return
        paper = self.paper if self.paper and self.paper["id"] == metadata["id"] else self.library.get(metadata["id"])
        dialog = QInputDialog(self)
        dialog.setWindowTitle("修改论文标题")
        dialog.setInputMode(QInputDialog.InputMode.TextInput)
        dialog.setLabelText("论文标题：")
        dialog.setTextValue(paper['title'])
        dialog.setOkButtonText("保存"); dialog.setCancelButtonText("取消")
        dialog.setMinimumWidth(760); dialog.resize(860, 200)
        if dialog.exec() and dialog.textValue().strip():
            title = dialog.textValue()
            paper["title"] = " ".join(title.split()); self.library.save(paper)
            metadata["title"] = paper["title"]
            item.setText(paper["title"]); item.setToolTip(paper["title"])
            if self.paper is paper:
                self.set_reader_title(paper["title"])

    def open_paper(self, row):
        if row < 0: return
        if self.list._modifying_selection: return
        metadata = self.paper_at_row(row)
        if metadata is None: return
        self.save_notes()
        self.position_timer.stop()
        if self.paper: self.persist()
        self.view.clear_document()
        if self.doc: self.doc.close()
        pending = getattr(self, 'inflight_paper', None)
        self.paper = pending if self.busy and pending and pending['id'] == metadata['id'] else self.library.get(metadata['id'])
        if self.analysis_progress_paper_id not in (None, self.paper['id']):
            self.analysis_progress_widget.hide()
        metadata['title'] = self.paper['title']
        self.list.item(row).setText(self.paper['title']); self.list.item(row).setToolTip(self.paper['title'])
        ensure_sessions(self.paper)
        self.set_reader_title(self.paper["title"])
        self.view.begin_loading()
        try:
            self.doc = fitz.open(self.library.pdf_path(self.paper))
        except Exception:
            self.view.end_loading()
            raise
        self._figure_index = None; self._figure_images = {}
        self.passage_index = None
        self.page = min(self.paper.get("page", 0), len(self.doc)-1)
        self.notes.blockSignals(True); self.notes.setPlainText(self.paper["notes"]); self.notes.blockSignals(False)
        self.view.follow_theme = self.paper.get("pdf_follow_theme", True)
        self.pdf_color_button.setText("黑白色" if self.view.follow_theme else "主题色")
        self.pdf_color_button.setEnabled(True)
        try:
            self.view.load(self.doc, self.page)
        except Exception:
            self.view.end_loading()
            raise
        self.pdf_fullscreen_button.setEnabled(True)
        try:
            self.clear_quote(); self.refresh()
        except Exception:
            self.view.end_loading()
            raise
        self.recent_reading[self.paper["id"]] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.recent_path.write_text(json.dumps(self.recent_reading), encoding="utf-8")
        except OSError:
            pass
        self.update_reading_home()

    def import_file(self):
        if self.busy:
            self.error("请等待后台任务完成后导入论文。"); return
        paths, _ = QFileDialog.getOpenFileNames(self, "批量导入论文", "", "PDF (*.pdf)")
        if not paths: return
        progress = QProgressDialog("正在导入 PDF…", "停止后续导入", 0, len(paths), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal); progress.setMinimumDuration(0)
        failures = []; succeeded = 0; last = None
        for index, path in enumerate(paths):
            progress.setValue(index)
            if progress.wasCanceled(): break
            progress.setLabelText(f"正在导入 {Path(path).name}（{index+1}/{len(paths)}）")
            try:
                last = self.library.import_pdf(Path(path).read_bytes(), Path(path).stem)
                succeeded += 1
            except Exception as exc:
                log.error("本地 PDF 导入失败：{}", Path(path).name, exc_info=True)
                failures.append(f"{Path(path).name}：{exc}")
        progress.close()
        if last: self.reload(last['id'])
        message = f"已处理 {succeeded} 个 PDF（相同文件自动去重）。"
        if failures: self.error(message + "\n以下文件导入失败，其余不受影响：\n" + "\n".join(failures))
        else: self.statusBar().showMessage(message)

    def import_link(self):
        if self.busy:
            self.error("请等待后台任务完成后导入论文。"); return
        dialog = QInputDialog(self)
        dialog.setWindowTitle("网站导入")
        dialog.setInputMode(QInputDialog.InputMode.TextInput)
        dialog.setLabelText("arXiv 摘要页或直接 PDF 链接：")
        dialog.setOkButtonText("导入"); dialog.setCancelButtonText("取消")
        dialog.setMinimumWidth(760); dialog.resize(820, 200)
        field = dialog.findChild(QLineEdit)
        if field: field.setPlaceholderText("https://arxiv.org/abs/… 或 https://…/paper.pdf")
        accepted = dialog.exec()
        url = dialog.textValue().strip()
        if accepted and url:
            parsed = urlsplit(url)
            log.info("开始导入论文链接：{}{}", parsed.netloc, parsed.path)
            self.task(lambda: download(url), lambda data: self.finish_link_import(data, url))

    def finish_link_import(self, data, url):
        existing_ids = {item["id"] for item in self.library.list_metadata()}
        paper = self.library.import_pdf(data, url.rstrip("/").split("/")[-1], url)
        duplicate = paper["id"] in existing_ids
        self.reload(paper["id"])
        row = self.row_for_paper(paper["id"])
        if row >= 0:
            self.list.scrollToItem(self.list.item(row), QListWidget.ScrollHint.PositionAtCenter)
        metadata = next((item for item in self.all_papers if item["id"] == paper["id"]), None)
        group_id = metadata["group_id"] if metadata else None
        group = next((item["name"] for item in self.library.list_groups() if item["id"] == group_id), "未分组")
        if duplicate:
            message = f"论文已存在于「{group}」：{paper['title'][:70]}，已定位到原记录。"
            log.info("论文链接重复：{}，分组 {}，标题 {}", paper["id"][:12], group, paper["title"])
        else:
            message = f"论文已导入「{group}」：{paper['title'][:70]}。"
            log.info("论文链接导入成功：{}，分组 {}，标题 {}", paper["id"][:12], group, paper["title"])
        self.statusBar().showMessage(message)
