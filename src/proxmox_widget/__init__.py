"""ProxmoxWidget — system-tray client for Proxmox VE."""

from __future__ import annotations

try:
    from ._version import __version__
except ImportError:
    __version__ = "0.1.0"

__all__ = ["__version__"]
