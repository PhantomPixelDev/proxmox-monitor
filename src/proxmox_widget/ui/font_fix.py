"""Central QFont safety: ensure valid pointSize everywhere.

Root cause of 26 warnings + tab-change persistence:
- QApplication default font can be pointSize -1 / pixelSize -1 on offscreen or
  before platform font resolves. Any QWidget created with that -1 then
  propagates to children; each child that triggers style polish may internally
  call QFont::setPointSize(-1) -> 26 Qt warnings via C++ path (bypasses Python
  monkey-patch; Qt style polish resolves fonts in C++).
- QFont() bare constructor returns pointSize -1 until QApplication font is
  valid; code that computed size from QFont().pointSize() would pass -1.
- QSS never contained font-size -1, but stylesheet application with invalid
  base font still warns via C++ QFont::setPointSize(-1) which Python clamp
  cannot intercept.
- Tab switching re-polishes QTabBar/QLabel via QSS and reuses diff-patched
  cards, re-triggering C++ warnings if app font was invalid.

Fix:
- Monkey-patch QFont.setPointSize / setPixelSize / setPointSizeF to clamp
  <=0 to 1 (global safety net for Python calls)
- Wrap QFont.__init__ to clamp pointSize <=0 to 1 when constructed via
  Python (covers QFont("Segoe UI", -1) edge)
- Provide ensure_valid_app_font(app) to set Segoe UI 9pt if invalid — MUST
  be called BEFORE any QSS is set and BEFORE any Dashboard is created,
  otherwise C++ style polish will warn even with Python clamp.
- Provide safe_font() helper to copy app font when available
"""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

_orig_setPointSize = QFont.setPointSize

def _clamped_setPointSize(self: QFont, size: int) -> None:
    try:
        if size is not None and int(size) <= 0:
            size = 1
    except Exception:
        size = 1
    return _orig_setPointSize(self, int(size))

# patch once at import
try:
    QFont.setPointSize = _clamped_setPointSize  # type: ignore[method-assign,assignment]
except Exception:
    pass

_orig_setPixelSize = QFont.setPixelSize

def _clamped_setPixelSize(self: QFont, size: int) -> None:
    try:
        if size is not None and int(size) <= 0:
            size = 1
    except Exception:
        size = 1
    return _orig_setPixelSize(self, int(size))

try:
    QFont.setPixelSize = _clamped_setPixelSize  # type: ignore[method-assign,assignment]
except Exception:
    pass

# also clamp float variant if present
try:
    _orig_setPointSizeF = QFont.setPointSizeF  # type: ignore[attr-defined]

    def _clamped_setPointSizeF(self: QFont, size: float) -> None:
        try:
            if size is not None and float(size) <= 0:
                size = 1.0
        except Exception:
            size = 1.0
        return _orig_setPointSizeF(self, float(size))

    QFont.setPointSizeF = _clamped_setPointSizeF  # type: ignore[method-assign,assignment]
except Exception:
    pass

# wrap QFont.__init__ to clamp pointSize <=0 passed via constructor
try:
    _orig_qfont_init = QFont.__init__  # type: ignore[attr-defined]

    def _clamped_qfont_init(self: QFont, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        # positional: QFont(), QFont(family, pointSize, weight, italic) etc
        # second positional arg is pointSize if int/float
        if args and len(args) >= 2 and isinstance(args[1], (int, float)):
            try:
                if int(args[1]) <= 0:
                    args = (args[0], 1, *args[2:])  # type: ignore[assignment]
            except Exception:
                pass
        if "pointSize" in kwargs:
            try:
                if int(kwargs["pointSize"]) <= 0:  # type: ignore[arg-type]
                    kwargs["pointSize"] = 1
            except Exception:
                kwargs["pointSize"] = 1
        return _orig_qfont_init(self, *args, **kwargs)

    QFont.__init__ = _clamped_qfont_init  # type: ignore[method-assign,assignment]
except Exception:
    pass


_qfont_prev_handler = None  # type: ignore[assignment]
_qfont_filter_installed = False


def _qfont_message_filter(msg_type, context, message: str) -> None:  # type: ignore[no-untyped-def]
    """Qt message handler that suppresses only QFont::setPointSize Point size <=0 warnings."""
    try:
        msg = str(message)
    except Exception:
        msg = ""
    # suppress only the specific un-patchable C++ polish warning (bypasses Python clamp)
    if "Point size <= 0" in msg and "setPointSize" in msg:
        return
    # delegate to previous handler or default stderr
    prev = _qfont_prev_handler
    if prev is not None:
        try:
            return prev(msg_type, context, message)  # type: ignore[misc]
        except TypeError:
            try:
                return prev(message)  # type: ignore[misc]
            except Exception:
                pass
        except Exception:
            pass
    # no previous handler: Qt default would print to stderr — replicate for non-filtered
    try:
        import sys as _sys

        # Qt formats prefix like "Qt Warning: ..." — just emit the message
        _sys.stderr.write(msg + "\n")
        try:
            _sys.stderr.flush()
        except Exception:
            pass
    except Exception:
        pass


def install_qfont_suppress_filter() -> None:
    """Install qInstallMessageHandler filter for QFont::setPointSize(-1) very early.

    Idempotent; safe to call before QApplication. Must be called before any
    QFont/QApplication creation to cover all early polish warnings.
    """
    global _qfont_prev_handler, _qfont_filter_installed
    if _qfont_filter_installed:
        return
    try:
        from PySide6.QtCore import qInstallMessageHandler  # type: ignore[import-not-found]

        prev = qInstallMessageHandler(_qfont_message_filter)  # type: ignore[arg-type]
        # qInstallMessageHandler returns previous handler (or None for default)
        # keep the *original* previous, not our own on re-entry
        if _qfont_prev_handler is None and prev is not None and prev is not _qfont_message_filter:
            _qfont_prev_handler = prev
        _qfont_filter_installed = True
    except Exception:
        pass


# auto-install on import as safety net (real early install still done in __main__.py)
try:
    install_qfont_suppress_filter()
except Exception:
    pass


def ensure_valid_app_font(app: QApplication | None = None) -> None:
    """Ensure app font has valid pointSize/pixelSize; call right after QApplication()."""
    try:
        if app is None:
            app = QApplication.instance()
        if app is None:
            return
        f = app.font()
        ps = f.pointSize()
        px = f.pixelSize()
        if ps <= 0 and px <= 0:
            nf = QFont("Segoe UI", 9)
            if nf.pointSize() <= 0:
                nf.setPointSize(9)
            app.setFont(nf)
        elif ps <= 0 and px > 0:
            pt = max(1, round(int(px) * 72 / 96))
            nf = QFont(f.family() or "Segoe UI", pt)
            try:
                nf.setPixelSize(int(px))
            except Exception:
                pass
            app.setFont(nf)
        elif ps <= 0:
            f.setPointSize(9)
            app.setFont(f)
        try:
            vf = app.font()
            if vf.pointSize() <= 0 and vf.pixelSize() <= 0:
                nf2 = QFont("Segoe UI", 9)
                if nf2.pointSize() <= 0:
                    nf2.setPointSize(9)
                app.setFont(nf2)
        except Exception:
            pass
    except Exception:
        pass


def safe_font() -> QFont:
    """Return a valid QFont copying app font if available, else Segoe UI 9."""
    try:
        app = QApplication.instance()
        if app is not None:
            f = app.font()
            if f.pointSize() > 0 or f.pixelSize() > 0:
                return QFont(f)
    except Exception:
        pass
    nf = QFont("Segoe UI", 9)
    if nf.pointSize() <= 0:
        try:
            nf.setPointSize(9)
        except Exception:
            pass
    return nf
