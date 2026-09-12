import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pathlib
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from proxmox_widget.config.models import ClusterConfig, ClusterHealth, LxcContainer, QemuVm
from proxmox_widget.ui.tray import TrayManager


def _qapp():
    app = QApplication.instance() or QApplication([])
    return app


def _health():
    vms = [
        QemuVm(vmid=100, name="vm1", node="pve", status="running"),
        QemuVm(vmid=101, name="vm2", node="pve", status="stopped"),
    ]
    cts = [
        LxcContainer(vmid=200, name="ct1", node="pve", status="running"),
        LxcContainer(vmid=201, name="ct2", node="pve", status="stopped"),
    ]
    h1 = ClusterHealth(cluster_id="c1", cluster_name="lab1", online=True, vms=vms, containers=cts)
    # offline cluster
    h2 = ClusterHealth(
        cluster_id="c2", cluster_name="lab2", online=False, error="timeout", vms=[], containers=[]
    )
    return [h1, h2]


def _clusters():
    c1 = ClusterConfig(id="c1", name="lab1", host="10.0.0.1", port=8006, token_id="root@pam!t")
    c2 = ClusterConfig(id="c2", name="lab2", host="10.0.0.2", port=8006, token_id="root@pam!t")
    return [c1, c2]


def test_tooltip_sums_vms_and_cts():
    app = _qapp()
    tray_icon = QSystemTrayIcon()
    mgr = TrayManager(tray_icon)
    health = _health()
    mgr.update_from_health(health)
    tip = tray_icon.toolTip()
    # online 1/2, total = 2 vms +2 cts =4, running =1 vm +1 ct =2
    assert "1/2" in tip
    assert "2/4" in tip
    # ensure old buggy count (1/2 VMs only) not present as sole logic
    # total should be 4 not 2
    assert "4" in tip
    mgr.tray.hide()
    # cleanup
    tray_icon.hide()


def test_tooltip_online_only_sums():
    app = _qapp()
    tray_icon = QSystemTrayIcon()
    mgr = TrayManager(tray_icon)
    # only online clusters counted
    vms = [QemuVm(vmid=100, name="a", node="n", status="running")]
    cts = [LxcContainer(vmid=200, name="b", node="n", status="running")]
    h = ClusterHealth(cluster_id="c1", cluster_name="lab", online=True, vms=vms, containers=cts)
    mgr.update_from_health([h])
    tip = tray_icon.toolTip()
    assert "1/1" in tip
    assert "2/2" in tip


def test_rebuild_icons_uses_palette_for():
    app = _qapp()
    tray_icon = QSystemTrayIcon()
    mgr = TrayManager(tray_icon)
    # should have rebuild_icons method
    assert hasattr(mgr, "rebuild_icons")
    # call with both themes without error
    mgr.rebuild_icons("dark")
    app.processEvents()
    mgr.rebuild_icons("light")
    app.processEvents()
    mgr.rebuild_icons("system")
    app.processEvents()
    text = pathlib.Path("src/proxmox_widget/ui/tray.py").read_text(encoding="utf-8")
    assert "palette_for" in text
    assert "rebuild_icons" in text


def test_offline_dot_disabled_entry():
    app = _qapp()
    tray_icon = QSystemTrayIcon()
    mgr = TrayManager(tray_icon)
    clusters = _clusters()
    mgr.set_clusters(clusters)
    health = _health()
    mgr.update_from_health(health)
    app.processEvents()
    # open menu should have 2 actions (one per cluster)
    actions = mgr._open_menu.actions()
    # find offline one (c2)
    offline_actions = [a for a in actions if "lab2" in a.text()]
    assert len(offline_actions) == 1
    a = offline_actions[0]
    assert "●" in a.text()
    assert not a.isEnabled()
    assert "timeout" in a.toolTip()
    # online one enabled
    online = next(x for x in actions if "lab1" in x.text())
    assert online.isEnabled()
    assert "●" not in online.text()


def test_launcher_open_url_used():
    text = pathlib.Path("src/proxmox_widget/ui/tray.py").read_text(encoding="utf-8")
    assert "launcher.open_url" in text
    assert "webbrowser.open" not in text
    # verify runtime calls launcher.open_url
    app = _qapp()
    tray_icon = QSystemTrayIcon()
    mgr = TrayManager(tray_icon)
    c = ClusterConfig(id="c1", name="lab1", host="10.0.0.5", port=8006, token_id="root@pam!t")
    mgr.set_clusters([c])
    mgr.update_from_health(
        [ClusterHealth(cluster_id="c1", cluster_name="lab1", online=True, vms=[], containers=[])]
    )
    app.processEvents()
    actions = [a for a in mgr._open_menu.actions() if "lab1" in a.text()]
    assert actions
    with patch("proxmox_widget.ui.tray.launcher.open_url") as mock_open:
        # trigger action
        actions[0].trigger()
        mock_open.assert_called_once()
        assert "10.0.0.5" in mock_open.call_args[0][0]


def test_activated_handling_all_reasons():
    app = _qapp()
    tray_icon = QSystemTrayIcon()
    mgr = TrayManager(tray_icon)
    text = pathlib.Path("src/proxmox_widget/ui/tray.py").read_text(encoding="utf-8")
    # ensure handling for all four reasons
    assert "DoubleClick" in text
    assert "MiddleClick" in text
    assert "Context" in text
    assert "Trigger" in text
    for reason in (
        QSystemTrayIcon.ActivationReason.Trigger,
        QSystemTrayIcon.ActivationReason.DoubleClick,
        QSystemTrayIcon.ActivationReason.MiddleClick,
        QSystemTrayIcon.ActivationReason.Context,
    ):
        called = []
        mgr.show_dashboard.connect(lambda: called.append(1))
        mgr._on_activated(reason)
        assert called, f"reason {reason} did not emit show_dashboard"
        # disconnect
        try:
            mgr.show_dashboard.disconnect()
        except Exception:
            pass


def test_app_applies_theme_rebuilds_icons():
    text = pathlib.Path("src/proxmox_widget/app.py").read_text(encoding="utf-8")
    assert "rebuild_icons" in text
    assert "palette_for" in pathlib.Path("src/proxmox_widget/ui/tray.py").read_text(
        encoding="utf-8"
    )
