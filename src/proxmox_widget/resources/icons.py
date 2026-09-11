from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QLinearGradient, QPainter, QPen, QPixmap

try:
    import proxmox_widget.ui.font_fix  # noqa: F401  # clamp QFont.setPointSize
except Exception:
    pass


def make_app_icon(size: int = 256) -> QIcon:
    try:
        from proxmox_widget.ui.font_fix import ensure_valid_app_font

        ensure_valid_app_font()
    except Exception:
        pass
    size = max(1, int(size))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    if not p.isActive():
        p.end()
        return QIcon(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    r = max(1, size // 8)
    bg_rect = pm.rect().adjusted(2, 2, -2, -2)

    grad = QLinearGradient(bg_rect.topLeft(), bg_rect.bottomRight())
    grad.setColorAt(0, QColor("#ff7b00"))
    grad.setColorAt(0.5, QColor("#e85d04"))
    grad.setColorAt(1, QColor("#9d0208"))
    p.setBrush(QBrush(grad))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(bg_rect, r, r)

    # inner highlight
    p.setBrush(QBrush(QColor(255, 255, 255, 18)))
    p.drawRoundedRect(bg_rect.adjusted(1, 1, -1, -size // 2), r, r)
    # server stack icon
    p.setPen(
        QPen(QColor("#ffffff"), max(2, size // 64), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    )
    p.setBrush(Qt.BrushStyle.NoBrush)
    # 3 stacked servers
    cx = size // 2
    w = int(size * 0.52)
    h = int(size * 0.11)
    gap = int(size * 0.04)
    sy = size // 2 - h - gap
    for i in range(3):
        y = sy + i * (h + gap)
        rect = p.pen().widthF()
        # plate
        p.setBrush(QBrush(QColor("#1e1e2e") if i == 1 else QColor("#ffffff")))
        # adjust brush
        if i == 1:
            p.setBrush(QBrush(QColor(255, 255, 255, 230)))
        else:
            p.setBrush(QBrush(QColor(255, 255, 255, 255)))
        # draw plate bg
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(int(cx - w // 2), int(y), int(w), int(h), h // 2, h // 2)
        # led
        p.setBrush(QBrush(QColor("#2ecc71") if i != 2 else QColor("#f1c40f")))
        p.drawEllipse(int(cx + w // 2 - h // 2 - 6), int(y + h // 2 - 4), 8, 8)
        # vent lines
        c = QColor("#1e1e2e")
        c.setAlpha(60)
        p.setPen(QPen(c, 1))
        for vx in range(3):
            lx = int(cx - w // 2 + 18 + vx * 18)
            p.drawLine(lx, int(y + 5), lx, int(y + h - 5))
        p.setPen(Qt.PenStyle.NoPen)

    # P letter watermark subtle
    p.setPen(QColor(255, 255, 255, 26))
    f = QFont("Segoe UI", max(1, int(size * 0.18)), QFont.Weight.Bold)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
    p.setFont(f)
    # p.drawText(bg_rect, Qt.AlignmentFlag.AlignCenter, "P")

    p.end()
    return QIcon(pm)


def make_tray_icon(size: int = 64, online: bool = True, alerts: int = 0) -> QIcon:
    try:
        from proxmox_widget.ui.font_fix import ensure_valid_app_font

        ensure_valid_app_font()
    except Exception:
        pass
    size = max(1, int(size))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    if not p.isActive():
        p.end()
        return QIcon(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    bg = QColor("#e85d04") if online else QColor("#6c7086")
    p.setBrush(QBrush(bg))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(pm.rect().adjusted(2, 2, -2, -2), 12, 12)
    # icon glyph
    p.setPen(QColor("#ffffff"))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor("#ffffff"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    cx, cy = size // 2, size // 2
    w, h = int(size * 0.42), int(size * 0.1)
    for i in range(2):
        y = cy - 6 + i * 12
        p.setBrush(QBrush(QColor("#ffffff")))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(int(cx - w // 2), int(y), int(w), int(h), 3, 3)
        p.setBrush(QBrush(QColor("#2ecc71")))
        p.drawEllipse(int(cx + w // 2 - 6), int(y + 1), 6, 6)
    if alerts:
        r = max(1, size // 4)
        p.setBrush(QBrush(QColor("#ff3b30")))
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.drawEllipse(size - r - 2, 2, r, r)
        p.setPen(QColor("#ffffff"))
        f = QFont("Segoe UI", max(1, int(r * 0.55)), QFont.Weight.Bold)
        p.setFont(f)
        p.drawText(int(size - r - 2), 2, r, r, Qt.AlignmentFlag.AlignCenter, str(min(alerts, 9)))
    p.end()
    return QIcon(pm)
