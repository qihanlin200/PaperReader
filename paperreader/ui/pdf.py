from paperreader.services.lazy import fitz
from paperreader.services.pdf_raster import rasterize_page_data, rasterize_pdf_file
from paperreader.ui.selection import column_words, paragraph_words
from paperreader.services.themes import get_theme
from paperreader.ui.theme import current_theme
from PySide6.QtCore import Qt, QRect, QRectF, QPoint, Signal, QEvent, QElapsedTimer, QObject
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor
from PySide6.QtWidgets import QApplication, QLabel, QMenu
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path


PINCH_ZOOM_GAIN = 1.5


_raster_pool = None


def raster_pool():
    global _raster_pool
    if _raster_pool is None:
        _raster_pool = ProcessPoolExecutor(max_workers=1, mp_context=get_context('spawn'))
    return _raster_pool


class RasterBridge(QObject):
    finished = Signal(object)


class PageView(QLabel):
    action = Signal(str, str, list)

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.click_selection = None
        self.double_click_timer = QElapsedTimer()
        self.double_click_pos = QPoint()
        self.double_click_word = None
        self.anchor = None
        self.endpoint = None
        self.page = None
        self.scale = 1.3
        self.start = None
        self.selection = QRect()
        self.marks = []
        self.words = []
        self.words_ready = False
        self.citation_rects = []
        self.bitmap = None
        self.render_scale = None
        self.fast_preview = False

    def display(self, page, marks, paper_colors=None):
        if paper_colors is None:
            theme = get_theme(current_theme())
            paper_colors = theme.pdf_paper, theme.pdf_ink
        samples, width, height, stride, density = rasterize_page_data(
            page, self.scale, self.devicePixelRatioF(), *paper_colors)
        image = QImage(samples, width, height, stride, QImage.Format.Format_RGB888).copy()
        self.display_image(page, marks, image, density)

    def display_image(self, page, marks, image, density):
        self.page, self.marks = page, marks
        if not self.words_ready:
            self.words = page.get_text("words", sort=True)
            self.words_ready = True
            self.column_cache = None
        self.selection = QRect()
        self.click_selection = None
        self.anchor = self.endpoint = None
        bitmap = QPixmap.fromImage(image)
        bitmap.setDevicePixelRatio(density)
        super().clear()
        self.bitmap = bitmap
        self.render_scale = self.scale
        self.fast_preview = False
        self.setFixedSize(ceil(page.rect.width*self.scale), ceil(page.rect.height*self.scale))
        self.update()

    def clear(self):
        self.bitmap = None
        self.fast_preview = False
        self.marks = []
        self.click_selection = None
        self.double_click_timer.invalidate()
        super().clear()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            point = event.position().toPoint()
            if self.select_paragraph_on_third_click(point):
                event.accept()
                return
            self.click_selection = None
            self.start = point
            self.anchor = self.endpoint = self.start
            self.selection = QRect()
            self.update()
            event.accept()
        else:
            self.double_click_timer.invalidate()
            event.ignore()

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.page is None:
            event.ignore(); return
        point = event.position().toPoint()
        if self.select_paragraph_on_third_click(point):
            event.accept()
            return
        self.start = None
        self.click_selection = None
        self.anchor = self.endpoint = None
        pdf_point = fitz.Point(event.position().x()/self.scale, event.position().y()/self.scale)
        pdf_point *= self.page.derotation_matrix
        for index, word in enumerate(self.words):
            if fitz.Rect(word[:4]).contains(pdf_point):
                self.click_selection = (word[4], [list(word[:4])])
                self.double_click_pos = point
                self.double_click_word = index
                self.double_click_timer.start()
                break
        self.update()
        event.accept()

    def select_paragraph_on_third_click(self, point):
        if not self.double_click_timer.isValid():
            return False
        elapsed = self.double_click_timer.elapsed()
        self.double_click_timer.invalidate()
        hints = QApplication.styleHints()
        delta = point - self.double_click_pos
        if (self.click_selection is None or elapsed > hints.mouseDoubleClickInterval()
                or max(abs(delta.x()), abs(delta.y())) > hints.mouseDoubleClickDistance()):
            return False
        word = self.words[self.double_click_word]
        rect = fitz.Rect(word[:4])
        anchor = (rect.tl + rect.br) / 2
        words = column_words(self.words, anchor, self.page.cropbox.width, self.page.cropbox.height)
        self.click_selection = self.selected_text(paragraph_words(words, word))
        self.update()
        return True

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
        if self.page is not None and self.click_selection is not None:
            return self.click_selection
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
        return self.selected_text(words[first:last+1])

    @staticmethod
    def selected_text(selected):
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
        menu.setObjectName("PdfSelectionMenu")
        hit_rects = rects
        if not hit_rects and self.page is not None:
            point = fitz.Point(event.pos().x()/self.scale, event.pos().y()/self.scale) * self.page.derotation_matrix
            hit_rects = [r for mark in self.marks for r in mark["rects"] if fitz.Rect(r).contains(point)]
        overlapping = [mark for mark in self.marks if any(fitz.Rect(a).intersects(fitz.Rect(b)) for a in hit_rects for b in mark["rects"])]
        if text:
            for name in ["复制", "翻译所选内容", "针对所选内容提问"]:
                menu.addAction(name)
            menu.addSeparator()
            menu.addAction("高亮")
            menu.addAction("添加批注")
        has_highlight = any(m.get("highlight", True) for m in overlapping)
        has_comment = any(m.get("comment") for m in overlapping)
        if text and (has_highlight or has_comment):
            menu.addSeparator()
        if has_highlight: menu.addAction("取消高亮")
        if has_comment: menu.addAction("删除批注")
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
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, not self.fast_preview)
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
        if self.page is not None:
            painter.setBrush(QColor(26, 190, 155, 100))
            for rect in self.citation_rects:
                draw_rect(rect)
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
        self.follow_theme = True
        self.pages = []
        self.offsets = []
        self.marks = []
        self.current = -1
        self.citation_page = None
        self.queue = []
        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.timeout.connect(self.render_next)
        self.render_generation = 0
        self.render_job = None
        self.render_bridge = RasterBridge(self)
        self.render_bridge.finished.connect(self.apply_render_result)
        self.verticalScrollBar().valueChanged.connect(self.scrolled)
        self.viewport().installEventFilter(self)
        self.viewport().grabGesture(Qt.GestureType.PinchGesture)
        self.gesture_active = False
        self.pinch_source = None
        self.settle_timer = QTimer(self)
        self.settle_timer.setSingleShot(True); self.settle_timer.setInterval(180)
        self.settle_timer.timeout.connect(self.finish_zoom_preview)
        self.resizing_pages = False

    def clear_document(self):
        self.render_timer.stop(); self.settle_timer.stop()
        self.render_generation += 1
        self.queue = []; self.gesture_active = False; self.pinch_source = None
        self.pages = []; self.offsets = []; self.current = -1; self.doc = None; self.marks = []
        self.citation_page = None
        self.setWidget(QWidget())

    def load(self, doc, page=0):
        if doc is not self.doc:
            self.settle_timer.stop(); self.gesture_active = False; self.pinch_source = None
        self.render_timer.stop(); self.queue = []
        self.render_generation += 1
        self.doc = doc; self.pages = []; self.offsets = []; self.current = -1
        self.citation_page = None
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

    def clear_citation(self):
        if self.citation_page is not None:
            previous = self.pages[self.citation_page]
            previous.citation_rects = []
            previous.update()
            self.citation_page = None

    def show_citation(self, page, rects):
        self.clear_citation()
        self.citation_page = page
        view = self.pages[page]
        view.citation_rects = rects
        view.update()
        if not rects:
            self.jump(page)
            return
        pdf_page = self.doc[page]
        first = fitz.Rect(rects[0]) * pdf_page.rotation_matrix
        x = view.x() + round((first.x0 + first.x1) * self.scale / 2)
        y = self.offsets[page] + round(first.y0 * self.scale)
        horizontal = self.horizontalScrollBar()
        if not horizontal.value() <= x < horizontal.value() + self.viewport().width():
            horizontal.setValue(x - self.viewport().width() // 2)
        self.verticalScrollBar().setValue(y - self.viewport().height() // 4)
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
                view.setText(f'第 {i+1} 页')
        if self.queue and not self.render_timer.isActive(): self.render_timer.start(0)

    def render_next(self):
        if not self.queue or self.doc is None or self.settle_timer.isActive() or self.render_job is not None: return
        index = self.queue.pop(0)
        view = self.pages[index]
        path = getattr(self.doc, 'name', '')
        if view.bitmap is not None and path and Path(path).is_file():
            paper_color, ink_color = self.pdf_colors()
            future = raster_pool().submit(rasterize_pdf_file, path, index, self.scale,
                                          view.devicePixelRatioF(), paper_color, ink_color)
            self.render_job = future
            bridge = self.render_bridge
            generation, scale = self.render_generation, self.scale
            def finished(result):
                try: bridge.finished.emit((generation, index, scale, result))
                except RuntimeError: pass  # Window closed before the process finished.
            future.add_done_callback(finished)
            return
        anchor, endpoint, click_selection = view.anchor, view.endpoint, view.click_selection
        view.display(self.doc[index], [m for m in self.marks if m['page'] == index], self.pdf_colors())
        view.anchor, view.endpoint, view.click_selection = anchor, endpoint, click_selection
        if self.queue: self.render_timer.start(0)

    def apply_render_result(self, result):
        generation, index, scale, future = result
        self.render_job = None
        if (self.doc is not None and generation == self.render_generation
                and scale == self.scale and index < len(self.pages)
                and self.page_is_visible(index)):
            try:
                samples, width, height, stride, density = future.result()
            except Exception:
                pass  # Retain the scaled preview if background rendering fails.
            else:
                image = QImage(samples, width, height, stride, QImage.Format.Format_RGB888).copy()
                view = self.pages[index]
                anchor, endpoint, click_selection = view.anchor, view.endpoint, view.click_selection
                view.display_image(self.doc[index], [m for m in self.marks if m['page'] == index],
                                   image, density)
                view.anchor, view.endpoint, view.click_selection = anchor, endpoint, click_selection
        if self.queue and not self.settle_timer.isActive(): self.render_timer.start(0)

    def page_is_visible(self, index):
        top = self.verticalScrollBar().value()
        first = max(0, bisect_right(self.offsets, top+40)-1)
        last = min(len(self.pages)-1, bisect_right(self.offsets, top+self.viewport().height()))
        return max(0, first-1) <= index <= min(len(self.pages)-1, last+1)

    def refresh_theme(self):
        if self.follow_theme:
            self.refresh_pdf_colors()

    def pdf_colors(self):
        if not self.follow_theme:
            return "#ffffff", "#000000"
        theme = get_theme(current_theme())
        return theme.pdf_paper, theme.pdf_ink

    def set_follow_theme(self, enabled):
        enabled = bool(enabled)
        if enabled == self.follow_theme:
            return
        self.follow_theme = enabled
        self.refresh_pdf_colors()

    def refresh_pdf_colors(self):
        self.render_generation += 1
        for view in self.pages:
            view.render_scale = None
        self.scrolled()

    def set_marks(self, marks):
        self.marks = marks
        for index, view in enumerate(self.pages):
            if view.page is not None:
                view.marks = [m for m in marks if m['page'] == index]
                view.update()

    def finish_zoom_preview(self):
        self.gesture_active = False; self.pinch_source = None
        for view in self.pages:
            if view.fast_preview and view.render_scale == self.scale:
                view.fast_preview = False
                view.update()
        self.scrolled()

    def end_zoom_gesture(self):
        self.gesture_active = False; self.pinch_source = None
        if self.settle_timer.isActive():
            self.settle_timer.start(90)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.DevicePixelRatioChange and isinstance(watched, PageView) and watched.page is not None:
            anchor, endpoint, click_selection = watched.anchor, watched.endpoint, watched.click_selection
            watched.display(watched.page, watched.marks, self.pdf_colors())
            watched.anchor, watched.endpoint, watched.click_selection = anchor, endpoint, click_selection
        if event.type() == QEvent.Type.NativeGesture:
            kind = event.gestureType()
            if kind == Qt.NativeGestureType.ZoomNativeGesture:
                if abs(event.value()) > .00001 and self.pinch_source in (None, 'native'):
                    self.pinch_source = 'native'
                    anchor = self.viewport().mapFromGlobal(event.globalPosition().toPoint())
                    self.gesture_active = True
                    self.zoom(max(.1, 1.0 + event.value()) ** PINCH_ZOOM_GAIN, anchor)
                event.accept(); return True
            if kind == Qt.NativeGestureType.BeginNativeGesture:
                self.gesture_active = True
                event.accept(); return True
            if kind == Qt.NativeGestureType.EndNativeGesture:
                self.end_zoom_gesture()
                event.accept(); return True
        if event.type() == QEvent.Type.Wheel and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            pixel_delta = event.pixelDelta().y()
            delta = pixel_delta or event.angleDelta().y()
            if delta and self.pinch_source in (None, 'wheel'):
                self.pinch_source = 'wheel'
                gain = PINCH_ZOOM_GAIN if pixel_delta or self.gesture_active else 1.0
                self.zoom(2 ** (delta*gain/480),
                          self.viewport().mapFromGlobal(event.globalPosition().toPoint()))
            event.accept(); return True
        if event.type() == QEvent.Type.Gesture:
            pinch = event.gesture(Qt.GestureType.PinchGesture)
            if pinch:
                # macOS may deliver Qt pinch, native magnification, or Ctrl+wheel.
                # Use whichever produces the first zoom update for this gesture.
                previous = pinch.lastScaleFactor()
                factor = pinch.scaleFactor()/previous if previous else 1.0
                if abs(factor-1.0) > .00001 and self.pinch_source in (None, 'qt'):
                    self.pinch_source = 'qt'
                    self.gesture_active = True
                    self.zoom(factor ** PINCH_ZOOM_GAIN, pinch.centerPoint().toPoint())
                if self.pinch_source == 'qt' and pinch.state() in (
                        Qt.GestureState.GestureFinished, Qt.GestureState.GestureCanceled):
                    self.end_zoom_gesture()
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
        self.render_generation += 1
        self.settle_timer.start(500 if self.gesture_active else 180)
        self.resizing_pages = True
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
            if page_view.bitmap is not None: page_view.fast_preview = True
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
        self.scrolled()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.scrolled()
