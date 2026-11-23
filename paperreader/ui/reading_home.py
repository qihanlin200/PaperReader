"""Theme-aware landing page for the reading workspace."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QMovie, QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from paperreader.services.themes import THEME_ROOT
from paperreader.ui.work_rail import menu_symbol_icon


class ContentButton(QPushButton):
    """Size a clickable row or brand from its child widgets."""
    def sizeHint(self):
        self.ensurePolished()
        return self.layout().sizeHint()

    def minimumSizeHint(self):
        self.ensurePolished()
        return self.layout().minimumSize()


class ReadingHomeBody(QWidget):
    def __init__(self):
        super().__init__()
        self.background_movie = None
        self.background_still = QPixmap()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)

    def paintEvent(self, event):
        super().paintEvent(event)
        frame = (self.background_movie.currentPixmap()
                 if self.background_movie is not None else QPixmap())
        if frame.isNull():
            frame = self.background_still
        if frame.isNull():
            return
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.setOpacity(0.5)
            source = QRectF(frame.rect())
            target = QRectF(self.rect())
            source_ratio = source.width() / source.height()
            target_ratio = target.width() / target.height()
            if source_ratio > target_ratio:
                width = source.height() * target_ratio
                source.setLeft((source.width() - width) / 2)
                source.setWidth(width)
            else:
                height = source.width() / target_ratio
                source.setTop((source.height() - height) / 2)
                source.setHeight(height)
            painter.drawPixmap(target, frame, source)

    def set_theme(self, theme):
        if self.background_movie is not None:
            self.background_movie.stop()
            self.background_movie.deleteLater()
            self.background_movie = None
        self.background_still = QPixmap()
        if theme == "naruto":
            folder = THEME_ROOT / theme
            self.background_still = QPixmap(str(folder / "home-background.png"))
            movie = QMovie(str(folder / "home-background.gif"), parent=self)
            if movie.isValid():
                movie.setSpeed(100)
                movie.frameChanged.connect(self.update)
                self.background_movie = movie
                if self.isVisible():
                    movie.start()
            else:
                movie.deleteLater()
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if self.background_movie is not None:
            self.background_movie.start()

    def hideEvent(self, event):
        if self.background_movie is not None:
            self.background_movie.stop()
        super().hideEvent(event)


class ReadingHome(QScrollArea):
    SLOGANS = {
        "dark": "从一个问题，读到一条线索",
        "naruto": "木ノ葉が舞うところに、火は燃え続ける",
        "cat": "先趴一会儿，顺便读读世界",
    }

    ART_BACKGROUNDS = {"dark": "#091425", "naruto": "#201b16", "cat": "#220d07"}

    def __init__(self, import_pdf, open_paper):
        super().__init__()
        self.open_paper = open_paper
        self.setObjectName("ReadingHome")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = ReadingHomeBody()
        body.setObjectName("ReadingHomeBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(22, 24, 22, 24)
        layout.addStretch()
        self.art = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.art.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.art)
        self.title = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.title.setObjectName("ReadingHomeTitle")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        hint = QLabel("从左侧选择一篇论文，或导入新的 PDF。", alignment=Qt.AlignmentFlag.AlignCenter)
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addSpacing(10)
        button = ContentButton()
        button.setObjectName("Primary")
        button.setAccessibleName("导入 PDF")
        content = QHBoxLayout(button)
        content.setContentsMargins(14, 8, 14, 8)
        content.setSpacing(9)
        content.addStretch()
        self.import_icon = QLabel()
        self.import_icon.setFixedSize(19, 19)
        text = QLabel("导入 PDF")
        text.setObjectName("ReadingHomeImportLabel")
        for child in (self.import_icon, text):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            content.addWidget(child)
        content.addStretch()
        button.setMinimumWidth(126)
        button.clicked.connect(import_pdf)
        layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(20)
        self.recent = QWidget()
        self.recent.setMaximumWidth(860)
        self.recent.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.rows = QVBoxLayout(self.recent)
        self.rows.setContentsMargins(0, 0, 0, 0)
        recent_line = QHBoxLayout()
        recent_line.addStretch(1)
        recent_line.addWidget(self.recent, 6)
        recent_line.addStretch(1)
        layout.addLayout(recent_line)
        layout.addStretch()
        self.setWidget(body)
        self.artwork = QPixmap()

    def set_theme(self, theme):
        theme = theme if theme in self.SLOGANS else "dark"
        self.title.setText(self.SLOGANS[theme])
        self.import_icon.setPixmap(menu_symbol_icon("upload", color="#092426", size=19).pixmap(19, 19))
        self.widget().set_theme(theme)
        self.widget().setStyleSheet(
            f"QWidget#ReadingHomeBody {{ background-color: {self.ART_BACKGROUNDS[theme]}; }}")
        self.artwork = QPixmap(str(THEME_ROOT / theme / "home.webp"))
        self.refresh_art()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh_art()

    def refresh_art(self):
        if self.artwork.isNull():
            return
        ratio = self.devicePixelRatioF()
        artwork = self.artwork.scaled(
            round(min(540, max(1, self.viewport().width() - 48)) * ratio), round(205 * ratio),
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        blended = QPixmap(artwork.size())
        blended.fill(Qt.GlobalColor.transparent)
        with QPainter(blended) as painter:
            painter.drawPixmap(0, 0, artwork)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            for end_x, end_y in ((artwork.width(), 0), (0, artwork.height())):
                fade = QLinearGradient(0, 0, end_x, end_y)
                for stop, alpha in ((0, 0), (0.12, 255), (0.88, 255), (1, 0)):
                    fade.setColorAt(stop, QColor(0, 0, 0, alpha))
                painter.fillRect(blended.rect(), fade)
        blended.setDevicePixelRatio(ratio)
        self.art.setPixmap(blended)

    def set_recent(self, entries):
        while self.rows.count():
            self.rows.takeAt(0).widget().deleteLater()
        self.recent.setVisible(bool(entries))
        if entries:
            self.rows.addWidget(QLabel("最近阅读"))
        for identifier, title, timestamp in entries:
            row = ContentButton()
            row.setObjectName("ReadingHomeRecent")
            row.setAccessibleName(f"{title}，最近阅读时间 {timestamp}")
            row.setToolTip(title)
            content = QHBoxLayout(row)
            content.setContentsMargins(12, 11, 12, 11)
            icon = QLabel()
            icon.setPixmap(menu_symbol_icon("paper").pixmap(16, 16))
            name = QLabel(title)
            name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            time = QLabel(timestamp)
            time.setObjectName("Muted")
            time.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for label in (icon, name, time):
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                content.addWidget(label, 1 if label is name else 0)
            row.clicked.connect(lambda checked=False, paper_id=identifier: self.open_paper(paper_id))
            self.rows.addWidget(row)
