# Screenshots

All captures are placeholders rendered from the app theme. Replace with real captures when you cut a release. Keep the same filenames so the README grid stays intact.

| File | What it shows | How to capture for real |
| --- | --- | --- |
| `dashboard.png` | Dashboard tab, two clusters with CPU/RAM/Disk bars | Launch app, connect to `your.host.example:8006`, open Dashboard tab |
| `nodes.png` | Nodes tab, per-node uptime and resource bars | Nodes tab with at least 2 nodes online |
| `vms.png` | VMs tab, running and stopped VMs with action buttons | VMs tab, include one running and one stopped VM |
| `containers.png` | Containers (LXC) tab | Containers tab with LXC entries |
| `storage.png` | Storage tab with usage bars | Storage tab, capture local and shared storages |
| `settings.png` | Settings, Add Cluster dialog and API token field | Settings dialog, blur real token |
| `tray.png` | System tray menu and tooltip | Right-click tray icon on Windows, hover for tooltip |

Capture tips:

- Size 1280 by 720 or larger, PNG, no window shadow cropping.
- Use dark theme for consistency, then capture light theme as an extra if you want.
- Blur or replace real hostnames and tokens with `your.host.example`.
- After replacing, run `Get-ChildItem docs/screenshots/*.png` and make sure each file is under 600 KB for fast GitHub rendering.

Placeholders were generated with Pillow from `src/proxmox_widget/resources/app.png` so the repo renders correctly before real screenshots exist.
