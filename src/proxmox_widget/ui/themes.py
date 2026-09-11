from __future__ import annotations

import pathlib

try:
    import proxmox_widget.ui.font_fix  # noqa: F401  # clamp QFont.setPointSize
except Exception:
    pass

# --- palettes -----------------------------------------------------------------
# Kept as dicts so widgets can pull the same colours the stylesheet uses
# (status accents, chart bars) instead of hardcoding hex twice.

DARK = {
    "bg": "#151623",
    "surface": "#1e2032",
    "surface_hi": "#272a40",
    "header": "#242739",
    "border": "#343850",
    "border_hi": "#454a6b",
    "text": "#e7eaf6",
    "text_dim": "#a5abc9",
    "text_faint": "#7f86a8",
    "accent": "#7aa2f7",
    "accent_ink": "#10121c",
    "ok": "#4ade80",
    "warn": "#fbbf24",
    "err": "#f87171",
    "info": "#7aa2f7",
    "bar_track": "#2c2f45",
}

LIGHT = {
    "bg": "#f3f4f9",
    "surface": "#ffffff",
    "surface_hi": "#f7f8fc",
    "header": "#f6f7fc",
    "border": "#d9dded",
    "border_hi": "#b9c0da",
    "text": "#171a2b",
    "text_dim": "#5b6180",
    "text_faint": "#7d83a0",
    "accent": "#2f6bed",
    "accent_ink": "#ffffff",
    "ok": "#16a34a",
    "warn": "#c2820a",
    "err": "#dc2626",
    "info": "#2f6bed",
    "bar_track": "#e6e9f2",
}

_QSS_TEMPLATE = """
/* --- ProxmoxWidget ------------------------------------------------------- */
QWidget {{
    background: {bg};
    color: {text};
    font-family: "Segoe UI", "Inter", "Noto Sans", sans-serif;
    font-size: 13px;
}}
QWidget#root {{ background: {bg}; }}
QToolTip {{
    background: {surface_hi};
    color: {text};
    border: 1px solid {border_hi};
    border-radius: 6px;
    padding: 5px 8px;
}}

/* --- cards: every row is its own solid block with a visible edge ---------- */
QFrame#card {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 10px;
}}
QFrame#card:hover {{ border-color: {border_hi}; }}
QFrame#cardHead {{
    background: {header};
    border: none;
    border-bottom: 1px solid {border};
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
}}
QFrame#cardBody {{ background: transparent; border: none; }}
QWidget#metricRow {{ background: transparent; }}
QFrame#tile QLabel {{ background: transparent; border: none; }}
QFrame#accent {{ border: none; border-top-left-radius: 9px; border-bottom-left-radius: 9px; }}

/* --- typography ----------------------------------------------------------- */
QLabel#title {{ font-size: 15px; font-weight: 700; color: {text}; }}
QLabel#subtitle {{ font-size: 11.5px; color: {text_faint}; }}
QLabel#cardTitle {{ font-size: 13.5px; font-weight: 650; color: {text}; }}
QLabel#muted {{ color: {text_dim}; font-size: 12px; }}
QLabel#meta {{ color: {text_faint}; font-size: 11px; }}
QLabel#value {{ color: {text_dim}; font-size: 11px; font-weight: 600; }}
QLabel#empty {{ color: {text_faint}; font-size: 12.5px; padding: 22px 8px; }}
QLabel#badge {{
    background: {surface_hi};
    color: {text_dim};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 2px 7px;
    font-size: 11px;
    font-weight: 700;
}}
QLabel {{ background: transparent; }}

/* --- buttons -------------------------------------------------------------- */
QPushButton {{
    background: {surface_hi};
    color: {text};
    border: 1px solid {border};
    border-radius: 7px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton:hover {{ background: {header}; border-color: {border_hi}; }}
QPushButton:pressed {{ background: {surface}; }}
QPushButton:disabled {{ color: {text_faint}; border-color: {border}; background: {surface}; }}
QPushButton#primary {{
    background: {accent};
    color: {accent_ink};
    border: 1px solid {accent};
    font-weight: 700;
    padding: 8px 14px;
}}
QPushButton#primary:hover {{ background: {accent}; border-color: {text_dim}; }}
QPushButton#ghost {{ background: transparent; border: 1px solid {border}; color: {text_dim}; }}
QPushButton#ghost:hover {{ background: {surface_hi}; color: {text}; }}
QPushButton#chip {{
    background: transparent;
    border: 1px solid {border};
    color: {text_dim};
    border-radius: 6px;
    padding: 4px 9px;
    font-size: 11.5px;
    font-weight: 600;
}}
QPushButton#chip:hover {{ background: {surface_hi}; color: {text}; }}
QPushButton#chip:checked {{ background: {accent}; color: {accent_ink}; border-color: {accent}; }}
QPushButton#menuBtn {{ text-align: left; padding-right: 8px; }}
QPushButton#menuBtn::menu-indicator {{
    image: url({asset_chevron});
    width: 11px;
    height: 11px;
    subcontrol-position: right center;
    right: 4px;
}}

/* --- search --------------------------------------------------------------- */
QLineEdit {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 12.5px;
    color: {text};
    selection-background-color: {accent};
    selection-color: {accent_ink};
}}
QLineEdit:focus {{ border-color: {accent}; }}
QLineEdit::placeholder {{ color: {text_faint}; }}
QFrame#searchBar {{ background: transparent; border: none; }}

/* --- progress ------------------------------------------------------------- */
QProgressBar {{
    background: {bar_track};
    border: none;
    border-radius: 5px;
    text-align: center;
    font-size: 10px;
    font-weight: 700;
    color: {text_dim};
    min-height: 10px;
    max-height: 10px;
}}
QProgressBar::chunk {{ background: {accent}; border-radius: 5px; }}
QProgressBar#ram::chunk {{ background: {ok}; }}
QProgressBar#disk::chunk {{ background: {warn}; }}
QProgressBar#hot::chunk {{ background: {err}; }}
QProgressBar#busy {{ min-height: 4px; max-height: 4px; border-radius: 2px; }}

/* --- tabs ----------------------------------------------------------------- */
QTabWidget::pane {{ border: none; background: transparent; margin-top: 6px; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{
    background: transparent;
    color: {text_faint};
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 6px 11px;
    margin-right: 4px;
    font-size: 12px;
    font-weight: 600;
}}
QTabBar::tab:selected {{ background: {surface_hi}; color: {text}; border-color: {border_hi}; }}
QTabBar::tab:hover:!selected {{ color: {text_dim}; background: {surface}; }}

/* --- scroll --------------------------------------------------------------- */
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px 0px 2px 0px; }}
QScrollBar::handle:vertical {{ background: {border_hi}; border-radius: 4px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {text_faint}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

/* --- settings dialog ------------------------------------------------------ */
QDialog {{ background: {bg}; }}
QGroupBox {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 10px;
    margin-top: 14px;
    padding: 12px 12px 10px 12px;
    font-size: 12px;
    font-weight: 700;
    color: {text_dim};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0px 6px;
    color: {text_dim};
}}
QListWidget {{
    background: {surface_hi};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 4px;
    font-size: 12.5px;
}}
QListWidget::item {{ padding: 6px 8px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {accent}; color: {accent_ink}; }}
QComboBox, QSpinBox {{
    background: {surface_hi};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 12.5px;
    color: {text};
    min-height: 20px;
}}
QComboBox:focus, QSpinBox:focus {{ border-color: {accent}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url({asset_chevron}); width: 11px; height: 11px; }}
QSpinBox::up-button, QSpinBox::down-button {{
    background: transparent;
    border: none;
    width: 18px;
}}
QSpinBox::up-arrow {{ image: url({asset_chevron_up}); width: 10px; height: 10px; }}
QSpinBox::down-arrow {{ image: url({asset_chevron}); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 8px;
    selection-background-color: {accent};
    selection-color: {accent_ink};
    padding: 4px;
}}
QCheckBox {{ background: transparent; font-size: 12.5px; color: {text_dim}; spacing: 8px; }}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {border_hi};
    border-radius: 4px;
    background: {surface_hi};
}}
QCheckBox::indicator:checked {{
    background: {accent};
    border-color: {accent};
    image: url({asset_check});
}}
QFormLayout QLabel {{ color: {text_dim}; }}

/* --- misc ----------------------------------------------------------------- */
QFrame#lineSep {{ background: {border}; max-height: 1px; border: none; }}
QMenu {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 5px;
}}
QMenu::item {{ padding: 6px 16px 6px 12px; border-radius: 5px; color: {text}; }}
QMenu::item:selected {{ background: {surface_hi}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 6px; }}
"""

_QSS_CACHE: dict[str, str] = {}


def _asset(name: str, color: str, size: int = 12) -> str:
    """Render one icon to a PNG on disk — Qt stylesheets can only load glyphs by path."""
    import tempfile

    from proxmox_widget.ui import icons

    size = max(1, int(size))
    slug = f"pw-{name}-{color.lstrip('#')}-{size}.png"
    path = pathlib.Path(tempfile.gettempdir()) / slug
    if not path.exists():
        try:
            icons.pixmap(name, size, color, stroke=2.6, dpr=2.0).save(str(path), "PNG")
        except Exception:
            return ""
    return path.as_posix()


def _build(pal: dict[str, str]) -> str:
    try:
        assets = {
            "asset_check": _asset("check", pal["accent_ink"], 12),
            "asset_chevron": _asset("chevron_down", pal["text_dim"], 12),
            "asset_chevron_up": _asset("chevron_up", pal["text_dim"], 12),
        }
    except Exception:  # no QGuiApplication yet — fall back to bare indicators
        assets = {"asset_check": "", "asset_chevron": "", "asset_chevron_up": ""}
    return _QSS_TEMPLATE.format(**pal, **assets)


def palette_for(theme: str, system_is_dark: bool = True) -> dict[str, str]:
    if theme == "dark":
        return DARK
    if theme == "light":
        return LIGHT
    return DARK if system_is_dark else LIGHT


def qss_for(theme: str, system_is_dark: bool = True) -> str:
    try:
        from proxmox_widget.ui.font_fix import ensure_valid_app_font, install_qfont_suppress_filter

        install_qfont_suppress_filter()
        ensure_valid_app_font()
    except Exception:
        pass
    key = theme if theme in ("dark", "light") else ("dark" if system_is_dark else "light")
    cached = _QSS_CACHE.get(key)
    if cached is None:
        cached = _build(DARK if key == "dark" else LIGHT)
        for token in ("font-size: -", "font: -", "font-size: 0px", "font-size: -1"):
            if token in cached:
                cached = cached.replace(token, "font-size: 1px")
        _QSS_CACHE[key] = cached
    return cached
