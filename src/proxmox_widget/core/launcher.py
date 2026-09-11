"""Hand a console off to whatever the desktop uses for it.

noVNC is a plain URL. SPICE is a .vv file that remote-viewer registers itself
for. RDP is a .rdp file handed to the platform client. SSH opens in the user's
own terminal, so keys, agent and known_hosts all behave as they do anywhere
else.
"""

from __future__ import annotations

import atexit
import ipaddress
import os
import platform
import shlex
import shutil
import subprocess
import tempfile
import webbrowser
from pathlib import Path

from loguru import logger

from proxmox_widget.api.exceptions import ActionFailedError

_which_cache: dict[str, str | None] = {}


def _which(cmd: str) -> str | None:
    if cmd not in _which_cache:
        _which_cache[cmd] = shutil.which(cmd)
    return _which_cache[cmd]


def _cleanup_temp_dirs() -> None:
    try:
        tmp = Path(tempfile.gettempdir())
        for d in tmp.glob("proxmoxwidget-*"):
            try:
                shutil.rmtree(d, ignore_errors=True)
            except OSError:
                pass
    except Exception:
        pass


atexit.register(_cleanup_temp_dirs)


def open_url(url: str) -> None:
    webbrowser.open(url)


def open_file(path: Path) -> None:
    """Open a file with the OS default handler (remote-viewer for .vv)."""
    system = platform.system()
    if system == "Windows":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif system == "Darwin":
        try:
            subprocess.Popen(["open", str(path)])
        except OSError as e:
            raise ActionFailedError(f"failed to open {path}: {e}") from e
    else:
        try:
            subprocess.Popen(["xdg-open", str(path)])
        except OSError as e:
            raise ActionFailedError(f"failed to open {path}: {e}") from e


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
    viewer = _which("remote-viewer")
    if viewer:
        try:
            subprocess.Popen([viewer, str(path)])
        except OSError as e:
            raise ActionFailedError(f"failed to launch remote-viewer: {e}") from e
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
    host_net: ipaddress.IPv4Network | ipaddress.IPv6Network | None = None
    if near:
        try:
            if "/" in near:
                host_net = ipaddress.ip_interface(near).network  # type: ignore[assignment]
            else:
                addr = ipaddress.ip_address(near)
                if isinstance(addr, ipaddress.IPv6Address):
                    host_net = ipaddress.ip_network(f"{near}/64", strict=False)  # type: ignore[assignment]
                else:
                    host_net = ipaddress.ip_network(f"{near}/24", strict=False)  # type: ignore[assignment]
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


# ---- ssh ---------------------------------------------------------------------


def ssh_command(host: str, user: str = "root", port: int = 22) -> list[str]:
    """ssh runs in the user's own terminal, so keys and agent come for free."""
    if port == 22:
        return ["ssh", "-tt", f"{user}@{host}"]
    return ["ssh", "-tt", "-p", str(port), f"{user}@{host}"]


def terminal_command(ssh_argv: list[str]) -> list[str] | None:
    """Wrap an argv in the desktop's own terminal emulator.

    Returns None when nothing is installed — the caller then lets the OS decide
    how to present the bare ssh command.
    """
    system = platform.system()
    if system == "Windows":
        # wt is Windows Terminal; conhost is the legacy console, always there
        for term, wrap in (("wt", ["--"]), ("conhost", [])):
            found = _which(term)
            if found:
                return [found, *wrap, *ssh_argv]
        return None
    if system == "Darwin":
        # -a Terminal: reuse the running app instead of stacking instances
        return ["open", "-a", "Terminal", "bash", "-c", shlex.join([*ssh_argv, "; exec bash"])]
    for term, fmt in (
        ("x-terminal-emulator", ["-e"]),
        ("gnome-terminal", ["--"]),
        ("konsole", ["-e"]),
        ("xfce4-terminal", ["-x"]),
        ("alacritty", ["-e"]),
        ("kitty", []),
        ("foot", []),
        ("xterm", ["-e"]),
    ):
        found = _which(term)
        if found:
            return [found, *fmt, *ssh_argv]
    return None


def open_ssh(host: str, user: str = "root", port: int = 22) -> bool:
    """Open an SSH session in a terminal window. Returns False if ssh is missing."""
    if not _which("ssh"):
        logger.warning("no ssh binary found for {}", platform.system())
        return False
    ssh_argv = ssh_command(host, user, port)
    cmd = terminal_command(ssh_argv)
    if cmd is None:
        # no terminal emulator found — hand the bare command to the OS, which
        # usually knows to open a console for it
        cmd = ssh_argv
    logger.info("launching ssh: {}", " ".join(cmd))
    try:
        subprocess.Popen(cmd)
    except OSError as e:
        raise ActionFailedError(f"failed to launch ssh: {e}") from e
    return True


# ---- rdp ---------------------------------------------------------------------


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
        found = _which(client)
        if found:
            return [found, *args]
    return None


def build_rdp_file(host: str, port: int = 3389, username: str = "") -> str:
    """A minimal but real .rdp file, as mstsc and xfreerdp both read it.

    smart sizing keeps the remote desktop fitting the local window instead of
    scrolling; the rest are the defaults mstsc itself writes.
    """
    lines = [
        f"full address:s:{host}:{port}",
        "screen mode id:i:1",
        "smart sizing:i:1",
        "audiomode:i:2",
    ]
    if username:
        lines.append(f"username:s:{username}")
    return "\r\n".join(lines) + "\r\n"


def write_rdp_file(content: str, vmid: int) -> Path:
    """Write the .rdp next to where the SPICE ticket lands — 0700 directory.

    It carries no secret, but a per-launch directory keeps parallel sessions
    from ever overwriting each other and makes cleanup one rmdir.
    """
    directory = Path(tempfile.mkdtemp(prefix="proxmoxwidget-"))
    path = directory / f"rdp-{vmid}.rdp"
    path.write_text(content, encoding="utf-8")
    return path


def open_rdp_file(path: Path) -> bool:
    """Hand a .rdp file to the platform client. False if none is installed."""
    system = platform.system()
    if system == "Windows":
        # mstsc ignores the file association and reads the path directly
        try:
            subprocess.Popen(["mstsc", str(path)])
        except OSError as e:
            raise ActionFailedError(f"failed to launch mstsc: {e}") from e
        return True
    if system == "Darwin":
        try:
            subprocess.Popen(["open", str(path)])
        except OSError as e:
            raise ActionFailedError(f"failed to open {path}: {e}") from e
        return True
    for client, args in (
        ("xfreerdp", []),
        ("xfreerdp3", []),
        ("remmina", []),
    ):
        found = _which(client)
        if found:
            try:
                subprocess.Popen([found, *args, str(path)])
            except OSError as e:
                raise ActionFailedError(f"failed to launch {found}: {e}") from e
            return True
    logger.warning("no RDP client found for {}", platform.system())
    return False


def open_rdp(host: str, port: int = 3389) -> bool:
    """Legacy flag-based launch, kept for callers without a config object."""
    cmd = rdp_command(host, port)
    if not cmd:
        logger.warning("no RDP client found for {}", platform.system())
        return False
    logger.info("launching RDP: {}", " ".join(cmd))
    try:
        subprocess.Popen(cmd)
    except OSError as e:
        raise ActionFailedError(f"failed to launch RDP: {e}") from e
    return True
