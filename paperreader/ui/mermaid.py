"""Render local Mermaid diagrams to Qt images without a network dependency."""
import json
import base64
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QImage
from PySide6.QtWebEngineCore import QWebEnginePage


class MermaidRenderer(QObject):
    ready = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._page = QWebEnginePage(self)
        self._page.loadFinished.connect(self._loaded)
        self._queue = []
        self._active = None
        self._loaded_ok = None
        self._polls = 0
        self._page.load(QUrl.fromLocalFile(str(
            Path(__file__).resolve().parent.parent / 'assets' / 'mermaid-render.html')))

    def request(self, key, source, style):
        if key != self._active and all(item[0] != key for item in self._queue):
            self._queue.append((key, source, style))
        self._next()

    def _loaded(self, ok):
        self._loaded_ok = ok
        self._next()

    def _next(self):
        if self._loaded_ok is None or self._active or not self._queue:
            return
        key, source, style = self._queue.pop(0)
        if not self._loaded_ok:
            self.ready.emit(key, None)
            QTimer.singleShot(0, self._next)
            return
        self._active = key
        self._polls = 0
        self._page.runJavaScript('window.paperreaderRender(' + json.dumps(source) + ','
                                 + json.dumps(style) + ')')
        QTimer.singleShot(60, self._poll)

    def _poll(self):
        if not self._active:
            return
        self._polls += 1
        if self._polls > 200:
            self._finish(None)
            return
        self._page.runJavaScript('JSON.stringify(window.paperreaderResult)', self._received)

    def _received(self, payload):
        if not self._active:
            return
        if not payload or payload == 'null':
            QTimer.singleShot(60, self._poll)
            return
        image = None
        try:
            result = json.loads(payload)
        except (TypeError, ValueError):
            result = None
        if isinstance(result, dict) and result.get('png', '').startswith('data:image/png;base64,'):
            try:
                data = base64.b64decode(result['png'].split(',', 1)[1], validate=True)
                candidate = QImage.fromData(data, 'PNG')
                if not candidate.isNull() and 0 < candidate.width() * candidate.height() <= 20_000_000:
                    candidate.setDevicePixelRatio(float(result['scale']))
                    image = candidate
            except (ValueError, KeyError):
                pass
        self._finish(image)

    def _finish(self, image):
        key, self._active = self._active, None
        self.ready.emit(key, image)
        QTimer.singleShot(0, self._next)
