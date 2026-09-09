"""Capture ProxmoxWidget screenshots for the README and the docs site.

Runs on a real desktop platform (not offscreen) because the offscreen plugin has
no font database on Windows and every glyph comes out as a tofu box. Nothing is
shown to the user: widgets are grabbed straight to a pixmap, so no event loop and
no visible window.

    python scripts/capture_screenshots.py --mock     # fake data, no PVE needed
    python scripts/capture_screenshots.py            # docs/live_health.json, else live API

Output: docs/screenshots/*.png at 2x for crisp HiDPI rendering on the site.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

# 2x so the PNGs stay sharp when the site renders them at CSS width.
os.environ.setdefault("QT_SCALE_FACTOR", "2")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from proxmox_widget.config.models import (  # noqa: E402
    ClusterHealth,
    LxcContainer,
    ProxmoxNode,
    QemuVm,
    StorageStatus,
)
from proxmox_widget.ui.dashboard import CTS, NODES, OVERVIEW, STORAGE, VMS, Dashboard  # noqa: E402

TAB_INDEX = {OVERVIEW: 0, NODES: 1, VMS: 2, CTS: 3, STORAGE: 4}
SHOTS = [
    ("dashboard", OVERVIEW),
    ("nodes", NODES),
    ("vms", VMS),
    ("containers", CTS),
    ("storage", STORAGE),
]


def mock_health() -> list[ClusterHealth]:
    nodes = [
        ProxmoxNode(
            node="pve",
            status="online",
            cpu=0.38,
            maxcpu=4,
            mem=4_200_000_000,
            maxmem=16_650_981_376,
            disk=31_000_000_000,
            maxdisk=100_861_726_720,
            uptime=14 * 86400 + 7 * 3600,
        ),
        ProxmoxNode(
            node="pve-2",
            status="online",
            cpu=0.12,
            maxcpu=8,
            mem=9_100_000_000,
            maxmem=33_301_962_752,
            disk=58_000_000_000,
            maxdisk=201_723_453_440,
            uptime=6 * 86400 + 2 * 3600,
        ),
    ]
    vms = [
        QemuVm(
            vmid=100, name="parrot-001", node="pve", status="stopped", cpus=4, maxmem=8_438_939_648
        ),
        QemuVm(
            vmid=101, name="portfolio", node="pve", status="stopped", cpus=4, maxmem=8_438_939_648
        ),
        QemuVm(
            vmid=112,
            name="win10",
            node="pve",
            status="running",
            cpus=4,
            cpu=0.42,
            mem=2_100_000_000,
            maxmem=8_489_271_296,
            uptime=3 * 86400 + 5 * 3600,
        ),
        QemuVm(
            vmid=118,
            name="ubuntu-server",
            node="pve-2",
            status="running",
            cpus=2,
            cpu=0.11,
            mem=1_400_000_000,
            maxmem=4_294_967_296,
            uptime=9 * 86400,
        ),
        QemuVm(
            vmid=122,
            name="build-runner",
            node="pve-2",
            status="stopped",
            cpus=4,
            maxmem=8_388_608_000,
        ),
    ]
    cts = [
        LxcContainer(
            vmid=107,
            name="docker",
            node="pve",
            status="running",
            cpus=2,
            cpu=0.18,
            mem=690_794_496,
            maxmem=4_294_967_296,
            disk=6_195_388_416,
            maxdisk=52_521_566_208,
            uptime=3600 * 40,
        ),
        LxcContainer(
            vmid=150,
            name="changeproof-test",
            node="pve",
            status="running",
            cpus=1,
            cpu=0.05,
            mem=31_584_256,
            maxmem=1_073_741_824,
            disk=739_733_504,
            maxdisk=8_350_298_112,
            uptime=1282,
        ),
        LxcContainer(
            vmid=161, name="pihole", node="pve-2", status="stopped", cpus=1, maxmem=536_870_912
        ),
    ]
    stor = [
        StorageStatus(
            storage="local",
            node="pve",
            type="dir",
            status="available",
            total=100_861_726_720,
            used=31_151_751_168,
            avail=69_709_975_552,
            enabled=True,
        ),
        StorageStatus(
            storage="local-lvm",
            node="pve",
            type="lvmthin",
            status="available",
            total=875_485_462_528,
            used=149_007_625_722,
            avail=726_477_836_806,
            enabled=True,
        ),
        StorageStatus(
            storage="backup-nas",
            node="pve",
            type="nfs",
            status="available",
            total=4_000_787_030_016,
            used=3_320_653_099_827,
            avail=680_133_930_189,
            enabled=True,
            shared=True,
        ),
    ]
    return [
        ClusterHealth(
            cluster_id="pve-192-168-10-2",
            cluster_name="pve-01",
            online=True,
            nodes=nodes,
            vms=vms,
            containers=cts,
            storages=stor,
        )
    ]


def load_live_health() -> list[ClusterHealth] | None:
    p = ROOT / "docs" / "live_health.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return [ClusterHealth.model_validate(data)]
        if isinstance(data, list):
            return [ClusterHealth.model_validate(x) for x in data]
    except Exception as e:
        print(f"failed to load live_health.json: {e}")
    return None


def fit_height(dash, key: str) -> None:
    """Size the popup to its content so shots do not end in dead space."""
    pane = dash._panes[key]
    viewport = pane.parentWidget()
    chrome = dash.height() - viewport.height()
    needed = pane.sizeHint().height() + chrome + 4
    dash.resize(dash.width(), max(620, min(880, needed)))
    QApplication.processEvents()


def grab(widget, path: pathlib.Path) -> None:
    QApplication.processEvents()
    pm = widget.grab()
    pm.save(str(path), "PNG")
    print(f"saved {path.name}  {pm.width()}x{pm.height()}  {path.stat().st_size} bytes")


def capture_settings(out_dir: pathlib.Path, theme: str) -> None:
    from proxmox_widget.config.models import AppSettings, AuthMode, ClusterConfig
    from proxmox_widget.ui.settings_dialog import SettingsDialog
    from proxmox_widget.ui.themes import qss_for

    # never the real saved settings — this image is published
    s = AppSettings(
        clusters=[
            ClusterConfig(
                id="pve-home",
                name="Home Lab",
                host="proxmox.lan",
                port=8006,
                token_id="widget@pve!monitor",
                auth_mode=AuthMode.TOKEN,
            )
        ]
    )
    dlg = SettingsDialog(s)
    dlg.setStyleSheet(qss_for(theme))
    dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    dlg.show()
    QApplication.processEvents()
    grab(dlg, out_dir / "settings.png")
    dlg.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="use fake data, no PVE needed")
    ap.add_argument("--theme", default="dark", choices=["dark", "light"])
    ap.add_argument("--out", default="docs/screenshots")
    args = ap.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)

    health = mock_health() if args.mock else (load_live_health() or mock_health())

    dash = Dashboard()
    dash.apply_theme(args.theme)
    # render into a pixmap without ever appearing on screen
    dash.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    dash.show()
    dash.update_health(health)
    dash.resize(dash.width(), 760)
    QApplication.processEvents()

    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, key in SHOTS:
        dash.tabs.setCurrentIndex(TAB_INDEX[key])
        QApplication.processEvents()
        fit_height(dash, key)
        grab(dash, out_dir / f"{name}.png")

    # search in action, for the docs gallery
    dash.tabs.setCurrentIndex(TAB_INDEX[VMS])
    dash._search[VMS].setText("win")
    QApplication.processEvents()
    fit_height(dash, VMS)
    grab(dash, out_dir / "search.png")
    dash._search[VMS].clear()

    capture_settings(out_dir, args.theme)
    dash.close()
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
