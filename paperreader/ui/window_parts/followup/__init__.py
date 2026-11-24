"""Followup behavior for the main window."""
from threading import Event
from paperreader.ui.prompts.followup import FOLLOWUP_INSTRUCTION
from paperreader.services.themes import get_theme
from paperreader.services.sessions import ensure_sessions
from paperreader.services.retrieval import CITATION, PassageIndex, asks_about_assistant

class FollowupMixin:
    def ask_about_analysis(self, text):
        if not self.paper or not text.strip(): return
        self.quote = "[来源：AI 分析，需结合论文核对]\n" + text.strip()
        self.quote_passage = None
        self.quote_label.set_markdown(self.quote)
        self.quote_box.show()
        self.question.setFocus()
        self.statusBar().showMessage("已引用 AI 分析内容，请输入问题后发送。")

    def clear_quote(self):
        self.quote = ""; self.quote_label.set_markdown("未引用选区")
        self.quote_passage = None
        self.quote_box.hide()

    def toggle_ask(self):
        if self.chat_cancel is None:
            self.ask()
            return
        self.chat_cancel.set()
        self.send_button.setText("停止中…")
        self.send_button.setEnabled(False)

    def ask(self):
        if not self.paper:
            self.chat.set_markdown(f"### {self.reading_assistant_name}\n\n请先导入或打开一篇论文，再使用论文追问。")
            return
        if self.busy or not self.question.toPlainText().strip(): return
        question = self.question.toPlainText().strip(); paper = self.paper
        pack = get_theme(self.profile_config["theme"])
        prompt = (f"引用选区：{self.quote}\n\n" if self.quote else "") + question
        standalone = not self.quote and asks_about_assistant(question)
        instruction = FOLLOWUP_INSTRUCTION
        evidence_header = "以下是论文资料。除标注为用户手动选区的片段外，均由应用自动检索。\n\n"
        question_header = "以下是用户的问题。\n\n"
        recent_messages = [] if standalone else paper["messages"][-6:]
        history = [{"role": m["role"], "content": CITATION.sub("", self.answer_with_page_numbers(m)[:6000])}
                   for m in recent_messages]
        context, sources = "", {}
        try:
            if not standalone:
                if self.passage_index is None:
                    self.passage_index = PassageIndex(self.doc)
                if not self.passage_index.passages:
                    raise ValueError("PDF 无可提取文本，首版不支持 OCR。")
                context, sources = self.passage_index.context(
                    question, 30000, selection=self.quote_passage, quote=self.quote,
                )
        except Exception as exc: self.error(str(exc)); return
        messages = [{"role": "system", "content": instruction}]
        user_content = evidence_header + context + question_header + prompt if context else prompt
        messages += history + [{"role": "user", "content": user_content}]
        chunks = []
        session = ensure_sessions(paper)
        status_context = (paper["id"], session["id"], len(session["messages"]))
        self.chat_status.set_context(status_context)
        self.chat_drafts[paper["id"]] = (prompt, "正在等待模型响应…", pack.assistant_name, sources)
        self.render_chat(follow_latest=True)
        def display_draft():
            self.chat_drafts[paper["id"]] = (prompt, "".join(chunks), pack.assistant_name, sources)
            if self.paper is paper: self.render_chat()
        render_timer = self.stream_render_timer(self.chat, display_draft)
        def progress(text):
            chunks.append(text)
            if not render_timer.isActive(): render_timer.start()
        def save_answer(text, success):
            status_record = self.chat_status.records.get(status_context)
            paper["messages"] += [
                {"role": "user", "content": prompt, "question": question},
                {"role": "assistant", "content": text, "theme_id": pack.identifier,
                 "assistant_name": pack.assistant_name,
                 "citations": {tag: sources[tag] for tag in set(CITATION.findall(text)) if tag in sources},
                 **({"request_status": dict(status_record)} if status_record else {})},
            ]
            session = ensure_sessions(paper)
            if session["title"] == "新会话": session["title"] = question[:60]
            self.library.save(paper)
            self.chat_drafts.pop(paper["id"], None)
            if self.paper is paper:
                self.refresh()
        cancel = Event()
        def reset_controls():
            render_timer.stop(); render_timer.deleteLater()
            self.chat_cancel = None
            self.send_button.setText("发送 ↑")
            self.send_button.setEnabled(True)
        def done(text):
            reset_controls()
            save_answer(text, True)
        def failed(error):
            reset_controls()
            if self.paper is paper and not self.question.toPlainText().strip():
                self.question.setPlainText(question)
            if chunks:
                save_answer("**生成中断，以下为部分结果**\n\n" + "".join(chunks), False)
            else:
                self.chat_drafts.pop(paper["id"], None)
                if self.paper is paper: self.render_chat()
        def stopped():
            reset_controls()
            if chunks:
                save_answer("**已停止，以下为部分结果**\n\n" + "".join(chunks), False)
            else:
                self.chat_drafts.pop(paper["id"], None)
                if self.paper is paper:
                    self.question.setPlainText(question)
                    self.render_chat()
        self.chat_cancel = cancel
        self.send_button.setText("停止")
        if self.ai(messages, done, progress, failed, request_status=self.chat_status,
                   request_label='论文追问', theme=pack.identifier,
                   cancel=cancel, on_stop=stopped):
            self.question.clear(); self.clear_quote()
        elif self.chat_cancel is cancel:
            reset_controls()
