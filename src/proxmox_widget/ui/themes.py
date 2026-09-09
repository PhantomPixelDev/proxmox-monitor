from __future__ import annotations

DARK_QSS = """
QWidget { background: #1e1e2e; color: #cdd6f4; font-family: "Segoe UI", sans-serif; font-size: 13px; }
QFrame#card { background: #313244; border-radius: 10px; }
QLabel#title { font-size: 15px; font-weight: 700; }
QLabel#muted { color: #a6adc8; }
QPushButton { background: #45475a; border: none; border-radius: 6px; padding: 6px 12px; }
QPushButton:hover { background: #585b70; }
QPushButton#primary { background: #89b4fa; color: #1e1e2e; font-weight: 600; }
QProgressBar { border: none; background: #45475a; border-radius: 4px; text-align: center; }
QProgressBar::chunk { background: #89b4fa; border-radius: 4px; }
QTabWidget::pane { border: none; }
QTabBar::tab { padding: 6px 14px; margin-right: 2px; background: #313244; border-radius: 6px; }
QTabBar::tab:selected { background: #45475a; }
"""

LIGHT_QSS = """
QWidget { background: #eff1f5; color: #4c4f69; font-family: "Segoe UI", sans-serif; font-size: 13px; }
QFrame#card { background: #ffffff; border-radius: 10px; border: 1px solid #ccd0da; }
QLabel#title { font-size: 15px; font-weight: 700; }
QLabel#muted { color: #8c8fa1; }
QPushButton { background: #ccd0da; border: none; border-radius: 6px; padding: 6px 12px; }
QPushButton:hover { background: #bcc0cc; }
QPushButton#primary { background: #1e66f5; color: white; font-weight: 600; }
QProgressBar { border: none; background: #ccd0da; border-radius: 4px; text-align: center; }
QProgressBar::chunk { background: #1e66f5; border-radius: 4px; }
QTabWidget::pane { border: none; }
QTabBar::tab { padding: 6px 14px; margin-right: 2px; background: #e6e9ef; border-radius: 6px; }
QTabBar::tab:selected { background: #ccd0da; }
"""


def qss_for(theme: str, system_is_dark: bool = True) -> str:
    if theme == "dark":
        return DARK_QSS
    if theme == "light":
        return LIGHT_QSS
    return DARK_QSS if system_is_dark else LIGHT_QSS
