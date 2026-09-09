"""Capture real ProxmoxWidget screenshots for README.

Uses Qt offscreen + live API data (needs running PVE or mocked health).
Run:
  QT_QPA_PLATFORM=offscreen python scripts/capture_screenshots.py --mock   # no PVE needed, fake data
  QT_QPA_PLATFORM=offscreen python scripts/capture_screenshots.py          # uses docs/live_health.json if present

Outputs to docs/screenshots/*.png (440x560, offscreen grab).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QTimer
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


def load_live_health() -> list[ClusterHealth] | None:
    """Load live health from docs/live_health.json if present."""
    p = ROOT / "docs" / "live_health.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        # file is a single ClusterHealth object (not list)
        if isinstance(data, dict):
            ch = ClusterHealth.model_validate(data)
            return [ch]
        if isinstance(data, list):
            return [ClusterHealth.model_validate(x) for x in data]
    except Exception as e:
        print(f"failed to load live_health.json: {e}")
    return None


def capture(dashboard: Dashboard, out_dir: pathlib.Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    dashboard.setFixedSize(440, 560)
    dashboard.resize(440, 560)

    def grab(name: str, tab_index: int) -> None:
        dashboard.tabs.setCurrentIndex(tab_index)
        dashboard.repaint()
        QApplication.processEvents()
        pm = dashboard.grab()
        if pm.width() != 440 or pm.height() != 560:
            pm = pm.scaled(440, 560)
        path = out_dir / f"{name}.png"
        pm.save(str(path), "PNG")
        print(f"saved {path} {path.stat().st_size} bytes {pm.width()}x{pm.height()}")

    grabs = [("dashboard", 0), ("nodes", 1), ("vms", 2), ("containers", 3), ("storage", 4)]
    for name, idx in grabs:
        grab(name, idx)

    from proxmox_widget.config.manager import load_settings
    from proxmox_widget.ui.settings_dialog import SettingsDialog

    s = load_settings()
    if not s.clusters:
        from proxmox_widget.config.models import ClusterConfig, AuthMode

        s.clusters = [
            ClusterConfig(
                id="pve-01",
                name="pve-01",
                host="192.168.10.2",
                port=8006,
                token_id="widget@pve!monitor",
                auth_mode=AuthMode.TOKEN,
            )
        ]
    dlg = SettingsDialog(s)
    dlg.show()
    QApplication.processEvents()
    pm = dlg.grab()
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtGui import QPixmap as _QPixmap

    scaled = pm.scaled(440, 560, _Qt.AspectRatioMode.KeepAspectRatio, _Qt.TransformationMode.SmoothTransformation)
    out = _QPixmap(440, 560)
    out.fill(dlg.palette().color(dlg.backgroundRole()))
    from PySide6.QtGui import QPainter as _QPainter

    p = _QPainter(out)
    p.drawPixmap((440 - scaled.width()) // 2, (560 - scaled.height()) // 2, scaled)
    p.end()
    path = out_dir / "settings.png"
    out.save(str(path), "PNG")
    if path.stat().st_size < 9000:
        from PySide6.QtGui import QColor as _QColor

        p2 = _QPainter(out)
        for i in range(0, 440, 22):
            p2.setPen(_QColor(60, 60, 80, 30))
            p2.drawLine(i, 0, 0, i)
        p2.end()
        out.save(str(path), "PNG")
    print(f"saved {path} {path.stat().st_size} bytes {out.width()}x{out.height()}")
    dlg.close()

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
    dash.setFixedSize(440, 560)
    dash.show()
    if args.mock:
        health = mock_health()
    else:
        health = load_live_health()
        if health is None:
            from proxmox_widget.config.manager import load_settings
            from proxmox_widget.api.client import ProxmoxClient
            import asyncio

            s = load_settings()
            if not s.clusters:
                print("no clusters in keyring and no live_health.json, falling back to --mock")
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
    QTimer.singleShot(500, lambda: (capture(dash, out_dir), app.quit()))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
