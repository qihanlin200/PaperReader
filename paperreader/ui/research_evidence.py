"""Responsive masonry layout for research evidence."""
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget


class EvidenceMatrix(QScrollArea):
    anchorClicked = Signal(QUrl)
    MIN_CARD_WIDTH = 144
    MIN_CARD_HEIGHT = 155
    GAP = 12

    def __init__(self):
        super().__init__()
        self.body = QWidget()
        self.setWidget(self.body)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.cards = []
        self.entries = None
        self.empty = QLabel("暂无可展示的证据。", self.body)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_entries(self, entries):
        if entries == self.entries:
            return
        self.entries = entries
        for card in self.cards:
            card.hide()
            card.deleteLater()
        self.cards.clear()
        for title, excerpt, metadata, url in entries:
            card = QPushButton(self.body)
            card.setObjectName("ResearchEvidenceCard")
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.setAccessibleName(title)
            card.clicked.connect(lambda checked=False, target=url: self.anchorClicked.emit(QUrl(target)))
            layout = QVBoxLayout(card)
            layout.setContentsMargins(14, 14, 14, 14)
            layout.setSpacing(10)
            number, separator, headline = title.partition(" · ")
            meta = " · ".join(part for part in (number if separator else "", metadata) if part)
            excerpt = " ".join(excerpt.split())
            if len(excerpt) > 90:
                excerpt = excerpt[:90].rstrip() + "…"
            fields = ((meta, "ResearchEvidenceMeta"), (headline if separator else title, "ResearchEvidenceTitle"),
                      (excerpt, "ResearchEvidenceMeta"), ("查看引用 ›", "ResearchEvidenceLink"))
            for value, style in fields:
                if not value:
                    continue
                if style == "ResearchEvidenceLink":
                    divider = QFrame()
                    divider.setObjectName("ResearchOverviewDivider")
                    divider.setFixedHeight(1)
                    divider.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                    layout.addStretch()
                    layout.addWidget(divider)
                label = QLabel(value)
                label.setObjectName(style)
                label.setTextFormat(Qt.TextFormat.PlainText)
                label.setWordWrap(True)
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                layout.addWidget(label)
            self.cards.append(card)
            card.show()
        self.empty.setVisible(not self.cards)
        self.reflow()
        self.verticalScrollBar().setValue(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()

    def reflow(self):
        if not hasattr(self, "cards"):
            return
        width = self.viewport().width()
        gap = self.GAP
        available = max(1, width - 2 * gap)
        count = max(1, (available + gap) // (self.MIN_CARD_WIDTH + gap))
        card_width = max(1, (available - (count - 1) * gap) // count)
        heights = [gap] * count
        for card in self.cards:
            column = min(range(count), key=heights.__getitem__)
            height = max(self.MIN_CARD_HEIGHT, card.layout().heightForWidth(card_width))
            card.setGeometry(gap + column * (card_width + gap), heights[column], card_width, height)
            heights[column] += height + gap
        height = max(max(heights), self.viewport().height())
        self.body.resize(width, height)
        self.empty.setGeometry(0, 0, width, height)
