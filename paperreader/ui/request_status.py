"""Collapsible, local request activity; never logs prompts, secrets, or responses."""
import time
from html import escape
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QToolButton, QProgressBar, QPlainTextEdit, QSizePolicy
from paperreader.ui.theme import theme_color


class RequestStatus(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(4)
        self.toggle = QToolButton()
        self.toggle.setObjectName('RequestToggle')
        self.toggle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle.setToolTip('展开或折叠请求过程')
        layout.addWidget(self.toggle)
        self.progress = QProgressBar()
        self.progress.setObjectName('RequestProgress')
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setObjectName('RequestLog')
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(100)
        self.log.setFixedHeight(96)
        layout.addWidget(self.log)
        self.toggle.toggled.connect(self.expand)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        self.running = False
        self.browser = None
        self.render_status = None
        self.context = None
        self.owner = None
        self.records = {}
        self.setStyleSheet('''
            QToolButton#RequestToggle { color: #91b9c5; background: transparent;
                border: none; padding: 4px 0; text-align: left; }
            QToolButton#RequestToggle:hover { color: #66ddda; }
            QPlainTextEdit#RequestLog { background: #0c1622; color: #91aabd;
                border: 1px solid #2b4254; border-radius: 6px; padding: 6px; }
            QProgressBar#RequestProgress { border: none; background: #213243; }
            QProgressBar#RequestProgress::chunk { background: #66ddda; }
        ''')
        self.hide()

    def attach(self, browser, render_status=None):
        self.browser = browser
        self.render_status = render_status
        self.setParent(browser)
        self.hide()
        if render_status is None:
            browser.anchorClicked.connect(self.link_clicked)

    def link_clicked(self, url):
        if url.scheme() != 'paperreader-status': return
        self.toggle_context(self.context)

    def toggle_context(self, context):
        if context not in self.records:
            return
        if context == self.owner:
            self.toggle.click()
        else:
            record = self.records[context]
            record['expanded'] = not record['expanded']
            self.render_inline(context)

    def set_context(self, context):
        if self.context == context: return
        self.context = context
        if self.render_status is None:
            self.render_inline()

    def discard_paper(self, identifier):
        for context in list(self.records):
            if context[0] == identifier: self.records.pop(context)
        if self.owner is not None and self.owner[0] == identifier:
            self.owner = None
        self.render_inline()

    def render_inline(self, context=None):
        if self.browser is None: return
        if self.owner is not None and hasattr(self, 'started'):
            self.records[self.owner] = dict(title=self.toggle.text(), log=self.log.toPlainText(),
                                            expanded=self.toggle.isChecked())
        if self.render_status is not None:
            self.render_status(context or self.owner)
        else:
            html = self.html_for(self.context)
            self.browser.set_status_html(html + '<hr>' if html else '')

    def html_for(self, context, href='paperreader-status:toggle'):
        record = self.records.get(context)
        if record is None:
            return ''
        arrow = '▾' if record['expanded'] else '▸'
        title = escape(record['title'])
        details = ''
        if record['expanded']:
            lines = '<br>'.join(escape(line) for line in record['log'].splitlines())
            details = f'<p style="color:{theme_color("#91aabd")}; font-size:12px; margin:4px 0 10px 0;">{lines}</p>'
        return (
            f'<p style="margin:4px 0 6px 0;"><a href="{escape(href, quote=True)}" '
            f'style="color:{theme_color("#66ddda")}; text-decoration:none;">{arrow} {title}</a></p>' + details)

    def expand(self, expanded):
        self.log.setVisible(expanded)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.render_inline()

    def add(self, message):
        elapsed = int(time.monotonic() - self.started)
        self.log.appendPlainText(f'[{elapsed:02d}秒] {message}')

    def begin(self, label, model):
        self.owner = self.context
        self.started = time.monotonic()
        self.label = label
        self.phase = '等待模型响应'
        self.characters = 0
        self.running = True
        self.log.clear()
        if self.browser is None: self.show()
        self.progress.show()
        self.toggle.setChecked(True); self.expand(True)
        self.add(f'{label}任务已启动 · 模型：{model}')
        self.add('正在调用模型，等待首段内容…')
        self.timer.start(); self.tick()

    def stage(self, title):
        self.phase = '等待模型响应'
        self.add(title + ' · 等待模型响应…')
        self.tick()

    def received(self, text):
        if not text: return
        first_chunk = self.phase != '正在接收内容'
        if first_chunk:
            self.add('已收到模型内容，正在流式生成…')
        self.phase = '正在接收内容'
        self.characters += len(text)
        if first_chunk:
            self.tick()

    def tick(self, *, force=False):
        if not force and self.browser is not None and self.browser.is_user_scrolling():
            return
        elapsed = int(time.monotonic() - self.started)
        count = f' · 已接收 {self.characters} 字符' if self.characters else ''
        self.toggle.setText(f'{self.label} · {self.phase} · {elapsed}秒{count}')
        self.render_inline()

    def finish(self, success=True):
        self.running = False
        self.timer.stop(); self.progress.hide()
        self.phase = '已完成' if success else '请求失败，可重试'
        self.add('模型返回完成，内容已处理。' if success else '请求未完成，请查看错误提示后重试。')
        self.tick(force=True)
        self.toggle.setChecked(not success)
        self.expand(not success)
