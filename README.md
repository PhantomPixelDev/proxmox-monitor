<p align="center">
  <img src="src/proxmox_widget/resources/app.png" width="88" alt="ProxmoxWidget icon" />
</p>

<h1 align="center">ProxmoxWidget</h1>

<p align="center">Proxmox VE in your system tray. Nodes, VMs, containers and storage at a glance, without opening the browser.</p>

<p align="center">
  <b><a href="https://phantompixeldev.github.io/proxmox-monitor/">Website</a></b> ·
  <a href="https://github.com/PhantomPixelDev/proxmox-monitor/releases/latest">Download</a> ·
  <a href="https://github.com/PhantomPixelDev/proxmox-monitor/issues">Issues</a>
</p>

<p align="center">
  <a href="https://github.com/PhantomPixelDev/proxmox-monitor/releases"><img src="https://img.shields.io/github/v/release/PhantomPixelDev/proxmox-monitor?label=release&color=2ecc71" alt="Latest release" /></a>
  <a href="https://github.com/PhantomPixelDev/proxmox-monitor/actions/workflows/ci.yml?branch=master"><img src="https://img.shields.io/github/actions/workflow/status/PhantomPixelDev/proxmox-monitor/ci.yml?branch=master&label=build" alt="Build status" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/PhantomPixelDev/proxmox-monitor?color=89b4fa" alt="MIT license" /></a>
</p>

<p align="center"><img src="docs/screenshots/dashboard.png" width="420" alt="ProxmoxWidget overview: cluster status, VM and container counts, per-node CPU, RAM and disk bars" /></p>

## Download

Ready-to-run builds, no Python needed — **[latest release](https://github.com/PhantomPixelDev/proxmox-monitor/releases/latest)**.

| System | File |
| --- | --- |
| Windows | `Windows-x64-Setup.exe`, or `Windows-x64-Portable.zip` to run without installing |
| Linux | `Linux-x64.tar.gz` — extract and run `ProxmoxWidget` |
| macOS | `macOS-x64.dmg` — drag to Applications |

Every release ships `SHA256SUMS.txt` if you want to verify the download.

## Setup

1. Install it, or unzip the portable build anywhere. It starts in the tray. On Windows check the hidden-icons chevron; on macOS look in the menu bar.
2. In Proxmox, go to **Datacenter → Access → API Tokens → Add**. Pick a user such as `widget@pve`, set the token ID to `monitor`, and copy the secret — it is shown once.
3. Under **Datacenter → Permissions → Add**, grant that user `PVEAuditor` on `/`. Add `VM.PowerMgmt` for the start, stop and reboot buttons, and `VM.Console` for SPICE.
4. In the tray, open Settings → Add, and enter the host, port `8006`, the token ID `widget@pve!monitor` and the secret.

Self-signed certificates are fine: turn TLS verification off for that cluster. The secret goes to your OS keyring, never to a config file.

### Consoles

The Console button opens the Proxmox web console in your browser, and that page needs a web-UI login. An API token cannot create a browser session, so if you are not logged in, Proxmox answers `401 no ticket`. Log in to the web UI once, with Open Proxmox, and the console works for as long as that session lasts.

SPICE and RDP do not need the browser. SPICE needs `VM.Console` on the token, and RDP needs the QEMU guest agent installed and running in the VM.

## What it does

- CPU, memory and disk for every node, VM and LXC container, refreshed on a timer you set.
- Search on each tab by name, VMID, node or status, plus a Running-only toggle.
- Start, stop and reboot, waiting until the guest actually reaches that state.
- Consoles in one click: noVNC for any guest, SPICE through `remote-viewer`, RDP to the address the QEMU guest agent reports, and a shell for each node.
- Several clusters at once, with offline ones flagged in the tray icon and tooltip.
- Dark and light themes that follow your OS.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `OFFLINE` right after adding a cluster | Check the banner error. Confirm `https://your-host:8006` loads in a browser, and re-paste the token without stray spaces. |
| `401 Unauthorized` | Token ID or secret is wrong. The ID must be the full `user@realm!tokenname`. |
| `403 Forbidden` on start or stop | The token lacks `VM.PowerMgmt`. Everything else keeps working without it. |
| `401 no ticket` when opening a console | The browser has no Proxmox session. Log in to the web UI once, in the same browser. |
| SPICE says the token lacks `VM.Console` | Add that privilege to the token in **Datacenter → Permissions**. |
| RDP says there is no guest agent | Install and enable the QEMU guest agent in that VM; without it the app cannot learn its IP. |
| Certificate error | Add your CA to the OS trust store, or turn TLS verification off for that cluster. |
| No tray icon on Windows | Look under the hidden-icons chevron and drag it out. |
| High CPU | Raise the refresh interval in Settings. |

For logs, start it with `--dev`:

```bash
ProxmoxWidget.exe --dev      # Windows
./ProxmoxWidget --dev        # Linux and macOS
```

## FAQ

**Is this an official Proxmox project?** No. It is a community client that talks to the Proxmox VE API. Proxmox and PVE are trademarks of Proxmox Server Solutions GmbH.

**What can the token see?** Only what you grant it. `PVEAuditor` is read-only and enough for monitoring.

**Where does my data go?** Nowhere. The app talks to your Proxmox host and to GitHub for the version check, nothing else.

**Where are settings stored?** Non-secret settings in the platform config directory, secrets in the OS keyring — Credential Manager, Keychain or Secret Service.

## Building from source

```bash
git clone https://github.com/PhantomPixelDev/proxmox-monitor.git
cd proxmox-monitor
uv venv && uv pip install -e ".[dev]"
python -m proxmox_widget --dev
```

`pytest` runs the tests, `ruff check src tests` the lints. Release builds are produced by GitHub Actions with Nuitka; see `.github/workflows/release.yml`.

## License

MIT — see [LICENSE](LICENSE). Not affiliated with Proxmox Server Solutions GmbH.
