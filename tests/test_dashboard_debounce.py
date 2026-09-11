import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock

import pytest
from PySide6.QtTest import QTest

from proxmox_widget.config.models import ClusterHealth, LxcContainer, ProxmoxNode, QemuVm
from proxmox_widget.ui.dashboard import VMS, Dashboard


def _health(vm_count: int = 12) -> list[ClusterHealth]:
    node = ProxmoxNode(
        node="pve", status="online", cpu=0.3, maxcpu=4, mem=4_000_000_000, maxmem=16_000_000_000
    )
    vms = [
        QemuVm(
            vmid=100 + i,
            name=f"vm-{i:02d}",
            node="pve",
            status="running" if i % 2 else "stopped",
            cpus=2,
            maxmem=2_000_000_000,
        )
        for i in range(vm_count)
    ]
    cts = [
        LxcContainer(vmid=200, name="docker", node="pve", status="running", cpus=1, maxmem=1 << 30)
    ]
    return [
        ClusterHealth(
            cluster_id="c1", cluster_name="lab", online=True, nodes=[node], vms=vms, containers=cts
        )
    ]


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def dash(qapp):
    d = Dashboard()
    d.apply_theme("dark")
    d.show()
    d.update_health(_health())
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    yield d
    for t in list(getattr(d, "_search_timers", {}).values()):
        try:
            t.stop()
        except Exception:
            pass
    d.close()


def test_typing_10_chars_at_20ms_results_le2_rebuilds(dash, qapp):
    edit = dash._search[VMS]
    edit.clear()
    qapp.processEvents()
    QTest.qWait(200)
    qapp.processEvents()

    original = dash._rebuild
    mock = MagicMock(side_effect=original)
    dash._rebuild = mock
    mock.reset_mock()

    for i in range(10):
        edit.setText("a" * (i + 1))
        QTest.qWait(20)
        qapp.processEvents()

    assert mock.call_count <= 1, f"debounce should suppress intermediate rebuilds, got {mock.call_count}"

    QTest.qWait(250)
    qapp.processEvents()

    assert mock.call_count <= 2, f"typing 10 chars at 20ms should result <=2 rebuilds, got {mock.call_count}"
    assert mock.call_count >= 1, "at least one debounced rebuild should fire"

    dash._rebuild = original


def test_fast_clear_rebuilds_once(dash, qapp):
    edit = dash._search[VMS]
    edit.setText("hello")
    qapp.processEvents()
    QTest.qWait(250)
    qapp.processEvents()

    original = dash._rebuild
    mock = MagicMock(side_effect=original)
    dash._rebuild = mock
    mock.reset_mock()

    edit.setText("hellox")
    QTest.qWait(20)
    qapp.processEvents()
    edit.clear()
    qapp.processEvents()

    QTest.qWait(250)
    qapp.processEvents()

    assert mock.call_count == 1, f"fast clear should coalesce to one rebuild, got {mock.call_count}"

    dash._rebuild = original


def test_running_toggle_not_debounced(dash, qapp):
    btn = dash._running_only[VMS]
    if btn.isChecked():
        btn.setChecked(False)
        qapp.processEvents()
        QTest.qWait(50)

    original = dash._rebuild
    mock = MagicMock(side_effect=original)
    dash._rebuild = mock
    mock.reset_mock()

    btn.setChecked(True)
    qapp.processEvents()

    assert mock.call_count == 1, f"Running toggle should rebuild immediately, got {mock.call_count}"

    btn.setChecked(False)
    qapp.processEvents()
    assert mock.call_count == 2, f"Running toggle off should rebuild immediately, got {mock.call_count}"

    dash._rebuild = original


def test_search_timer_cancel_prior(dash, qapp):
    edit = dash._search[VMS]
    edit.clear()
    qapp.processEvents()
    QTest.qWait(200)
    qapp.processEvents()

    assert hasattr(dash, "_search_timers") or hasattr(dash, "_search_debounce") or hasattr(dash, "_debounce")
    assert VMS in dash._search

    original = dash._rebuild
    mock = MagicMock(side_effect=original)
    dash._rebuild = mock
    mock.reset_mock()

    edit.setText("a")
    qapp.processEvents()
    timer = dash._search_timers.get(VMS) or dash._search_debounce.get(VMS) or dash._debounce.get(VMS)
    assert timer is not None
    assert timer.isActive()

    edit.setText("ab")
    qapp.processEvents()
    assert timer.isActive()
    assert mock.call_count == 0

    QTest.qWait(250)
    qapp.processEvents()
    assert mock.call_count == 1

    dash._rebuild = original
