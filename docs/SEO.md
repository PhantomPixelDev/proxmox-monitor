# SEO: ProxmoxWidget

This file exists so GitHub, PyPI, and search engines rank the repo for the right long-tail queries. It also gives blog writers a copy-paste FAQ.

## One line pitch

ProxmoxWidget is a Proxmox VE desktop client that lives in the system tray and shows live node, VM, LXC, and storage health for homelabs and small clusters.

## Primary keywords

proxmox, pve, proxmox-ve, pve-monitoring, system-tray, tray-app, desktop-client, pyside6, qt6, homelab, vm-management, lxc, storage-monitoring, api-token, least-privilege, python, nuitka, windows-tray, macos-menu-bar, linux-tray

## Long-tail phrases to target

- proxmox ve desktop client
- proxmox ve tray app windows
- proxmox widget system tray
- pve monitoring desktop app
- proxmox homelab dashboard windows
- pyside6 proxmox client
- proxmox api token least privilege widget
- proxmox ve lxc vm tray monitor
- proxmox storage monitoring desktop
- python proxmox system tray app

## Suggested repo topics

Add these under GitHub Settings, About, Topics: `proxmox`, `pve`, `pve-monitoring`, `system-tray`, `pyside6`, `homelab`, `desktop-client`, `qt6`, `proxmox-ve`, `tray-app`

## Suggested PyPI keywords

`proxmox`, `pve`, `pve-monitoring`, `system-tray`, `desktop`, `monitoring`, `homelab`, `pyside6`, `qt`, `proxmox-ve`, `tray`, `vm-management`, `lxc`

Those keywords are in `pyproject.toml` `keywords` so PyPI search picks them up.

## FAQ: Long tail, SEO ready

Copy any of these into a blog post or discussion answer. Keep the links.

### What is ProxmoxWidget?

ProxmoxWidget is a cross platform tray app for Proxmox VE. It polls the Proxmox API and shows per-cluster health, per-node CPU, RAM, Disk bars, VM and LXC status, and storage use. It runs with `pythonw` on Windows so there is no console, and uses an in-app banner instead of OS popup spam.

### How do I install ProxmoxWidget on Windows?

`pipx install proxmox-widget`, then `pythonw -m proxmox_widget`. On first run go to Settings, Add Cluster, enter `your.host.example:8006` and paste `PVEAPIToken=widget@pve!monitor=...`. See the Quick Start in the README.

### How do I create a least privilege API token for ProxmoxWidget?

In Proxmox go to Datacenter, Access, API Tokens, Add `widget@pve!monitor`. Give the user or token `PVEAuditor` and `VM.Audit` on `/` for read, and `VM.PowerMgmt` only if you want Start, Stop, Reboot. Store it in the OS keyring via the app Settings. This limits harm if a token leaks.

### Does ProxmoxWidget work on Linux and macOS?

Yes. It uses PySide6 Qt. On Linux it needs a tray like KDE or GNOME AppIndicator. On macOS it shows in the menu bar. The same `pipx install proxmox-widget` works, and the Nuitka build notes in README cover onefile and app bundle.

### How is ProxmoxWidget different from the Proxmox web UI?

The web UI is full featured. ProxmoxWidget is for quick checks: one click to see which nodes and VMs are up, how full storage is, and to start or reboot a guest. It polls on a timer you control and shows an OFFLINE badge the moment a cluster stops responding. Use Open Proxmox in the app to jump to the full UI when you need it.

### Why does the widget show OFFLINE or Connection reset?

That means the API host is unreachable, the port is wrong, or TLS failed. The Troubleshooting section lists fixes for 500 retry, Connection reset, 401, and 403. Run with `--dev` to see logs without guessing.

### Is ProxmoxWidget official?

No, it is a community project. Proxmox and PVE are trademarks of Proxmox Server Solutions GmbH.

## Alt text and captions for screenshots

Use these verbatim so image search lands here.

- `ProxmoxWidget dashboard — CPU/RAM bars for pve`: Dashboard tab with cluster cards and per-node progress bars.
- `ProxmoxWidget nodes — per-node uptime and resource bars`: Nodes tab with online dots, uptime, and CPU, RAM, Disk bars.
- `ProxmoxWidget VMs — VM list with start stop reboot`: VMs tab with status badges and action buttons per VM.
- `ProxmoxWidget containers — LXC status and actions`: Containers tab with LXC status and controls.
- `ProxmoxWidget storage — disk usage bars and free space`: Storage tab with use bars and free space.
- `ProxmoxWidget settings — Add Cluster and API token flow`: Settings dialog adding `your.host.example:8006` with API token.
- `ProxmoxWidget system tray — menu and tooltip`: Tray menu, popup dashboard, and hover tooltip.

## Blog snippet

Proxmox VE already has a great web UI. What it does not have is a small desktop presence. ProxmoxWidget fills that gap. It lives in the system tray on Windows, the menu bar on macOS, and the panel on Linux. You add one or many clusters with `your.host.example:8006` and a least privilege token `widget@pve!monitor`, and you get live CPU, RAM, Disk bars for each node, a list of VMs and LXC with Start, Stop, Reboot, and a storage tab that tells you at a glance which pool is getting full. It polls on a timer, waits patiently after power actions, and marks a cluster OFFLINE the second it stops answering. No console spam, no popup spam, just a banner that fades. If you run a homelab and you check PVE ten times a day, this saves a lot of clicks.

## Checklist before release

- [ ] Replace the 7 placeholders in `docs/screenshots/*.png` with real captures, keep filenames.
- [ ] Add repo topics in GitHub settings.
- [ ] Confirm PyPI keywords render on the project page.
- [ ] Set the social preview image to `docs/screenshots/dashboard.png` or a 1280 by 640 crop of it.
- [ ] Link the README FAQ headings from at least one discussion or blog post.
