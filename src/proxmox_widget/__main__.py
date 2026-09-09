from __future__ import annotations

import sys

from loguru import logger

from proxmox_widget.app import create_app


def main() -> int:
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    app, w = create_app()
    w.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
