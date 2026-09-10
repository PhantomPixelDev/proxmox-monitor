from __future__ import annotations


def fmt_bytes(n: int) -> str:
    # binary units, matching what the Proxmox UI shows
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} PiB"


def fmt_uptime(seconds: int) -> str:
    if seconds <= 0:
        return "—"
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    parts: list[str] = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m and not d:
        parts.append(f"{m}m")
    return " ".join(parts) if parts else f"{m}m"


def bar(cpu: float, width: int = 10) -> str:
    filled = int(cpu * width)
    return "█" * filled + "░" * (width - filled)
