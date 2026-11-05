import fitz
from paperreader.ui.selection import column_words
from PySide6.QtCore import Qt, QRect, QRectF, QPoint, Signal, QEvent
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor
from PySide6.QtWidgets import QLabel, QMenu


class PageView(QLabel):
    action = Signal(str, str, list)

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.single_word = None
        self.anchor = None
        self.endpoint = None
        self.page = None
        self.scale = 1.3
        self.start = None
        self.selection = QRect()
        self.marks = []
        self.words = []
        self.bitmap = None
        self.render_scale = None

    def display(self, page, marks):
        self.page, self.marks = page, marks
        self.words = page.get_text("words", sort=True)
        self.column_cache = None
        self.selection = QRect()
        self.single_word = None
        self.anchor = self.endpoint = None
        # Qt widget geometry uses logical pixels; PDF raster needs physical screen pixels.
        from math import sqrt
        target_density = max(1.5, self.devicePixelRatioF())
        logical_area = max(1, page.rect.width * page.rect.height * self.scale**2)
        density = min(target_density, sqrt(24_000_000 / logical_area))
        pix = page.get_pixmap(matrix=fitz.Matrix(self.scale*density, self.scale*density), alpha=False)
        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
        bitmap = QPixmap.fromImage(image)
        bitmap.setDevicePixelRatio(density)
        super().clear()
        self.bitmap = bitmap
        self.render_scale = self.scale
        self.setFixedSize(ceil(page.rect.width*self.scale), ceil(page.rect.height*self.scale))
        self.update()

    def clear(self):
        self.bitmap = None
        super().clear()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.single_word = None
            self.start = event.position().toPoint()
            self.anchor = self.endpoint = self.start
            self.selection = QRect()
            self.update()
            event.accept()
        else:
            event.ignore()

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.page is None:
            event.ignore(); return
        self.start = None
        self.single_word = None
        self.anchor = self.endpoint = None
        point = fitz.Point(event.position().x()/self.scale, event.position().y()/self.scale)
        for index, word in enumerate(self.words):
            rect = fitz.Rect(word[:4]) * self.page.rotation_matrix
            if rect.contains(point):
                self.single_word = index
                break
        self.update()
        event.accept()

    def mouseMoveEvent(self, event):
        if self.start is not None:
            self.endpoint = event.position().toPoint()
            self.selection = QRect(self.start, self.endpoint).normalized()
            self.update()
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.start is not None:
            # Release may be the only endpoint event delivered on a quick trackpad drag.
            self.endpoint = event.position().toPoint()
            self.selection = QRect(self.start, self.endpoint).normalized()
            self.start = None
            self.update()
            event.accept()
        else:
            event.ignore()

    def selected(self):
        if self.page is not None and self.single_word is not None:
            word = self.words[self.single_word]
            return word[4], [list(word[:4])]
        if self.page is None or self.anchor is None or self.endpoint is None:
            return "", []
        if (self.endpoint - self.anchor).manhattanLength() < 3:
            return "", []
        words = self.words
        if not words:
            return "", []
        cache_key = (self.anchor.x(), self.anchor.y(), self.scale)
        cached = getattr(self, 'column_cache', None)
        if cached is None or cached[0] != cache_key:
            point = fitz.Point(self.anchor.x()/self.scale, self.anchor.y()/self.scale) * self.page.derotation_matrix
            words = column_words(words, point, self.page.cropbox.width, self.page.cropbox.height)
            self.column_cache = (cache_key, words)
        else: words = cached[1]
        # PyMuPDF text coordinates are unrotated; mouse coordinates are rendered/rotated.
        def nearest(point):
            p = fitz.Point(point.x()/self.scale, point.y()/self.scale)
            def distance(word):
                rect = fitz.Rect(word[:4]) * self.page.rotation_matrix
                dx = max(rect.x0-p.x, 0, p.x-rect.x1)
                dy = max(rect.y0-p.y, 0, p.y-rect.y1)
                return dx*dx + dy*dy
            return min(range(len(words)), key=lambda i: distance(words[i]))
        first, last = sorted((nearest(self.anchor), nearest(self.endpoint)))
        selected = words[first:last+1]
        lines = []
        previous = None
        for word in selected:
            line = (word[5], word[6])
            if lines and line == previous:
                lines[-1] += " " + word[4]
            else:
                lines.append(word[4])
            previous = line
        return "\n".join(lines), [list(w[:4]) for w in selected]

    def contextMenuEvent(self, event):
        text, rects = self.selected()
        menu = QMenu(self)
        hit_rects = rects
        if not hit_rects and self.page is not None:
            point = fitz.Point(event.pos().x()/self.scale, event.pos().y()/self.scale) * self.page.derotation_matrix
            hit_rects = [r for mark in self.marks for r in mark["rects"] if fitz.Rect(r).contains(point)]
        overlapping = [mark for mark in self.marks if any(fitz.Rect(a).intersects(fitz.Rect(b)) for a in hit_rects for b in mark["rects"])]
        if text:
            for name in ["复制", "翻译所选内容", "针对所选内容提问", "高亮", "添加批注"]:
                menu.addAction(name)
        if any(m.get("highlight", True) for m in overlapping): menu.addAction("取消高亮")
        if any(m.get("comment") for m in overlapping): menu.addAction("删除批注")
        if not text and not overlapping:
            hint = menu.addAction("请先选择文字，或在已有高亮/批注上右键")
            hint.setEnabled(False)
        rects = hit_rects
        chosen = menu.exec(event.globalPos())
        if chosen:
            self.action.emit(chosen.text(), text, rects)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        if self.bitmap is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(QRectF(self.rect()), self.bitmap, QRectF(self.bitmap.rect()))
        painter.setPen(Qt.PenStyle.NoPen)
        def draw_rect(rect):
            r = fitz.Rect(rect) * self.page.rotation_matrix if self.page is not None else fitz.Rect(rect)
            painter.drawRect(QRect(int(r.x0*self.scale), int(r.y0*self.scale),
                                   max(1, int(r.width*self.scale)), max(1, int(r.height*self.scale))))
        painter.setBrush(QColor(255, 215, 0, 85))
        for mark in self.marks:
            if mark.get("highlight", True):
                for rect in mark["rects"]: draw_rect(rect)
        painter.setBrush(QColor(60, 140, 255, 90))
        _, rects = self.selected()
        for rect in rects: draw_rect(rect)


from bisect import bisect_right
from math import ceil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QScrollArea, QWidget, QVBoxLayout


class ContinuousPDF(QScrollArea):
    action = Signal(int, str, str, list)
    pageChanged = Signal(int)
    zoomChanged = Signal(float)

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.verticalScrollBar().setSingleStep(45)
        self.doc = None
        self.scale = 1.3
        self.pages = []
        self.offsets = []
        self.marks = []
        self.current = -1
        self.queue = []
        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.timeout.connect(self.render_next)
        self.verticalScrollBar().valueChanged.connect(self.scrolled)
        self.viewport().installEventFilter(self)
        self.viewport().grabGesture(Qt.GestureType.PinchGesture)
        self.pending_zoom = 1.0
        self.zoom_anchor = None
        self.zoom_timer = QTimer(self)
        self.zoom_timer.setSingleShot(True); self.zoom_timer.setInterval(32)
        self.zoom_timer.timeout.connect(self.apply_pending_zoom)
        self.settle_timer = QTimer(self)
        self.settle_timer.setSingleShot(True); self.settle_timer.setInterval(180)
        self.settle_timer.timeout.connect(self.scrolled)
        self.resizing_pages = False

    def clear_document(self):
        self.render_timer.stop(); self.zoom_timer.stop(); self.settle_timer.stop()
        self.queue = []; self.pending_zoom = 1.0
        self.pages = []; self.offsets = []; self.current = -1; self.doc = None; self.marks = []
        self.setWidget(QWidget())

    def load(self, doc, page=0):
        if doc is not self.doc:
            self.zoom_timer.stop(); self.settle_timer.stop(); self.pending_zoom = 1.0
        self.render_timer.stop(); self.queue = []
        self.doc = doc; self.pages = []; self.offsets = []; self.current = -1
        container = QWidget(); container.installEventFilter(self); layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12); layout.setSpacing(16)
        y = 12
        for index in range(len(doc)):
            view = PageView(); view.scale = self.scale
            view.installEventFilter(self)
            size = doc[index].rect
            view.base_size = (size.width, size.height)
            view.setFixedSize(ceil(size.width*self.scale), ceil(size.height*self.scale))
            view.setStyleSheet('background: white; color: #666;')
            view.setText(f'第 {index+1} 页 · 加载中…')
            view.action.connect(lambda action, text, rects, i=index: self.action.emit(i, action, text, rects))
            layout.addWidget(view, alignment=Qt.AlignmentFlag.AlignHCenter)
            self.pages.append(view); self.offsets.append(y)
            y += view.height() + 16
        layout.addStretch()
        self.setWidget(container)
        container.setMinimumHeight(y)
        layout.activate()
        self.jump(page)
        self.scrolled()

    def jump(self, page):
        if not self.pages: return
        page = max(0, min(len(self.pages)-1, page))
        self.verticalScrollBar().setValue(self.offsets[page])
        self.scrolled()

    def scrolled(self):
        if not self.pages or self.resizing_pages: return
        top = self.verticalScrollBar().value()
        index = max(0, min(len(self.pages)-1, bisect_right(self.offsets, top+40)-1))
        if index != self.current:
            self.current = index; self.pageChanged.emit(index)
        end = min(len(self.pages)-1, bisect_right(self.offsets, top+self.viewport().height()))
        wanted = set(range(max(0, index-1), min(len(self.pages), end+2)))
        if self.settle_timer.isActive(): return
        self.queue = [i for i in sorted(wanted, key=lambda i: abs(i-index))
                      if self.pages[i].page is None or self.pages[i].render_scale != self.scale]
        # Keep only visible pages and neighbours as raster images.
        for i, view in enumerate(self.pages):
            if i not in wanted and view.page is not None:
                view.clear(); view.page = None; view.selection = QRect()
                view.anchor = view.endpoint = None
                view.single_word = None
                view.setText(f'第 {i+1} 页')
        if self.queue and not self.render_timer.isActive(): self.render_timer.start(0)

    def render_next(self):
        if not self.queue or self.doc is None or self.settle_timer.isActive(): return
        index = self.queue.pop(0)
        view = self.pages[index]
        anchor, endpoint, single_word = view.anchor, view.endpoint, view.single_word
        view.display(self.doc[index], [m for m in self.marks if m['page'] == index])
        view.anchor, view.endpoint, view.single_word = anchor, endpoint, single_word
        if self.queue: self.render_timer.start(0)

    def set_marks(self, marks):
        self.marks = marks
        for index, view in enumerate(self.pages):
            if view.page is not None:
                view.marks = [m for m in marks if m['page'] == index]
                view.update()

    def queue_zoom(self, factor, anchor):
        if self.doc is None or factor <= 0: return
        self.pending_zoom *= factor
        self.zoom_anchor = anchor
        if not self.zoom_timer.isActive(): self.zoom_timer.start()

    def apply_pending_zoom(self):
        factor = self.pending_zoom; self.pending_zoom = 1.0
        self.zoom(factor, self.zoom_anchor)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.DevicePixelRatioChange and isinstance(watched, PageView) and watched.page is not None:
            anchor, endpoint, single_word = watched.anchor, watched.endpoint, watched.single_word
            watched.display(watched.page, watched.marks)
            watched.anchor, watched.endpoint, watched.single_word = anchor, endpoint, single_word
        if event.type() == QEvent.Type.NativeGesture:
            kind = event.gestureType()
            if kind == Qt.NativeGestureType.ZoomNativeGesture:
                anchor = self.viewport().mapFromGlobal(event.globalPosition().toPoint())
                self.queue_zoom(max(.1, 1.0 + event.value()), anchor)
                event.accept(); return True
            if kind in (Qt.NativeGestureType.BeginNativeGesture, Qt.NativeGestureType.EndNativeGesture):
                event.accept(); return True
        if event.type() == QEvent.Type.Wheel and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.pixelDelta().y() or event.angleDelta().y()
            self.queue_zoom(2 ** (delta/480), self.viewport().mapFromGlobal(event.globalPosition().toPoint()))
            event.accept(); return True
        if event.type() == QEvent.Type.Gesture:
            pinch = event.gesture(Qt.GestureType.PinchGesture)
            if pinch:
                previous = pinch.lastScaleFactor()
                factor = pinch.scaleFactor()/previous if previous else 1.0
                self.queue_zoom(factor, pinch.centerPoint().toPoint())
                event.accept(); return True
        return super().eventFilter(watched, event)

    def zoom(self, factor, anchor=None):
        if self.doc is None: return
        new_scale = max(.5, min(4, self.scale*factor))
        if abs(new_scale-self.scale) < .0001: return
        if anchor is None: anchor = self.viewport().rect().center()
        # Keep the PDF point under the gesture centre stationary in both axes.
        content_point = self.widget().mapFrom(self.viewport(), anchor)
        index = max(0, min(len(self.pages)-1, bisect_right(self.offsets, content_point.y())-1))
        view = self.pages[index]
        fraction_y = (content_point.y()-self.offsets[index]) / max(1, view.height())
        fraction_x = (content_point.x()-view.x()) / max(1, view.width())
        self.render_timer.stop()
        self.settle_timer.start()
        self.resizing_pages = True
        self.viewport().setUpdatesEnabled(False)
        ratio = new_scale/self.scale
        self.scale = new_scale
        self.zoomChanged.emit(new_scale)
        y = 12
        self.offsets = []
        for page_index, page_view in enumerate(self.pages):
            self.offsets.append(y)
            page_view.scale = new_scale
            width, height = page_view.base_size
            page_view.setFixedSize(ceil(width*new_scale), ceil(height*new_scale))
            if page_view.anchor is not None: page_view.anchor = page_view.anchor*ratio
            if page_view.endpoint is not None: page_view.endpoint = page_view.endpoint*ratio
            page_view.update()
            y += page_view.height()+16
        self.widget().setMinimumHeight(y)
        self.widget().layout().activate()
        view = self.pages[index]
        self.verticalScrollBar().setValue(self.offsets[index] + int(fraction_y*view.height()) - anchor.y())
        self.horizontalScrollBar().setValue(view.x() + int(fraction_x*view.width()) - anchor.x())
        self.resizing_pages = False
        self.viewport().setUpdatesEnabled(True)
        self.scrolled()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.scrolled()
