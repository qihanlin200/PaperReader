"""Deep-space desktop theme, shared by the main window and dialogs."""
from pathlib import Path
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

BACKGROUND = '#0b1019'
PANEL = '#101824'
TEXT = '#e4ebf5'
ACCENT = '#66ddda'

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
th { background-color: #213243; }
td, th { padding: 7px; border: 1px solid #34465a; }
hr { color: #29394c; }
'''

STYLESHEET = '''
QWidget { color: #e4ebf5; font-size: 13px; }
QMainWindow, QDialog, QMessageBox { background: #0b1019; }
QWidget#AppRoot, QWidget#ReaderPanel { background: #0b1019; }
QWidget#TopBar { background: #111a28; border-bottom: 1px solid #263345; }
QLabel#Brand { color: #eaf4ff; font-size: 18px; font-weight: 600; }
QLabel#BrandMark { color: #66ddda; font-size: 23px; }
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
QListWidget#PaperList::item { min-height: 20px; padding: 7px 9px; }
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
QLineEdit { background: #0c1521; border: 1px solid #34475b; border-radius: 6px; padding: 9px 11px; min-height: 22px; selection-background-color: #305663; }
QWidget#QuoteCard { background: #142530; border: 1px solid #35515c; border-radius: 7px; }
QTextBrowser#Quote { background: transparent; border: none; color: #afc4d5; padding: 0; }
QPushButton#QuoteClose { background: #203b48; color: #b9d8dd; border: 1px solid #3d5e6a; border-radius: 12px; padding: 0; min-height: 0; font-size: 17px; }
QPushButton#QuoteClose:hover { background: #365866; color: #ffffff; border-color: #66ddda; }
QScrollArea { border: none; background: #0a111b; }
QScrollArea > QWidget > QWidget { background: #0a111b; }
QScrollBar:vertical { background: #101824; width: 9px; margin: 0; }
QScrollBar::handle:vertical { background: #35495e; border-radius: 4px; min-height: 32px; }
QScrollBar:horizontal { background: #101824; height: 9px; margin: 0; }
QScrollBar::handle:horizontal { background: #35495e; border-radius: 4px; min-width: 32px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QStatusBar { background: #101824; color: #93a4ba; border-top: 1px solid #263345; font-size: 11px; }
QStatusBar::item { border: none; }
QMenu { background: #162231; border: 1px solid #344b62; padding: 5px; }
QMenu::item { padding: 8px 20px; border-radius: 4px; }
QMenu::item:selected { background: #294251; color: #8ce9e6; }
QMenu::item:disabled { color: #79899b; }
QToolTip { background: #1b2d3d; color: #e4ebf5; border: 1px solid #405b70; padding: 7px; }
'''


def apply_theme():
    app = QApplication.instance()
    if app is None: return
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
    }.items(): palette.setColor(role, QColor(value))
    app.setPalette(palette)
    font = QFont(app.font()); font.setPointSize(11); app.setFont(font)
    arrow = (Path(__file__).resolve().parent.parent / "assets" / "dropdown-arrow.svg").as_posix()
    app.setStyleSheet(STYLESHEET.replace("__DROPDOWN_ARROW__", arrow))
