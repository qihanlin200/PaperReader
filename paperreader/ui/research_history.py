"""Date-grouped research run history."""
from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .research_overview import WrappedOverviewLabel


def trace_time(event):
    try:
        return datetime.fromisoformat(event[0])
    except (IndexError, ValueError, TypeError):
        return None


class ResearchHistory(QScrollArea):
    anchorClicked = Signal(QUrl)

    def __init__(self, action="查看 Trace ›", scheme="research-trace", empty="暂无执行记录。"):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        panel = QWidget()
        self.rows = QVBoxLayout(panel)
        self.rows.setContentsMargins(16, 14, 16, 14)
        self.rows.setSpacing(9)
        self.setWidget(panel)
        self.action, self.scheme, self.empty = action, scheme, empty
        self.snapshot = None
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update_elapsed)
        self.running = []

    def update_elapsed(self):
        for label, start in self.running:
            self.set_metadata(label, start, datetime.now(start.tzinfo))

    @staticmethod
    def set_metadata(label, start, end):
        timestamp = start.strftime("%H:%M") if start else "时间未知"
        duration = "—"
        if start and end and start.tzinfo == end.tzinfo:
            minutes, seconds = divmod(max(0, int((end - start).total_seconds())), 60)
            duration = f"{minutes} 分 {seconds:02d} 秒"
        label.setText(f"{timestamp}   ·   运行时长 {duration}")

    def set_runs(self, runs, eligible=lambda run: True):
        entries = []
        for index, run in enumerate(runs):
            if not eligible(run):
                continue
            events = run.get("trace") or []
            start = trace_time(events[0]) if events else None
            end = trace_time(events[-1]) if events and run["status"] != "运行中" else None
            entries.append((index, run["id"], run["question"], run["status"], start, end))
        today = date.today()
        if self.snapshot == (today, entries):
            return
        self.snapshot = (today, entries)
        self.running.clear()
        while self.rows.count():
            widget = self.rows.takeAt(0).widget()
            if widget:
                widget.hide()
                widget.deleteLater()
        if not entries:
            self.rows.addWidget(QLabel(self.empty))
        previous = object()
        entries.sort(key=lambda entry: (entry[4].timestamp() if entry[4] else float("-inf"), entry[0]), reverse=True)
        for index, _, question, status, start, end in entries:
            day = start.date() if start else None
            if day != previous:
                title = {today: "今天", today - timedelta(days=1): "昨天"}.get(day)
                group = QLabel(title or (day.isoformat() if day else "日期未知"))
                group.setObjectName("ResearchOverviewTitle")
                self.rows.addWidget(group)
                previous = day
            card = QFrame()
            active = status == "运行中"
            card.setObjectName("ResearchHistoryActive" if active else "ResearchHistoryRow")
            row = QHBoxLayout(card)
            row.setContentsMargins(12, 10, 12, 10)
            marker = QLabel({"已完成": "✓", "运行中": "◔", "已停止": "■"}.get(status, "·"))
            marker.setObjectName("ResearchHistoryMarker")
            marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
            marker.setFixedSize(24, 24)
            row.addWidget(marker)
            content = QVBoxLayout()
            content.setSpacing(3)
            question_label = WrappedOverviewLabel(question)
            question_label.setTextFormat(Qt.TextFormat.PlainText)
            question_label.setWordWrap(True)
            question_label.setObjectName("ResearchTaskName")
            content.addWidget(question_label)
            metadata = QLabel()
            metadata.setObjectName("ResearchOverviewMuted")
            metadata.setWordWrap(True)
            self.set_metadata(metadata, start, end)
            content.addWidget(metadata)
            row.addLayout(content, 1)
            badge = QLabel("执行中" if active else status)
            badge.setObjectName("ResearchTaskActiveBadge" if active else
                                "ResearchTaskDoneBadge" if status == "已完成" else "ResearchTaskBadge")
            row.addWidget(badge)
            trace = QPushButton(self.action)
            trace.setObjectName("Quiet")
            trace.clicked.connect(lambda checked=False, i=index:
                                  self.anchorClicked.emit(QUrl(f"{self.scheme}:{i}")))
            row.addWidget(trace)
            self.rows.addWidget(card)
            if active and start:
                self.running.append((metadata, start))
        self.rows.addStretch()
        if self.running:
            self.update_elapsed()
            self.timer.start()
        else:
            self.timer.stop()
