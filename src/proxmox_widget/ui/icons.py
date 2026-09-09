"""Inline SVG icon set for the dashboard.

Line icons, 24x24 grid, 2px stroke, currentColor — rendered to pixmaps at the
widget's device pixel ratio so they stay crisp on HiDPI. Emoji were replaced by
these because emoji render inconsistently across Windows/Linux fonts.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QLabel

try:
    from PySide6.QtSvg import QSvgRenderer
except ImportError:  # pragma: no cover - Qt build without SVG
    QSvgRenderer = None  # type: ignore[assignment]

_P = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round">'
)

PATHS: dict[str, str] = {
    # infrastructure
    "cluster": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "node": '<rect x="2.5" y="4" width="19" height="7" rx="2"/><rect x="2.5" y="13" width="19" height="7" rx="2"/><path d="M6.5 7.5h.01M6.5 16.5h.01"/><path d="M10 7.5h5M10 16.5h5"/>',
    "vm": '<rect x="2.5" y="4" width="19" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    "ct": '<path d="M12 2.8 20.5 7v10L12 21.2 3.5 17V7Z"/><path d="M3.5 7 12 11.4 20.5 7"/><path d="M12 11.4V21.2"/>',
    "storage": '<ellipse cx="12" cy="5.5" rx="8" ry="3"/><path d="M4 5.5v13c0 1.66 3.58 3 8 3s8-1.34 8-3v-13"/><path d="M4 12c0 1.66 3.58 3 8 3s8-1.34 8-3"/>',
    "network": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18Z"/>',
    # metrics
    "cpu": '<rect x="7" y="7" width="10" height="10" rx="1.5"/><path d="M9.5 2.5v3M14.5 2.5v3M9.5 18.5v3M14.5 18.5v3M2.5 9.5h3M2.5 14.5h3M18.5 9.5h3M18.5 14.5h3"/>',
    "ram": '<rect x="2.5" y="6" width="19" height="11" rx="2"/><path d="M7 10v4M12 10v4M17 10v4"/>',
    "disk": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.5"/><path d="M17.5 17.5 13.8 13.8"/>',
    "uptime": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5.2l3.4 2"/>',
    "status": '<circle cx="12" cy="12" r="4" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="8"/>',
    "gauge": '<path d="M4 18a9 9 0 1 1 16 0"/><path d="m12 14 4-4"/>',
    # actions
    "play": '<path d="M8 5.5v13l11-6.5Z"/>',
    "stop": '<rect x="6.5" y="6.5" width="11" height="11" rx="1.5"/>',
    "restart": '<path d="M20 12a8 8 0 1 1-2.6-5.9"/><path d="M20 3.5V9h-5.5"/>',
    "power": '<path d="M12 3.5v8"/><path d="M6.9 7A8 8 0 1 0 17.1 7"/>',
    "console": '<rect x="2.5" y="4" width="19" height="16" rx="2"/><path d="m7 9.5 3 2.5-3 2.5"/><path d="M12.5 15h4.5"/>',
    "monitor": '<rect x="2.5" y="4" width="19" height="12" rx="2"/><path d="M8 20h8M12 16v4"/><path d="M6.5 8h5"/>',
    "remote": '<rect x="2.5" y="4.5" width="19" height="13" rx="2"/><path d="M6.5 21h11"/><path d="M9.5 9.5h5v5h-5z"/>',
    "external": '<path d="M14 4h6v6"/><path d="M20 4 11 13"/><path d="M18 14.5V19a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 19V7.5A1.5 1.5 0 0 1 5 6h4.5"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 14.5a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5v.2a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1h.2a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1Z"/>',
    "refresh": '<path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3.5V9h-5.5"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m20 20-4.7-4.7"/>',
    "close": '<path d="M6 6 18 18M18 6 6 18"/>',
    "check": '<path d="m5 13 4.5 4.5L19 7"/>',
    "warn": '<path d="M10.3 3.9 1.9 18a2 2 0 0 0 1.7 3h16.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    "error": '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/>',
    "shield": '<path d="M12 2.7 20 6v6c0 5-3.4 8.3-8 9.3C7.4 20.3 4 17 4 12V6Z"/><path d="m9 12 2 2 4-4"/>',
    "chevron_down": '<path d="m5 9 7 7 7-7"/>',
    "chevron_up": '<path d="m5 15 7-7 7 7"/>',
    "filter": '<path d="M3 5h18l-7 8v6l-4 2v-8Z"/>',
}

_CACHE: dict[tuple[str, int, str, float, float], QPixmap] = {}


def svg_markup(name: str, color: str = "currentColor", stroke: float = 2.0) -> str:
    body = PATHS.get(name, PATHS["status"])
    svg = _P.format(w=stroke) + body + "</svg>"
    return svg.replace("currentColor", color)


def pixmap(
    name: str, size: int = 16, color: str = "#a5abc9", stroke: float = 2.0, dpr: float = 2.0
) -> QPixmap:
    key = (name, size, color, stroke, dpr)
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    px = max(1, int(size * dpr))
    pm = QPixmap(px, px)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    if QSvgRenderer is not None:
        renderer = QSvgRenderer(QByteArray(svg_markup(name, color, stroke).encode("utf-8")))
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # explicit target rect in logical units: painter.viewport() is in device
        # pixels, so letting QSvgRenderer pick it crops the icon on HiDPI
        renderer.render(painter, QRectF(0.0, 0.0, float(size), float(size)))
        painter.end()
    _CACHE[key] = pm
    return pm


def icon(name: str, size: int = 16, color: str = "#a5abc9", stroke: float = 2.0) -> QIcon:
    return QIcon(pixmap(name, size, color, stroke))


def label(name: str, size: int = 15, color: str = "#a5abc9", stroke: float = 2.0) -> QLabel:
    lbl = QLabel()
    lbl.setFixedSize(size, size)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setStyleSheet("background: transparent; border: none;")
    dpr = lbl.devicePixelRatioF() or 2.0
    lbl.setPixmap(pixmap(name, size, color, stroke, max(2.0, dpr)))
    return lbl
