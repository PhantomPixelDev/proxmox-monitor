# 🖥️ ProxmoxWidget

Lightweight cross-platform system-tray / menu-bar client for Proxmox VE.

> Run it on Windows, Linux, or macOS — click the tray icon and get a live dashboard of your PVE infrastructure.

```
┌──────────────────────────────┐
│ 🖥 ProxmoxWidget              │
├──────────────────────────────┤
│ 🟢 pve-01                    │
│    CPU   ███░░░░  38%        │
│    RAM   █████░░  62%        │
│    Uptime 14d 7h             │
│                              │
│ VMs                           │
│ 🟢 web-server       42% CPU  │
│ 🔴 minecraft        STOPPED  │
│                              │
│ Containers                    │
│ 🟢 nginx             RUNNING │
│                              │
│ [ Open Proxmox ]   [ ⚙ ]     │
└──────────────────────────────┘
```

## Features

- **Multiple clusters & nodes** — manage many `host:port` endpoints
- **Live dashboard** — CPU/RAM/storage, uptime, VM/LXC status
- **Actions** — start / stop / restart / open console
- **Health & Alerts** — node/VM down notifications, offline mode
- **Auto-refresh** — configurable interval (default 30s)
- **Tray goodness** — badge, tooltip, left-click popup, right-click menu
- **Secure auth** — API-token (`PVEAPIToken=...`), secrets in OS keyring
- **Themes** — dark / light / system, QSS based
- **Cross-platform** — Windows `.exe`, Linux AppImage/`.deb`, macOS `.app`

## Quick Start

```bash
# with uv (recommended)
uv venv && uv pip install -e ".[dev]"
uv run proxmox-widget

# or pip
pip install -e ".[dev]"
proxmox-widget
```

On first launch: **⚙ Settings → Add Cluster** → `https://pve.example.com:8006` → API Token → Save.

### Creating an API Token in Proxmox

Datacenter → Access → API Tokens → Add → `widget@pve!monitor` → uncheck *Privilege Separation* → copy token.

Give it at least `PVEAuditor` + `VM.Audit` on `/` and `VM.PowerMgmt` if you want start/stop.

## Dev

```bash
ruff check src tests
basedpyright src
pytest
```

## Packaging

```bash
# PyInstaller / briefcase / nuitka — TODO
```

## License

MIT
