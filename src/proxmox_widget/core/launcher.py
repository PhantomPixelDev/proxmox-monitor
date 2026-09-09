"""Hand a console off to whatever the desktop uses for it.

noVNC is a plain URL. SPICE is a .vv file that remote-viewer registers itself
for. RDP has no single cross-platform entry point, so each OS gets its own
client list.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
import webbrowser
from pathlib import Path

from loguru import logger


def open_url(url: str) -> None:
    webbrowser.open(url)


def open_file(path: Path) -> None:
    """Open a file with the OS default handler (remote-viewer for .vv)."""
    system = platform.system()
    if system == "Windows":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif system == "Darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def write_spice_file(vv_content: str, vmid: int) -> Path:
    path = Path(tempfile.gettempdir()) / f"proxmoxwidget-spice-{vmid}.vv"
    path.write_text(vv_content, encoding="utf-8")
    return path


def open_spice(vv_content: str, vmid: int) -> Path:
    path = write_spice_file(vv_content, vmid)
    viewer = shutil.which("remote-viewer")
    if viewer:
        subprocess.Popen([viewer, str(path)])
    else:
        open_file(path)
    return path


def rdp_command(host: str, port: int = 3389) -> list[str] | None:
    """First available RDP client for this OS, or None if nothing is installed."""
    system = platform.system()
    if system == "Windows":
        return ["mstsc", f"/v:{host}:{port}"]
    if system == "Darwin":
        return ["open", f"rdp://full%20address=s:{host}:{port}"]
    for client, args in (
        ("xfreerdp", [f"/v:{host}:{port}"]),
        ("xfreerdp3", [f"/v:{host}:{port}"]),
        ("remmina", ["-c", f"rdp://{host}:{port}"]),
        ("rdesktop", [f"{host}:{port}"]),
    ):
        found = shutil.which(client)
        if found:
            return [found, *args]
    return None


def open_rdp(host: str, port: int = 3389) -> bool:
    cmd = rdp_command(host, port)
    if not cmd:
        logger.warning("no RDP client found for {}", platform.system())
        return False
    logger.info("launching RDP: {}", " ".join(cmd))
    subprocess.Popen(cmd)
    return True
