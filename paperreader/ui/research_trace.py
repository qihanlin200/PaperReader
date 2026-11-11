"""Native run timeline with a fixed export action."""
from datetime import datetime
from math import cos, tau
import re
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from paperreader.ui.theme import theme_color
from paperreader.ui.work_rail import menu_symbol_icon


def text(value, style="", wrap=False):
    label = QLabel(value)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setObjectName(style)
    label.setWordWrap(wrap)
    return label


def icon(symbol, size=20):
    label = QLabel()
    label.setPixmap(menu_symbol_icon(symbol).pixmap(size, size))
    label.setFixedSize(size, size)
    return label


BREATH_FRAMES = 34


def breath_color(phase):
    brightness = (1 - cos(tau * phase / BREATH_FRAMES)) / 2
    color = QColor(theme_color("#66ddda"))
    color.setAlphaF(0.25 + 0.73 * brightness)
    return color


class TimelineMarker(QWidget):
    phase = 0
    def __init__(self, state, first, last):
        super().__init__()
        self.state, self.first, self.last = state, first, last
        self.setFixedWidth(24)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = QColor(theme_color("#66ddda"))
        muted = QColor(theme_color("#64768d"))
        dark = QColor(theme_color("#101824"))
        x, y = 12, 22
        for endpoint, enabled, completed in ((0, not self.first, self.state != "terminal"),
                                             (self.height(), not self.last, self.state == "done")):
            if enabled:
                painter.setPen(QPen(accent if completed else muted, 2))
                painter.drawLine(QPointF(x, y), QPointF(x, endpoint))
        dot = breath_color(self.phase) if self.state == "active" else accent
        painter.setPen(QPen(muted if self.state == "terminal" else dot, 2))
        painter.setBrush(accent if self.state == "done" else dark)
        painter.drawEllipse(QPointF(x, y), 7, 7)
        if self.state == "active":
            painter.setBrush(dot)
            painter.drawEllipse(QPointF(x, y), 3, 3)
        elif self.state == "done":
            painter.setPen(QPen(dark, 1.6))
            painter.drawLine(QPointF(x - 3, y), QPointF(x - 1, y + 2))
            painter.drawLine(QPointF(x - 1, y + 2), QPointF(x + 4, y - 3))


class TraceBreathingFrame(QFrame):
    running = False
    phase = 0

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.running:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(breath_color(self.phase), 1.5))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 9, 9)


class TracePulse(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(24, 20)
        self.phase = 0
        self.running = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(theme_color("#66ddda" if self.running else "#a6b8ce"))
        painter.setPen(QPen(color, 1.6))
        path = QPainterPath(QPointF(1, 10))
        for x, y in ((6, 10), (9, 4), (12, 16), (15, 7), (18, 10), (23, 10)):
            path.lineTo(x, y)
        painter.drawPath(path)
        if self.running:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(path.pointAtPercent(self.phase / 24), 2.2, 2.2)
        painter.end()


class ResearchTrace(QWidget):
    toggle_requested = Signal(int)
    export_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("ResearchTimeline")
        self.snapshot = None
        self.rows = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(9)
        self.header = TraceBreathingFrame()
        self.header.setObjectName("TraceRunHeader")
        row = QHBoxLayout(self.header)
        row.setContentsMargins(10, 8, 10, 8)
        self.run_icon = TracePulse()
        row.addWidget(self.run_icon)
        self.run_label = text("", "TraceTitle")
        row.addWidget(self.run_label)
        self.run_status = text("", "TraceStatus")
        row.addWidget(self.run_status, 1)
        self.elapsed = text("", "TraceDuration")
        row.addWidget(self.elapsed)
        self.info = icon("info", 16)
        row.addWidget(self.info)
        layout.addWidget(self.header)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("TraceScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        panel = QWidget()
        self.events_layout = QVBoxLayout(panel)
        self.events_layout.setContentsMargins(0, 0, 1, 0)
        self.events_layout.setSpacing(0)
        self.empty = text("暂无执行记录。", "TraceMuted", True)
        self.events_layout.addWidget(self.empty)
        self.events_layout.addStretch()
        self.scroll.setWidget(panel)
        self.follow_timer = QTimer(self)
        self.follow_timer.setSingleShot(True)
        self.follow_timer.timeout.connect(self.follow_latest)
        self.following = True
        bar = self.scroll.verticalScrollBar()
        bar.sliderPressed.connect(self.follow_timer.stop)
        bar.valueChanged.connect(self.scroll_position_changed)
        bar.rangeChanged.connect(self.scroll_range_changed)
        layout.addWidget(self.scroll, 1)
        self.export = QPushButton(menu_symbol_icon("download"), "导出 Trace")
        self.export.setObjectName("TraceExport")
        self.export.clicked.connect(self.export_requested)
        layout.addWidget(self.export)
        self.clock = QTimer(self)
        self.clock.setInterval(55)
        self.clock.timeout.connect(self.update_clock)
        self.started = None
        self.ended = None
        self.show_events("", "", [])

    def update_clock(self):
        self.run_icon.phase = (self.run_icon.phase + 1) % 24
        self.run_icon.update()
        if self.header.running:
            phase = self.header.phase = (self.header.phase + 1) % BREATH_FRAMES
            self.header.update()
            if self.rows and self.rows[-1].marker.state == "active":
                row = self.rows[-1]
                row.marker.phase = row.tile.phase = phase
                row.marker.update()
                row.tile.update()
        if self.started is not None:
            now = self.ended or datetime.now(tz=self.started.tzinfo)
            seconds = max(0, int((now - self.started).total_seconds()))
            hours, remainder = divmod(seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            self.elapsed.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

    def scroll_position_changed(self, value):
        self.following = value == self.scroll.verticalScrollBar().maximum()
        if not self.following:
            self.follow_timer.stop()

    def scroll_range_changed(self, _minimum, _maximum):
        if self.following:
            self.follow_latest()

    def follow_latest(self):
        bar = self.scroll.verticalScrollBar()
        if not bar.isSliderDown():
            bar.setValue(bar.maximum())

    def show_events(self, label, status, events, started="", ended=""):
        events = tuple(events)
        snapshot = (label, status, events)
        if snapshot == self.snapshot:
            return
        bar = self.scroll.verticalScrollBar()
        same_run = self.snapshot is not None and self.snapshot[0] == label
        previous = self.snapshot[2] if same_run else ()
        if not same_run:
            self.following = True
        self.snapshot = snapshot
        self.header.setVisible(bool(label))
        self.export.setVisible(bool(label))
        self.empty.setVisible(not events)
        self.run_label.setText(label)
        self.run_status.setText("· " + status)
        self.run_icon.running = status == "运行中"
        if self.header.running != self.run_icon.running:
            self.header.running = self.run_icon.running
            self.header.phase = 0
            self.header.update()
        self.started = datetime.fromisoformat(started) if started else None
        self.ended = datetime.fromisoformat(ended) if ended and not self.run_icon.running else None
        self.elapsed.setVisible(self.started is not None)
        if self.run_icon.running:
            self.clock.start()
        else:
            self.clock.stop()
        self.update_clock()
        self.info.setToolTip(f"{len(events)} 条执行事件")
        keep = min(len(previous), len(events))
        for row in self.rows[keep:]:
            self.remove_row(row)
        del self.rows[keep:]
        for index, event in enumerate(events):
            last = index == len(events) - 1
            if index < keep and previous[index][:-2] == event[:-2]:
                marker = self.rows[index].marker
                state = self.marker_state(event)
                if (marker.state, marker.last) != (state, last):
                    marker.state, marker.last = state, last
                    marker.update()
                    self.style_tile(self.rows[index].tile, event)
                    self.rows[index].tile.update()
                continue
            row = self.event_row(index, event, first=index == 0, last=last)
            if index < keep:
                self.remove_row(self.rows[index])
                self.rows[index] = row
            else:
                self.rows.append(row)
            self.events_layout.insertWidget(index + 1, row)
        if self.following and not bar.isSliderDown():
            self.follow_timer.start(0)
        else:
            self.follow_timer.stop()

    def remove_row(self, row):
        self.events_layout.removeWidget(row)
        row.hide()
        row.deleteLater()

    @staticmethod
    def marker_state(event):
        return "active" if event[-2] else "terminal" if event[-1] else "done"

    @staticmethod
    def style_tile(tile, event):
        tile.running = event[-2]
        name = "TraceEventActive" if event[4] and not tile.running else "TraceEvent"
        if tile.objectName() != name:
            tile.setObjectName(name)
            tile.style().unpolish(tile)
            tile.style().polish(tile)
            tile.update()

    def event_row(self, index, event, *, first, last):
        stage, timestamp, elapsed, details, expanded, symbol, _, _ = event
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        row.marker = TimelineMarker(self.marker_state(event), first, last)
        layout.addWidget(row.marker)
        tile = row.tile = TraceBreathingFrame()
        self.style_tile(tile, event)
        outer = QVBoxLayout(tile)
        outer.setContentsMargins(10, 8, 9, 8)
        outer.setSpacing(6)
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_row.addWidget(icon(symbol, 18), 0, Qt.AlignmentFlag.AlignTop)
        title = text(stage, "TraceTitle", True)
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        title_row.addWidget(title, 1)
        title_row.addWidget(text(timestamp, "TraceMuted"), 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(title_row)
        summary = QHBoxLayout()
        summary.setSpacing(5)
        summary.addSpacing(24)
        excerpt = details if len(details) <= 92 else details[:92] + "…"
        description = text(excerpt, "TraceMuted", True)
        description.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        summary.addWidget(description, 1)
        summary.addWidget(text(elapsed or "—", "TraceDuration"), 0, Qt.AlignmentFlag.AlignTop)
        if details:
            toggle = QPushButton("⌃" if expanded else "⌄")
            toggle.setObjectName("TraceExpand")
            toggle.setAccessibleName("收起事件详情" if expanded else "展开事件详情")
            toggle.clicked.connect(lambda: self.toggle_requested.emit(index))
            summary.addWidget(toggle, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(summary)
        if expanded:
            fields = []
            if stage.startswith("模型分析 · "):
                fields.append(("模型", stage.partition(" · ")[2]))
                count = re.search(r"(\d+) 段证据", details)
                if count:
                    fields.append(("来源", f"{count[1]} 段"))
            if elapsed:
                fields.append(("耗时", elapsed))
            for name, value in fields:
                metrics = QHBoxLayout()
                metrics.addWidget(text(name, "TraceDuration"))
                metrics.addWidget(text(value, "TraceMuted", True), 1)
                outer.addLayout(metrics)
            line = QFrame()
            line.setObjectName("TraceDivider")
            line.setFixedHeight(1)
            outer.addWidget(line)
            outer.addWidget(text("事件详情", "TraceTitle"))
            outer.addWidget(text(details, "TraceMuted", True))
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 8)
        column.addWidget(tile)
        layout.addLayout(column, 1)
        return row
