"""Deep-space desktop theme, shared by the main window and dialogs."""
import re
from pathlib import Path
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QMovie, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication, QCheckBox, QWidget
from paperreader.services.themes import DEFAULT_THEME_ID, get_theme

BACKGROUND = '#0b1019'
PANEL = '#101824'
TEXT = '#e4ebf5'
ACCENT = '#66ddda'
_HEX_COLOR = re.compile(r'#[0-9a-fA-F]{6}(?![0-9a-fA-F])')


def current_theme():
    app = QApplication.instance()
    return (app.property('paperreaderTheme') or DEFAULT_THEME_ID) if app else DEFAULT_THEME_ID


def theme_color(color, theme=None):
    pack = get_theme(theme or current_theme())
    if color.lower() in pack.colors:
        return pack.colors[color.lower()]
    if not pack.warm_surfaces:
        return color
    rgb = QColor(color)
    if rgb.blue() <= rgb.red():
        return color
    # Warm the remaining blue surfaces and muted text while keeping luminance.
    level = round(0.21 * rgb.red() + 0.72 * rgb.green() + 0.07 * rgb.blue())
    return QColor(min(255, level + 5), level, max(0, level - 8)).name()


def theme_css(css, theme=None):
    theme = theme or current_theme()
    return _HEX_COLOR.sub(lambda match: theme_color(match[0], theme), css)


class ThemeSwitch(QCheckBox):
    """An accessible check box painted as a theme-aware sliding switch."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(36)
        self.toggled.connect(lambda checked: self.setAccessibleDescription(
            "已开启" if checked else "已关闭"))
        self.setAccessibleDescription(self.status_text())

    def status_text(self):
        return "已开启" if self.isChecked() else "已关闭"

    def sizeHint(self):
        original = super().sizeHint()
        label_width = self.fontMetrics().horizontalAdvance(self.text())
        status_width = self.fontMetrics().horizontalAdvance("已开启")
        return QSize(max(original.width(), 64 + label_width + 18 + status_width),
                     max(original.height(), 36))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(2, (self.height() - 26) / 2, 48, 26)
        if self.hasFocus():
            painter.setPen(QColor(theme_color('#eaf4ff')))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(track.adjusted(-2, -2, 2, 2), 15, 15)
        painter.setPen(QColor(theme_color('#66ddda' if self.isChecked() else '#91aabd')))
        painter.setBrush(QColor(theme_color('#66ddda' if self.isChecked() else '#213243')))
        painter.drawRoundedRect(track, 13, 13)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme_color('#092426' if self.isChecked() else '#eaf4ff')))
        thumb_x = track.right() - 23 if self.isChecked() else track.left() + 3
        painter.drawEllipse(QRectF(thumb_x, track.top() + 3, 20, 20))
        label_color = self.palette().color(QPalette.ColorRole.Text)
        if not self.isEnabled():
            label_color.setAlpha(120)
        painter.setPen(label_color)
        label_x = 62
        label_width = self.fontMetrics().horizontalAdvance(self.text())
        painter.drawText(QRectF(label_x, 0, label_width + 2, self.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text())
        status_font = painter.font()
        status_font.setBold(True)
        painter.setFont(status_font)
        status_color = QColor(theme_color('#66ddda' if self.isChecked() else '#91aabd'))
        if not self.isEnabled():
            status_color.setAlpha(120)
        painter.setPen(status_color)
        painter.drawText(QRectF(label_x + label_width + 18, 0,
                                max(0, self.width() - label_x - label_width - 18), self.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         self.status_text())


class ThemeHeader(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("TopBar")
        self.banner = None
        self.banner_path = None
        self.animation = None
        self.animation_path = None

    def set_animation(self, path):
        if path == self.animation_path:
            return
        self.animation_path = path
        if self.animation is not None:
            self.animation.stop()
            self.animation.deleteLater()
            self.animation = None
        if path is not None:
            movie = QMovie(str(path), parent=self)
            if movie.isValid():
                self.animation = movie
                movie.frameChanged.connect(self._update_animation)
                if self.isVisible():
                    movie.start()
            else:
                movie.deleteLater()
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if self.animation is not None:
            if self.animation.state() == QMovie.MovieState.Paused:
                self.animation.setPaused(False)
            else:
                self.animation.start()

    def hideEvent(self, event):
        if self.animation is not None and self.animation.state() == QMovie.MovieState.Running:
            self.animation.setPaused(True)
        super().hideEvent(event)

    def _animation_rect(self):
        # Leave the title row above and the lamp illustration to the right.
        return QRectF(12, 40, max(0, self.width() * .75 - 24), max(0, self.height() - 45))

    def _update_animation(self, _frame_number):
        self.update(self._animation_rect().toAlignedRect())

    def paintEvent(self, event):
        super().paintEvent(event)
        pack = get_theme(current_theme())
        if pack.banner is None and self.animation is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._paint_banner(painter, pack)
        if self.animation is not None:
            frame = self.animation.currentPixmap()
            bounds = self._animation_rect()
            if not frame.isNull() and not bounds.isEmpty():
                scale = min(bounds.width() / frame.width(), bounds.height() / frame.height())
                width, height = frame.width() * scale, frame.height() * scale
                target = QRectF(bounds.left(), bounds.bottom() - height, width, height)
                painter.drawPixmap(target, frame, QRectF(frame.rect()))

    def _paint_banner(self, painter, pack):
        if pack.banner is None:
            return
        if self.banner_path != pack.banner:
            self.banner_path = pack.banner
            self.banner = QPixmap(str(pack.banner))
        if self.banner.isNull():
            return
        width, height = self.banner.width(), self.banner.height()
        crop_top, crop_bottom = pack.banner_crop
        source = QRectF(0, height * crop_top, width, height * (crop_bottom - crop_top))
        target_width = min(self.width(), round(self.height() * source.width() / source.height()))
        target = QRectF(self.width() - target_width, 0, target_width, self.height())
        base = QColor(pack.banner_background)
        painter.fillRect(self.rect(), base)
        painter.drawPixmap(target, self.banner, source)
        fade_width = target.width() * .28
        fade = QLinearGradient(target.left(), 0, target.left() + fade_width, 0)
        fade.setColorAt(0, base)
        transparent = QColor(base)
        transparent.setAlpha(0)
        fade.setColorAt(1, transparent)
        painter.fillRect(QRectF(target.left(), 0, fade_width, target.height()), fade)

DOCUMENT_CSS = '''
body { color: #d0dbea; font-size: 14px; }
h1 { color: #eef5ff; font-size: 24px; margin-bottom: 16px; }
h2 { color: #e4ebf5; font-size: 20px; margin-top: 22px; }
h3 { color: #66ddda; font-size: 16px; margin-top: 18px; }
p, li { line-height: 155%; }
blockquote { background-color: #142630; color: #afc8d7; margin-left: 0; padding: 12px; }
pre { background-color: #0b121d; color: #c1e5e4; padding: 12px; white-space: pre-wrap; }
code { color: #8ee4df; background-color: #182735; }
a { color: #66ddda; }
.chat-speaker { color: #66ddda; }
a.chat-note-action { color: #66ddda; background-color: #294251; text-decoration: none; }
th { background-color: #213243; }
td, th { padding: 7px; border: 1px solid #34465a; }
hr { color: #29394c; }
'''


def document_stylesheet():
    return theme_css(DOCUMENT_CSS) + '\n' + get_theme(current_theme()).document_css


STYLESHEET = '''
QWidget { color: #e4ebf5; font-size: 13px; }
QMainWindow, QDialog, QMessageBox { background: #0b1019; }
QWidget#AppRoot, QWidget#ReaderPanel { background: #0b1019; }
QWidget#TopBar { background: #111a28; border-bottom: 1px solid #263345; }
QPushButton#Brand { background: transparent; border: 1px solid transparent; color: #eaf4ff; padding: 0 3px; font-size: 18px; font-weight: 600; }
QPushButton#Brand:hover { color: #66ddda; }
QPushButton#Brand:focus { border-color: #66ddda; }
QLabel#CurrentPaper, QLabel#Muted { color: #93a4ba; }
QLabel#SectionLabel { color: #8298b2; font-size: 11px; letter-spacing: 1px; }
QWidget#LibraryPanel { background: #0e1520; }
QWidget#PanelHeader { background: #101824; border-bottom: 1px solid #263345; }
QLabel#PanelTitle { color: #e0eaf6; font-weight: 600; }
QLabel#AccentLabel { color: #66ddda; font-size: 11px; }
QLabel#LocalBadge { background: #142b2d; color: #9ed6c7; padding: 5px 9px; border-radius: 5px; font-size: 11px; }
QPushButton { background: #162130; border: 1px solid #2c3d50; border-radius: 6px; padding: 7px 12px; min-height: 19px; }
QPushButton:hover { background: #223146; border-color: #456079; }
QPushButton:pressed { background: #294154; }
QPushButton:disabled { color: #64768d; background: #121c29; border-color: #223042; }
QPushButton#Primary { background: #66ddda; color: #092426; border-color: #66ddda; font-weight: 600; }
QPushButton#Primary:hover { background: #8ce9e6; }
QPushButton#Primary:disabled { background: #294d53; color: #7ea6ac; border-color: #294d53; }
QPushButton#Quiet { background: transparent; border-color: transparent; color: #a6b8ce; }
QPushButton#Quiet:hover { background: #1c2c3d; color: #e4ebf5; }
QPushButton#QuestionMarker { background: transparent; color: #66ddda; border: none; padding: 0; min-height: 0; font-size: 18px; }
QPushButton#QuestionMarker:hover { background: #294251; }
QPushButton#NavButton { padding: 3px 8px; min-height: 18px; }
QPushButton#Danger { color: #efb0b3; }
QPushButton:focus, QLineEdit:focus, QTextEdit:focus { border-color: #66ddda; }
QListWidget { background: transparent; border: none; outline: none; padding: 4px; }
QListWidget::item { padding: 12px 9px; margin: 3px 0; border-radius: 6px; border: 1px solid transparent; }
QListWidget::item:hover { background: #142130; }
QListWidget::item:selected { background: #172c38; color: #e0f4f2; border-color: #355665; }
QListWidget#PaperList::item { min-height: 26px; padding: 7px 9px; }
QToolButton#PaperFavoriteButton { background: transparent; border: 1px solid transparent; border-radius: 5px; padding: 0; }
QToolButton#PaperFavoriteButton:hover { background: #294251; }
QToolButton#PaperFavoriteButton:focus { border-color: #66ddda; }
QTabWidget::pane { border: none; background: #101824; }
QTabBar { background: #101824; }
QTabBar::tab { background: transparent; color: #93a4ba; padding: 11px 12px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #66ddda; border-bottom-color: #66ddda; }
QTabBar::tab:hover { background: #172536; }
QTextBrowser { background: #101824; border: none; padding: 12px; selection-background-color: #305663; selection-color: #ffffff; }
QTextEdit { background: #111c2a; border: 1px solid #2e4056; border-radius: 6px; padding: 10px; selection-background-color: #305663; }
QWidget#ComposerFooter { background: #111c2a; }
QComboBox { background: #172736; color: #c5d9e2; border: 1px solid #344b60; border-radius: 5px; padding: 6px 36px 6px 10px; min-height: 20px; }
QComboBox:hover { border-color: #66ddda; background: #1d3342; }
QComboBox::drop-down { subcontrol-origin: border; subcontrol-position: top right; border-left: 1px solid #3d596c; border-top-right-radius: 5px; border-bottom-right-radius: 5px; background: #244151; width: 30px; }
QComboBox::drop-down:hover { background: #305465; }
QComboBox::down-arrow { image: url("__DROPDOWN_ARROW__"); width: 14px; height: 14px; }
QComboBox:disabled { color: #7b8d9d; border-color: #2a3949; }
QComboBox QAbstractItemView { background: #162231; color: #e4ebf5; selection-background-color: #294251; }
QComboBox#AnalysisMode { combobox-popup: 0; background: #121d2a; color: #a3bacd; border-color: #2b4053; padding: 4px 24px 4px 8px; min-height: 18px; }
QComboBox#AnalysisMode:hover, QComboBox#AnalysisMode:focus { background: #172433; border-color: #4a6379; }
QComboBox#AnalysisMode::drop-down { background: transparent; border: none; width: 23px; }
QComboBox#AnalysisMode::down-arrow { image: url("__ANALYSIS_ARROW__"); width: 12px; height: 12px; }
QComboBox#AnalysisMode QAbstractItemView { border: 1px solid #2b4053; }
QComboBox#AnalysisMode QAbstractItemView::item { padding: 4px 8px 4px 5px; }
QComboBox#ThemePicker { combobox-popup: 0; background: #121d2a; border-color: #2b4053; min-height: 24px; }
QComboBox#ThemePicker:hover, QComboBox#ThemePicker:focus { border-color: #4a6379; }
QComboBox#ThemePicker::drop-down { background: transparent; border: none; }
QComboBox#ThemePicker QAbstractItemView { border: 1px solid #344b62; outline: none; }
QComboBox#ThemePicker QAbstractItemView::item { padding: 7px 10px; min-height: 19px; }
QComboBox#ThemePicker QAbstractItemView::item:selected { color: #8ce9e6; }
QLineEdit, QSpinBox { background: #0c1521; border: 1px solid #34475b; border-radius: 6px; padding: 9px 11px; min-height: 22px; selection-background-color: #305663; }
QWidget#QuoteCard { background: #142530; border: 1px solid #35515c; border-radius: 7px; }
QSpinBox QLineEdit { background: transparent; border: none; padding: 0; min-height: 0; }
QSpinBox { padding-right: 28px; min-height: 22px; max-height: 22px; }
QSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 24px; border-left: 1px solid #34475b; }
QSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 24px; border-left: 1px solid #34475b; }
QTextBrowser#Quote { background: transparent; border: none; color: #afc4d5; padding: 0; }
QPushButton#QuoteClose { background: #203b48; color: #b9d8dd; border: 1px solid #3d5e6a; border-radius: 12px; padding: 0; min-height: 0; font-size: 17px; }
QPushButton#QuoteClose:hover { background: #365866; color: #ffffff; border-color: #66ddda; }
QScrollArea { border: none; background: #0a111b; }
QScrollArea > QWidget > QWidget { background: #0a111b; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 0; }
QScrollBar::handle:vertical { background: #35495e; border-radius: 4px; min-height: 32px; }
QScrollBar:horizontal { background: transparent; height: 9px; margin: 0; }
QScrollBar::handle:horizontal { background: #35495e; border-radius: 4px; min-width: 32px; }
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: #54748d; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QStatusBar { background: #101824; color: #93a4ba; border-top: 1px solid #263345; font-size: 11px; }
QStatusBar::item { border: none; }
QMenu { background: #162231; border: 1px solid #344b62; padding: 5px; }
QMenu::item { padding: 8px 20px; border-radius: 4px; }
QMenu::item:selected { background: #294251; color: #8ce9e6; }
QMenu::item:disabled { color: #79899b; }
QMenu#PdfSelectionMenu { border-radius: 8px; }
QMenu#PdfSelectionMenu::item { padding: 8px 24px 8px 14px; }
QMenu#PdfSelectionMenu::separator { height: 1px; background: #344b62; margin: 4px 8px; }
QToolTip { background: #1b2d3d; color: #e4ebf5; border: 1px solid #405b70; padding: 7px; }
QListWidget#SettingsNavigation { background: #101824; border-right: 1px solid #263345; }
QListWidget#SettingsNavigation::item { padding: 9px 12px; }
QLabel#SettingsHeading { color: #eaf4ff; font-size: 18px; font-weight: 600; padding: 5px 0 10px; }
'''


def apply_theme(theme=DEFAULT_THEME_ID):
    app = QApplication.instance()
    if app is None: return
    pack = get_theme(theme)
    theme = pack.identifier
    app.setProperty('paperreaderTheme', theme)
    # The native macOS title bar follows the application appearance, not QSS.
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    app.setStyle('Fusion')
    palette = QPalette()
    for role, value in {
        QPalette.ColorRole.Window: BACKGROUND,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: PANEL,
        QPalette.ColorRole.AlternateBase: '#162130',
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: '#162130',
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.Highlight: '#305663',
        QPalette.ColorRole.HighlightedText: '#ffffff',
        QPalette.ColorRole.PlaceholderText: '#8294ab',
        QPalette.ColorRole.ToolTipBase: '#1b2d3d',
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.Link: ACCENT,
    }.items(): palette.setColor(role, QColor(theme_color(value, theme)))
    app.setPalette(palette)
    font = QFont(app.font()); font.setPointSize(11); app.setFont(font)
    arrow = (Path(__file__).resolve().parent.parent / "assets" / "dropdown-arrow.svg").as_posix()
    analysis_arrow = Path(arrow).with_name("analysis-arrow.svg").as_posix()
    if pack.arrow:
        arrow = analysis_arrow = pack.arrow.as_posix()
    stylesheet = theme_css(STYLESHEET, theme) + '\n' + pack.stylesheet
    app.setStyleSheet(stylesheet.replace("__DROPDOWN_ARROW__", arrow).replace("__ANALYSIS_ARROW__", analysis_arrow))
    from paperreader.ui.scrollbars import install_hover_scrollbars
    install_hover_scrollbars(app)
