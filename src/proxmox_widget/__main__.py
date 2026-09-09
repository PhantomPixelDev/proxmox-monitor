from __future__ import annotations

import os
import sys
import pathlib

from loguru import logger
from platformdirs import user_log_dir

from proxmox_widget.app import create_app


def _setup_logging() -> None:
    logger.remove()
    dev = "--dev" in sys.argv or "--console" in sys.argv or os.environ.get("PROXMOX_WIDGET_DEV") == "1"
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
    app, w = create_app()
    w.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
