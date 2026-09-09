from __future__ import annotations

DARK_QSS = """
/* --- ProxmoxWidget Dark | Catppuccin Mocha + refined spacing --- */
QWidget {
    background: #1e1e2e;
    color: #cdd6f4;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 14px;
}
QWidget#root { background: #1e1e2e; }

/* cards — high-contrast, clearly separated */
QFrame#card {
    background: #2b2e4a;
    border: 2px solid #6d72a3;
    border-radius: 12px;
}
QFrame#card:hover { border-color: #6d72a3; }
QFrame#cardHeader {
    background: #32365a;
    border-bottom: 1.5px solid #4a4e7a;
    border-top-left-radius: 11px;
    border-top-right-radius: 11px;
}

/* typography */
QLabel#title {
    font-size: 16px;
    font-weight: 700;
    color: #cdd6f4;
    letter-spacing: 0.2px;
}
QLabel#subtitle { font-size: 12px; color: #a6adc8; }
QLabel#muted { color: #8d91b0; font-size: 12px; }
QLabel#badge {
    background: #3a3d53;
    color: #bac2de;
    border-radius: 8px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}
QLabel#cardTitle { font-size: 14.5px; font-weight: 600; color: #cdd6f4; }
QLabel { padding: 1px 0px; }

/* buttons */
QPushButton {
    background: #34374e;
    color: #cdd6f4;
    border: 1px solid #3f425c;
    border-radius: 8px;
    padding: 7px 14px;
    font-size: 12.5px;
    font-weight: 500;
}
QPushButton:hover { background: #3e415e; border-color: #4c4f6e; }
QPushButton:pressed { background: #2e3148; }
QPushButton:disabled { background: #2a2d42; color: #6c7086; border-color: #31344a; }
QPushButton#primary {
    background: #89b4fa;
    color: #1e1e2e;
    border: none;
    font-weight: 700;
    padding: 8px 16px;
}
QPushButton#primary:hover { background: #a6ccff; }
QPushButton#primary:pressed { background: #74a6f0; }
QPushButton#ghost {
    background: transparent;
    border: 1px solid #3a3d53;
    color: #a6adc8;
}
QPushButton#ghost:hover { background: #25273d; color: #cdd6f4; }

/* progress */
QProgressBar {
    background: #34374e;
    border: 1px solid #3a3d53;
    border-radius: 7px;
    text-align: center;
    font-size: 10.5px;
    font-weight: 600;
    color: #cdd6f4;
    min-height: 14px;
    max-height: 14px;
}
QProgressBar::chunk {
    background: #89b4fa;
    border-radius: 6px;
    margin: 1px;
}
QProgressBar#ram::chunk { background: #a6e3a1; }
QProgressBar#disk::chunk { background: #f9e2af; }

/* tabs */
QTabWidget::pane {
    border: none;
    background: transparent;
    margin-top: 8px;
}
QTabBar::tab {
    background: #25273d;
    color: #8d91b0;
    border: 1px solid #3a3d53;
    border-radius: 8px;
    padding: 7px 14px;
    margin-right: 6px;
    font-size: 12.5px;
    font-weight: 500;
    min-width: 48px;
}
QTabBar::tab:selected {
    background: #34374e;
    color: #cdd6f4;
    border-color: #4c4f6e;
}
QTabBar::tab:hover { background: #2e3148; color: #bac2de; }

/* scrollbars */
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 4px 2px 4px 0px;
}
QScrollBar::handle:vertical {
    background: #3a3d53;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #4c4f6e; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

/* separators */
QFrame#lineSep { background: #31344a; max-height: 1px; border: none; }
"""

LIGHT_QSS = """
QWidget {
    background: #eff1f5;
    color: #4c4f69;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 14px;
}
QWidget#root { background: #eff1f5; }

QFrame#card {
    background: #ffffff;
    border: 2px solid #c8cde0;
    border-radius: 12px;
}
QFrame#cardHeader {
    background: #f2f4f9;
    border-bottom: 1.5px solid #d8dce9;
    border-top-left-radius: 11px;
    border-top-right-radius: 11px;
}

QLabel#title { font-size: 16px; font-weight: 700; color: #4c4f69; }
QLabel#subtitle { font-size: 12px; color: #7c7f93; }
QLabel#muted { color: #8c8fa1; font-size: 12px; }
QLabel#badge {
    background: #e6e9ef;
    color: #5c5f77;
    border-radius: 8px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}
QLabel#cardTitle { font-size: 14.5px; font-weight: 600; color: #4c4f69; }
QLabel { padding: 1px 0px; }

QPushButton {
    background: #ffffff;
    color: #4c4f69;
    border: 1px solid #ccd0da;
    border-radius: 8px;
    padding: 7px 14px;
    font-size: 12.5px;
    font-weight: 500;
}
QPushButton:hover { background: #e6e9ef; border-color: #bcc0cc; }
QPushButton:pressed { background: #dce0ec; }
QPushButton:disabled { background: #e6e9ef; color: #9ca0b0; }
QPushButton#primary {
    background: #1e66f5;
    color: white;
    border: none;
    font-weight: 700;
    padding: 8px 16px;
}
QPushButton#primary:hover { background: #3369ff; }
QPushButton#ghost { background: transparent; border: 1px solid #dce0ec; color: #7c7f93; }
QPushButton#ghost:hover { background: #ffffff; }

QProgressBar {
    background: #e6e9ef;
    border: 1px solid #dce0ec;
    border-radius: 7px;
    text-align: center;
    font-size: 10.5px;
    font-weight: 600;
    color: #4c4f69;
    min-height: 14px;
    max-height: 14px;
}
QProgressBar::chunk { background: #1e66f5; border-radius: 6px; margin: 1px; }
QProgressBar#ram::chunk { background: #40a02b; }
QProgressBar#disk::chunk { background: #df8e1d; }

QTabWidget::pane { border: none; background: transparent; margin-top: 8px; }
QTabBar::tab {
    background: #ffffff;
    color: #8c8fa1;
    border: 1px solid #dce0ec;
    border-radius: 8px;
    padding: 7px 14px;
    margin-right: 6px;
    font-size: 12.5px;
    font-weight: 500;
}
QTabBar::tab:selected { background: #1e66f5; color: white; border-color: #1e66f5; }
QTabBar::tab:hover { background: #e6e9ef; }

QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 4px 2px 4px 0px; }
QScrollBar::handle:vertical { background: #ccd0da; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #bcc0cc; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QFrame#lineSep { background: #dce0ec; max-height: 1px; border: none; }
"""


def qss_for(theme: str, system_is_dark: bool = True) -> str:
    if theme == "dark":
        return DARK_QSS
    if theme == "light":
        return LIGHT_QSS
    return DARK_QSS if system_is_dark else LIGHT_QSS
