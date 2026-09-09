# Screenshots

Single hero keeps the README fast and focused.

| File | What it shows | How to capture |
| --- | --- | --- |
| `dashboard.png` | Hero — ProxmoxWidget on Windows, live pve-01 dashboard (440×573, ~23 KB, window frame) | Run `python scripts/capture_onscreen.py` on Windows (visible, not offscreen) with live data; saves `dashboard.png?v=hero` via `QScreen.grabWindow(winId)` |

Tips:

- Keep hero under 600 KB (current 23334 bytes); use PNG.
- Blur or replace real hostnames/tokens with `your.host.example`.
- After replacing, run `Get-ChildItem docs/screenshots/*.png` — expect 1 file (dashboard.png).
