"""Browser-session downloads for publisher pages that require JavaScript."""
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from PySide6.QtWebEngineCore import (
    QWebEngineDownloadRequest, QWebEnginePage, QWebEngineProfile, QWebEngineSettings,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

from paperreader.services.lazy import fitz
from paperreader.services.research_pdf import MAX_PDF_BYTES, page_pdf_links


class ResearchDownload(QWidget):
    ready = Signal(object)
    status_changed = Signal(str)
    failed = Signal(str)

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root = Path(root) / "research-downloads"
        self.root.mkdir(parents=True, exist_ok=True)
        self.closed = False
        self.current = None
        self.request = None
        self.pending = []
        self.tried = set()
        self.generation = 0
        self.source = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.status = QLabel()
        self.status.setWordWrap(True)
        row.addWidget(self.status, 1)
        retry = QPushButton("重新查找 PDF")
        retry.clicked.connect(self.inspect_page)
        row.addWidget(retry)
        layout.addLayout(row)
        self.profile = QWebEngineProfile(self)
        self.profile.downloadRequested.connect(self.accept_download)
        self.page = QWebEnginePage(self.profile, self)
        self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.PdfViewerEnabled, False)
        self.page.newWindowRequested.connect(lambda request: request.openIn(self.page))
        self.web = QWebEngineView()
        self.web.setPage(self.page)
        self.web.loadFinished.connect(self.page_loaded)
        layout.addWidget(self.web, 1)
        self.retry = QTimer(self)
        self.retry.setSingleShot(True)
        self.retry.setInterval(1500)
        self.retry.timeout.connect(self.inspect_page)
        self.inspections = 0
        self.clicked_pages = set()
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.setInterval(35000)
        self.deadline.timeout.connect(lambda: self.fail("下载超时，未能取得可读 PDF。"))
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def set_status(self, message):
        self.status.setText(message)
        self.status_changed.emit(message)

    def fail(self, message):
        self.cancel()
        self.failed.emit(message)

    def start(self, source, target):
        self.cancel()
        self.source = dict(source)
        self.target = Path(target)
        self.current = self.generation
        self.set_status("正在连接论文站点…")
        self.deadline.start()
        self.page.setVisible(True)
        self.web.setUrl(QUrl(source["url"]))

    def cancel(self):
        if self.closed:
            return
        self.generation += 1
        self.current = None
        self.retry.stop()
        self.deadline.stop()
        self.clicked_pages.clear()
        self.web.stop()
        self.page.setVisible(False)
        if self.request is not None:
            self.request.cancel()
            self.request = None
        self.pending = []
        self.tried.clear()
        self.inspections = 0

    def page_loaded(self, ok):
        if self.current is None:
            return
        if ok:
            self.inspect_page()
            if self.inspections < 5:
                self.retry.start()
        else:
            self.set_status("正在等待站点响应…")

    def inspect_page(self):
        if self.current is None or self.request is not None:
            return
        generation = self.current
        url = self.page.url().toString()
        self.inspections += 1
        self.page.toHtml(lambda html: self.page_source(generation, html, url))

    def page_source(self, generation, html, url):
        if generation != self.current or self.request is not None:
            return
        links = page_pdf_links(html, url)
        self.pending = [link for link in links if link not in self.tried]
        if url not in self.clicked_pages:
            self.clicked_pages.add(url)
            self.set_status("正在通过页面的 PDF 下载按钮保存文件…")
            self.page.runJavaScript("""
                (() => {
                    const candidates = Array.from(document.querySelectorAll('a,button'));
                    const target = candidates.find(el =>
                        /download\s*(?:this\s*)?(?:paper|pdf)|下载\s*pdf/i.test(el.innerText || el.textContent || '')
                        && el.getClientRects().length > 0 && !el.disabled);
                    if (!target) return false;
                    target.click();
                    return true;
                })()
            """, lambda clicked: self.clicked_download(generation, clicked))
        else:
            self.try_next()

    def clicked_download(self, generation, clicked):
        if generation != self.current or self.request is not None:
            return
        if not clicked:
            self.try_next()
        elif self.inspections < 5:
            self.retry.start()

    def try_next(self):
        if self.current is None:
            return
        if not self.pending:
            if self.inspections < 5:
                self.retry.start()
            else:
                self.fail("未找到可下载的 PDF，可在浏览器中打开论文。")
            return
        target = self.pending.pop(0)
        self.tried.add(target)
        self.set_status("已找到 PDF 下载地址，正在保存到本地…")
        self.page.download(QUrl(target))

    def accept_download(self, request):
        if self.current is None or self.request is not None or request.page() != self.page:
            request.cancel()
            return
        self.request = request
        generation = self.current
        filename = uuid4().hex + ".pdf"
        path = self.root / filename
        request.setDownloadDirectory(str(self.root))
        request.setDownloadFileName(filename)
        request.receivedBytesChanged.connect(lambda: self.progress(request))
        request.isFinishedChanged.connect(lambda: self.download_finished(generation, request, path))
        request.accept()

    def progress(self, request):
        if request is not self.request:
            return
        size = request.receivedBytes()
        if size > MAX_PDF_BYTES:
            self.fail("下载失败，PDF 超过 32 MB。")
            return
        total = request.totalBytes()
        self.set_status(f"正在下载 PDF · {size / 1048576:.1f} MB" +
                            (f" / {total / 1048576:.1f} MB" if total > 0 else ""))

    def download_finished(self, generation, request, path):
        if not request.isFinished():
            return
        valid = False
        if request.state() == QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
            try:
                if path.stat().st_size <= MAX_PDF_BYTES:
                    with fitz.open(path) as document:
                        valid = len(document) > 0 and not document.needs_pass
            except (OSError, RuntimeError, ValueError):
                pass
        active = generation == self.current
        if request is self.request:
            self.request = None
        if valid and active:
            try:
                path.replace(self.target)
            except OSError:
                path.unlink(missing_ok=True)
                self.fail("本地保存失败，请检查存储空间。")
                return
            self.current = None
            self.deadline.stop()
            self.ready.emit(self.target)
            return
        path.unlink(missing_ok=True)
        if active:
            if self.pending:
                self.try_next()
            elif request.state() == QWebEngineDownloadRequest.DownloadState.DownloadInterrupted:
                self.fail(f"下载失败，{request.interruptReasonString()}。")
            else:
                self.fail("下载失败，站点未返回可读 PDF。")

    def shutdown(self):
        if self.closed:
            return
        self.cancel()
        self.closed = True
        from shiboken6 import delete
        # The browser page must be destroyed before its download profile.
        delete(self.web)
        delete(self.page)
        delete(self.profile)
