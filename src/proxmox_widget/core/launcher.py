"""Hand a console off to whatever the desktop uses for it.

noVNC is a plain URL. SPICE is a .vv file that remote-viewer registers itself
for. RDP has no single cross-platform entry point, so each OS gets its own
client list.
"""

from __future__ import annotations

import ipaddress
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
    """Write the .vv somewhere only this user can read it.

    It carries a live SPICE ticket, so it must not land in the shared temp
    directory under a predictable name at the default umask.
    """
    directory = Path(tempfile.mkdtemp(prefix="proxmoxwidget-"))  # 0700
    path = directory / f"spice-{vmid}.vv"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(vv_content)
    return path


def discard(path: str | Path) -> None:
    """Delete a written console file, and its directory, best effort."""
    p = Path(path)
    try:
        p.unlink(missing_ok=True)
        if p.parent.name.startswith("proxmoxwidget-"):
            p.parent.rmdir()
    except OSError as e:
        logger.debug("could not remove {}: {}", p, e)


def open_spice(vv_content: str, vmid: int) -> Path:
    path = write_spice_file(vv_content, vmid)
    viewer = shutil.which("remote-viewer")
    if viewer:
        subprocess.Popen([viewer, str(path)])
    else:
        open_file(path)
    return path


def pick_rdp_host(ips: list[str], near: str = "") -> str | None:
    """Choose which address to RDP to.

    A guest often reports several: pick the one on the same network as the
    Proxmox host, since that is the one the user can reach.
    """
    usable = [ip for ip in ips if ip and not ip.startswith(("127.", "169.254."))]
    if not usable:
        return None
    try:
        host_net = ipaddress.ip_network(f"{near}/24", strict=False) if near else None
    except ValueError:
        host_net = None
    if host_net is not None:
        for ip in usable:
            try:
                if ipaddress.ip_address(ip) in host_net:
                    return ip
            except ValueError:
                continue
    return usable[0]


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
