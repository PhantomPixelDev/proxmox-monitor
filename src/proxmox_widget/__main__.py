from __future__ import annotations

import os
import pathlib
import sys

try:
    from proxmox_widget.ui.font_fix import install_qfont_suppress_filter as _early_install

    _early_install()
except Exception:
    try:
        from PySide6.QtCore import qInstallMessageHandler as _qIMH

        def _fallback_filter(t, ctx, msg):  # type: ignore[no-untyped-def]
            m = str(msg)
            if "Point size <= 0" in m and "setPointSize" in m:
                return
            try:
                import sys as _sys

                _sys.stderr.write(m + "\n")
            except Exception:
                pass

        _qIMH(_fallback_filter)  # type: ignore[arg-type]
    except Exception:
        pass

from loguru import logger
from platformdirs import user_log_dir

from proxmox_widget.app import create_app


def _setup_logging() -> None:
    logger.remove()
    dev = (
        "--dev" in sys.argv
        or "--console" in sys.argv
        or os.environ.get("PROXMOX_WIDGET_DEV") == "1"
    )
    if dev:
        logger.add(sys.stderr, level="INFO")
        return
    try:
        sys.stderr.write("")
        has_console = sys.stderr is not None and hasattr(sys.stderr, "isatty")
    except Exception:
        has_console = False
    if has_console and os.isatty(sys.stderr.fileno()) if hasattr(sys.stderr, "fileno") else False:
        logger.add(sys.stderr, level="WARNING")
        return
    log_dir = pathlib.Path(user_log_dir("ProxmoxWidget", "ProxmoxWidget"))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "proxmox-widget.log"
    logger.add(str(log_file), level="INFO", rotation="5 MB", retention="7 days")
    logger.add(sys.stderr, level="ERROR")


def main() -> int:
    _setup_logging()
    if "--dev" in sys.argv:
        sys.argv.remove("--dev")
    if "--console" in sys.argv:
        sys.argv.remove("--console")
    try:
        from proxmox_widget.ui.font_fix import install_qfont_suppress_filter

        install_qfont_suppress_filter()
    except Exception:
        pass
    try:
        import proxmox_widget.ui.font_fix  # noqa: F401  # ensure QFont clamp active before any font
    except Exception:
        pass
    app, w = create_app()
    try:
        from proxmox_widget.ui.font_fix import ensure_valid_app_font

        ensure_valid_app_font(app)
    except Exception:
        pass
    w.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
