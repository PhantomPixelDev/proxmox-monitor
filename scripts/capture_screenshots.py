"""Capture real ProxmoxWidget screenshots for README.

Uses Qt offscreen + live API data (needs running PVE or mocked health).
Run:
  pythonw scripts/capture_screenshots.py              # uses your keyring config (pve-01)
  pythonw scripts/capture_screenshots.py --mock       # no PVE needed, fake data

Outputs to docs/screenshots/*.png (1280x720, 2x for retina).
Swaps placeholders created earlier with real captures.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from proxmox_widget.config.models import ClusterHealth, LxcContainer, ProxmoxNode, QemuVm, StorageStatus
from proxmox_widget.ui.dashboard import Dashboard


def mock_health() -> list[ClusterHealth]:
    n = ProxmoxNode(node="pve", status="online", cpu=0.38, maxcpu=4, mem=4_200_000_000, maxmem=16_650_981_376, disk=31_000_000_000, maxdisk=100_861_726_720, uptime=14 * 86400 + 7 * 3600)
    vms = [
        QemuVm(vmid=100, name="parrot-001", node="pve", status="stopped", cpus=4, cpu=0, mem=0, maxmem=8_438_939_648, template=False),
        QemuVm(vmid=101, name="portfolio", node="pve", status="stopped", cpus=4, cpu=0, mem=0, maxmem=8_438_939_648),
        QemuVm(vmid=112, name="win10", node="pve", status="running", cpus=4, cpu=0.42, mem=2_100_000_000, maxmem=8_489_271_296),
        QemuVm(vmid=122, name="openclaw-led-bussiness", node="pve", status="stopped", cpus=4, cpu=0, mem=0, maxmem=8_388_608_000),
    ]
    cts = [
        LxcContainer(vmid=107, name="docker", node="pve", status="running", cpus=2, cpu=0.18, mem=690_794_496, maxmem=4_294_967_296, disk=6_195_388_416, maxdisk=52_521_566_208, uptime=3600),
        LxcContainer(vmid=150, name="changeproof-test", node="pve", status="running", cpus=1, cpu=0.05, mem=31_584_256, maxmem=1_073_741_824, disk=739_733_504, maxdisk=8_350_298_112, uptime=1282),
    ]
    stor = [
        StorageStatus(storage="local", node="pve", type="dir", status="available", total=100_861_726_720, used=31_151_751_168, avail=69_709_975_552, enabled=True),
        StorageStatus(storage="local-lvm", node="pve", type="lvmthin", status="available", total=875_485_462_528, used=149_007_625_722, avail=726_477_836_806, enabled=True, shared=False),
    ]
    return [ClusterHealth(cluster_id="pve-192-168-10-2", cluster_name="pve-01", online=True, nodes=[n], vms=vms, containers=cts, storages=stor)]


def capture(dashboard: Dashboard, out_dir: pathlib.Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    def grab(name: str, tab_index: int) -> None:
        dashboard.tabs.setCurrentIndex(tab_index)
        dashboard.repaint()
        QApplication.processEvents()
        pm = dashboard.grab()
        # scale to 1280 width for docs while keeping aspect, add shadow via stylesheet already
        scaled = pm.scaled(1280, 900, aspectMode=0, mode=1)  # KeepAspectRatio, Smooth
        # pad to 1280x720
        out = QPixmap(1280, 720)
        out.fill(dashboard.palette().color(dashboard.backgroundRole()))
        painter = __import__("PySide6.QtGui", fromlist=["QPainter"]).QPainter(out)
        x = (1280 - scaled.width()) // 2
        y = (720 - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        painter.end()
        path = out_dir / f"{name}.png"
        out.save(str(path), "PNG")
        print(f"saved {path} {path.stat().st_size} bytes")

    grabs = [("dashboard", 0), ("nodes", 1), ("vms", 2), ("containers", 3), ("storage", 4)]
    for name, idx in grabs:
        grab(name, idx)

    # settings dialog
    from proxmox_widget.config.manager import load_settings
    from proxmox_widget.ui.settings_dialog import SettingsDialog

    s = load_settings()
    dlg = SettingsDialog(s)
    dlg.show()
    QApplication.processEvents()
    pm = dlg.grab()
    scaled = pm.scaled(900, 700, aspectMode=0, mode=1)
    out = QPixmap(900, 700)
    out.fill(dlg.palette().color(dlg.backgroundRole()))
    p = __import__("PySide6.QtGui", fromlist=["QPainter"]).QPainter(out)
    p.drawPixmap((900 - scaled.width()) // 2, (700 - scaled.height()) // 2, scaled)
    p.end()
    path = out_dir / "settings.png"
    out.save(str(path), "PNG")
    print(f"saved {path}")
    dlg.close()

    # tray placeholder just copy dashboard for now
    import shutil
    shutil.copy(out_dir / "dashboard.png", out_dir / "tray.png")
    print("tray.png copied from dashboard.png (manual tray capture needs OS screenshot)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="use fake data, no PVE needed")
    ap.add_argument("--out", default="docs/screenshots")
    args = ap.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    dash = Dashboard()
    dash.show()
    if args.mock:
        health = mock_health()
    else:
        from proxmox_widget.config.manager import load_settings
        from proxmox_widget.api.client import ProxmoxClient
        import asyncio

        s = load_settings()
        if not s.clusters:
            print("no clusters in keyring, falling back to --mock")
            health = mock_health()
        else:
            async def fetch() -> list[ClusterHealth]:
                out: list[ClusterHealth] = []
                for c in s.clusters:
                    h = await ProxmoxClient(c).fetch_health()
                    out.append(h)
                return out

            health = asyncio.run(fetch())
    dash.update_health(health)
    dash.show()
    dash.raise_()

    out_dir = ROOT / args.out
    QTimer.singleShot(600, lambda: (capture(dash, out_dir), app.quit()))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
