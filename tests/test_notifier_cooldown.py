import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from proxmox_widget.config.models import AppSettings, ClusterHealth, LxcContainer, QemuVm
from proxmox_widget.core.notifier import Notifier


def _qapp():
    return QApplication.instance() or QApplication([])


def _make_health(vms=None, cts=None, cid="c1", cname="lab1"):
    return ClusterHealth(
        cluster_id=cid,
        cluster_name=cname,
        online=True,
        vms=vms or [],
        containers=cts or [],
    )


def test_notifications_disabled_no_emissions():
    _qapp()
    settings = AppSettings(notifications_enabled=False)
    n = Notifier(settings=settings)
    emitted = []
    n.notification_requested.connect(lambda t, m: emitted.append((t, m)))
    # prime prev with running
    h1 = _make_health(vms=[QemuVm(vmid=100, name="vm100", node="pve", status="running")])
    n.check([h1])
    # transition to stopped should be suppressed
    h2 = _make_health(vms=[QemuVm(vmid=100, name="vm100", node="pve", status="stopped")])
    n.check([h2])
    assert emitted == []


def test_notifications_enabled_via_check_param():
    _qapp()
    n = Notifier()
    emitted = []
    n.notification_requested.connect(lambda t, m: emitted.append((t, m)))
    h1 = _make_health(vms=[QemuVm(vmid=100, name="vm100", node="pve", status="running")])
    n.check([h1], settings=AppSettings(notifications_enabled=False))
    h2 = _make_health(vms=[QemuVm(vmid=100, name="vm100", node="pve", status="stopped")])
    n.check([h2], settings=AppSettings(notifications_enabled=False))
    assert emitted == []
    # now enabled
    h3 = _make_health(vms=[QemuVm(vmid=100, name="vm100", node="pve", status="running")])
    n.check([h3], settings=True)
    h4 = _make_health(vms=[QemuVm(vmid=100, name="vm100", node="pve", status="stopped")])
    n.check([h4], settings=True)
    assert len(emitted) == 1


def test_same_vm_stopped_twice_within_5m_emits_once():
    _qapp()
    settings = AppSettings(notifications_enabled=True)
    n = Notifier(settings=settings)
    emitted = []
    n.notification_requested.connect(lambda t, m: emitted.append((t, m)))
    # mock time
    with patch("proxmox_widget.core.notifier.time.monotonic") as mock_time:
        mock_time.return_value = 1000.0
        h_run = _make_health(vms=[QemuVm(vmid=100, name="vm100", node="pve", status="running")])
        n.check([h_run])
        h_stop = _make_health(vms=[QemuVm(vmid=100, name="vm100", node="pve", status="stopped")])
        n.check([h_stop])
        assert len(emitted) == 1
        # flap: back to running (no notify for start)
        mock_time.return_value = 1100.0
        h_run2 = _make_health(vms=[QemuVm(vmid=100, name="vm100", node="pve", status="running")])
        n.check([h_run2])
        assert len(emitted) == 1
        # stopped again within 5min (1000+300 =1300 expiry) -> throttled
        mock_time.return_value = 1200.0
        h_stop2 = _make_health(vms=[QemuVm(vmid=100, name="vm100", node="pve", status="stopped")])
        n.check([h_stop2])
        assert len(emitted) == 1
        # after cooldown expires (5min + 1s after first =1301)
        mock_time.return_value = 1401.0
        h_run3 = _make_health(vms=[QemuVm(vmid=100, name="vm100", node="pve", status="running")])
        n.check([h_run3])
        h_stop3 = _make_health(vms=[QemuVm(vmid=100, name="vm100", node="pve", status="stopped")])
        n.check([h_stop3])
        assert len(emitted) == 2


def test_batch_4_stopped_emits_summary_one():
    _qapp()
    settings = AppSettings(notifications_enabled=True)
    n = Notifier(settings=settings)
    emitted = []
    n.notification_requested.connect(lambda t, m: emitted.append((t, m)))
    vms_run = [QemuVm(vmid=i, name=f"vm{i}", node="pve", status="running") for i in range(100, 104)]
    h1 = _make_health(vms=vms_run)
    n.check([h1])
    vms_stop = [
        QemuVm(vmid=i, name=f"vm{i}", node="pve", status="stopped") for i in range(100, 104)
    ]
    h2 = _make_health(vms=vms_stop)
    n.check([h2])
    assert len(emitted) == 1
    assert "4" in emitted[0][0] or "4" in emitted[0][1]
    txt = (emitted[0][0] + emitted[0][1]).lower()
    assert "stopped" in txt


def test_batch_three_or_less_not_summarized():
    _qapp()
    settings = AppSettings(notifications_enabled=True)
    n = Notifier(settings=settings)
    emitted = []
    n.notification_requested.connect(lambda t, m: emitted.append((t, m)))
    vms_run = [QemuVm(vmid=i, name=f"vm{i}", node="pve", status="running") for i in range(100, 103)]
    n.check([_make_health(vms=vms_run)])
    vms_stop = [
        QemuVm(vmid=i, name=f"vm{i}", node="pve", status="stopped") for i in range(100, 103)
    ]
    n.check([_make_health(vms=vms_stop)])
    assert len(emitted) == 3


def test_key_distinct_vm_vs_ct():
    _qapp()
    settings = AppSettings(notifications_enabled=True)
    n = Notifier(settings=settings)
    emitted = []
    n.notification_requested.connect(lambda t, m: emitted.append((t, m)))
    # prime both as running
    h1 = _make_health(
        vms=[QemuVm(vmid=100, name="vm100", node="pve", status="running")],
        cts=[LxcContainer(vmid=100, name="ct100", node="pve", status="running")],
    )
    n.check([h1])
    # both stop
    h2 = _make_health(
        vms=[QemuVm(vmid=100, name="vm100", node="pve", status="stopped")],
        cts=[LxcContainer(vmid=100, name="ct100", node="pve", status="stopped")],
    )
    n.check([h2])
    assert len(emitted) == 2
    # keys must be distinct internally
    assert "c1:vm:100" in n._prev_vms
    assert "c1:ct:100" in n._prev_vms
    assert n._cooldown.get("c1:vm:100") is not None
    assert n._cooldown.get("c1:ct:100") is not None


def test_tray_showMessage_when_supported():
    _qapp()
    settings = AppSettings(notifications_enabled=True)
    tray = MagicMock(spec=QSystemTrayIcon)
    tray.supportsMessages.return_value = True
    tray.showMessage = MagicMock()
    n = Notifier(tray=tray, settings=settings)
    emitted = []
    n.notification_requested.connect(lambda t, m: emitted.append((t, m)))
    h1 = _make_health(vms=[QemuVm(vmid=1, name="vm1", node="pve", status="running")])
    n.check([h1])
    h2 = _make_health(vms=[QemuVm(vmid=1, name="vm1", node="pve", status="stopped")])
    n.check([h2])
    assert tray.showMessage.called
    assert len(emitted) == 1


def test_banner_fallback_when_no_tray_support():
    _qapp()
    settings = AppSettings(notifications_enabled=True)
    tray = MagicMock(spec=QSystemTrayIcon)
    tray.supportsMessages.return_value = False
    tray.showMessage = MagicMock()
    n = Notifier(tray=tray, settings=settings)
    emitted = []
    n.notification_requested.connect(lambda t, m: emitted.append((t, m)))
    h1 = _make_health(vms=[QemuVm(vmid=2, name="vm2", node="pve", status="running")])
    n.check([h1])
    h2 = _make_health(vms=[QemuVm(vmid=2, name="vm2", node="pve", status="stopped")])
    n.check([h2])
    assert not tray.showMessage.called
    assert len(emitted) == 1


def test_app_wires_notifier_with_settings():
    text = open("src/proxmox_widget/app.py", encoding="utf-8").read()
    assert "Notifier(self.tray_icon" in text
    # must pass settings
    assert (
        "Notifier(self.tray_icon, self.settings)" in text
        or "Notifier(self.tray_icon, settings" in text
        or ("self.settings" in text and "Notifier" in text)
    )
    assert "showMessage" in text
    assert "supportsMessages" in text


def test_notifier_has_tray_ref_and_cooldown():
    text = open("src/proxmox_widget/core/notifier.py", encoding="utf-8").read()
    assert "notifications_enabled" in text
    assert "f\"{cid}:{'ct' if is_lxc else 'vm'}:{vmid}\"" in text
    assert "time.monotonic" in text
    assert "300" in text
    assert "supportsMessages" in text
    assert "showMessage" in text
    assert "batch" in text.lower() or ">3" in text


def test_no_spam_on_flapping_cooldown_stored():
    _qapp()
    settings = AppSettings(notifications_enabled=True)
    n = Notifier(settings=settings)
    with patch("proxmox_widget.core.notifier.time.monotonic", return_value=5000.0):
        h1 = _make_health(vms=[QemuVm(vmid=10, name="vm10", node="pve", status="running")])
        n.check([h1])
        h2 = _make_health(vms=[QemuVm(vmid=10, name="vm10", node="pve", status="stopped")])
        n.check([h2])
        key = "c1:vm:10"
        assert key in n._cooldown
        # monotonic +300 stored
        assert abs(n._cooldown[key] - 5300.0) < 1
