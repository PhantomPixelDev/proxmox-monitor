import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QPushButton

from proxmox_widget.config.models import ClusterHealth, LxcContainer, ProxmoxNode, QemuVm
from proxmox_widget.ui.dashboard import CTS, NODES, VMS, Dashboard


def _health_mixed():
    n1 = ProxmoxNode(
        node="pve", status="online", cpu=0.2, maxcpu=4, mem=4000000000, maxmem=16000000000
    )
    n2 = ProxmoxNode(
        node="pve2", status="online", cpu=0.3, maxcpu=4, mem=4000000000, maxmem=16000000000
    )
    vms = [
        QemuVm(
            vmid=100,
            name="alpha",
            node="pve",
            status="running",
            cpus=2,
            cpu=0.9,
            mem=1000000000,
            maxmem=2000000000,
            uptime=1000,
        ),
        QemuVm(
            vmid=101,
            name="beta",
            node="pve",
            status="running",
            cpus=2,
            cpu=0.2,
            mem=1000000000,
            maxmem=2000000000,
            uptime=5000,
        ),
        QemuVm(
            vmid=102,
            name="gamma",
            node="pve2",
            status="running",
            cpus=2,
            cpu=0.5,
            mem=1000000000,
            maxmem=2000000000,
            uptime=3000,
        ),
        QemuVm(
            vmid=103,
            name="delta",
            node="pve2",
            status="stopped",
            cpus=2,
            cpu=0.0,
            mem=0,
            maxmem=2000000000,
            uptime=0,
        ),
    ]
    cts = [
        LxcContainer(
            vmid=200,
            name="ct-alpha",
            node="pve",
            status="running",
            cpus=1,
            cpu=0.7,
            mem=512000000,
            maxmem=1 << 30,
            uptime=2000,
        ),
        LxcContainer(
            vmid=201,
            name="ct-beta",
            node="pve2",
            status="running",
            cpus=1,
            cpu=0.1,
            mem=512000000,
            maxmem=1 << 30,
            uptime=6000,
        ),
    ]
    return [
        ClusterHealth(
            cluster_id="c1",
            cluster_name="lab",
            online=True,
            nodes=[n1, n2],
            vms=vms,
            containers=cts,
        )
    ]


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def dash(qapp):
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()
    d = Dashboard()
    d.apply_theme("dark")
    d.show()
    qapp.processEvents()
    yield d
    for t in list(getattr(d, "_search_timers", {}).values()):
        try:
            t.stop()
        except Exception:
            pass
    d.close()
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()


def _card_names(dash: Dashboard, key: str) -> list[str]:
    pane = dash._panes[key]
    lay = pane.layout()
    names = []
    for i in range(lay.count()):
        w = lay.itemAt(i).widget()
        if w is not None and w.objectName() == "card":
            # title label has objectName cardTitle
            for lbl in w.findChildren(
                type(dash._panes[key].findChild(type(w.findChild(w.__class__, "cardHead"))))
            ):
                pass
            # simpler: search QLabel with objectName cardTitle
            from PySide6.QtWidgets import QLabel

            for lbl in w.findChildren(QLabel):
                if lbl.objectName() == "cardTitle":
                    names.append(lbl.text())
                    break
    return names


def test_filters_exist(dash, qapp):
    assert VMS in dash._type_filter
    assert VMS in dash._node_filter
    assert VMS in dash._sort_combo
    assert CTS in dash._type_filter
    assert CTS in dash._node_filter
    assert CTS in dash._sort_combo
    # node filter for NODES/storage also
    assert NODES in dash._node_filter
    for cb in (
        list(dash._type_filter.values())
        + list(dash._node_filter.values())
        + list(dash._sort_combo.values())
    ):
        assert isinstance(cb, QComboBox)


def test_type_filter_items(dash):
    cb = dash._type_filter[VMS]
    texts = [cb.itemText(i) for i in range(cb.count())]
    assert "All" in texts
    assert "VM" in texts
    assert "CT" in texts


def test_node_filter_contains_all_nodes(dash, qapp):
    dash.update_health(_health_mixed())
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    # trigger rebuild to refresh node list
    dash._refresh_node_filter(VMS)
    cb = dash._node_filter[VMS]
    texts = [cb.itemText(i) for i in range(cb.count())]
    assert "All nodes" in texts
    assert "pve" in texts
    assert "pve2" in texts


def test_sort_cpu_highest_first(dash, qapp):
    dash.update_health(_health_mixed())
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    cb = dash._sort_combo[VMS]
    idx = cb.findText("CPU")
    assert idx >= 0
    cb.setCurrentIndex(idx)
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    names = _card_names(dash, VMS)
    # alpha cpu 0.9 should be first when sorted by cpu descending
    assert names[0] == "alpha"
    assert names[1] == "gamma"
    assert "beta" in names


def test_sort_uptime(dash, qapp):
    dash.update_health(_health_mixed())
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    cb = dash._sort_combo[VMS]
    idx = cb.findText("Uptime")
    assert idx >= 0
    cb.setCurrentIndex(idx)
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    names = _card_names(dash, VMS)
    # beta uptime 5000 highest
    assert names[0] == "beta"


def test_sort_name_default(dash, qapp):
    dash.update_health(_health_mixed())
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    cb = dash._sort_combo[VMS]
    cb.setCurrentIndex(cb.findText("Name"))
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    names = _card_names(dash, VMS)
    # name order disregards cpu: alpha, beta, delta, gamma (stopped vs running? name sort uses running first)
    # our Name mode is (status != running, name.lower()) so running first alphabetically
    # running: alpha, beta, gamma ; stopped: delta -> expect alpha first
    assert names[0] == "alpha"


def test_node_filter_works(dash, qapp):
    dash.update_health(_health_mixed())
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    dash._refresh_node_filter(VMS)
    cb = dash._node_filter[VMS]
    idx = cb.findText("pve")
    assert idx >= 0
    cb.setCurrentIndex(idx)
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    # only pve nodes: alpha, beta
    assert dash._counts[VMS].text().startswith("2")
    names = _card_names(dash, VMS)
    assert set(names) == {"alpha", "beta"}
    # switch to pve2
    cb.setCurrentIndex(cb.findText("pve2"))
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    names2 = _card_names(dash, VMS)
    assert set(names2) == {"gamma", "delta"}


def test_empty_cta_emits_open_settings(dash, qapp):
    fired = []
    dash.open_settings.connect(lambda: fired.append(1))
    dash.update_health([])
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    # find CTA button in any pane
    found = None
    for key in dash._panes:
        pane = dash._panes[key]
        for btn in pane.findChildren(QPushButton):
            if btn.objectName() == "emptyCta" or btn.text() == "Add cluster in Settings":
                found = btn
                break
        if found:
            break
    assert found is not None, "empty CTA button not found when health empty"
    assert found.text() == "Add cluster in Settings"
    found.click()
    qapp.processEvents()
    assert fired == [1]


def test_matches_intact(dash):
    assert Dashboard._matches("", "anything") is True
    assert Dashboard._matches("alpha", "alpha", 100, "pve") is True
    assert Dashboard._matches("pve", "vm", "pve") is True
    assert Dashboard._matches("nomatch", "alpha") is False


def test_persistence_via_qsettings(dash, qapp):
    dash._type_filter[VMS].setCurrentText("CT")
    dash._sort_combo[VMS].setCurrentText("CPU")
    dash._running_only[VMS].setChecked(True)
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    dash._qsettings.sync()
    QSettings("PhantomPixelDev", "ProxmoxWidget").sync()
    qapp.processEvents()
    QTest.qWait(20)
    qapp.processEvents()
    s = QSettings("PhantomPixelDev", "ProxmoxWidget")
    s.sync()
    type_val = s.value("dashboard/type_vms")
    if type_val is None:
        type_val = s.value("dashboard/type_VMS")
    sort_val = s.value("dashboard/sort_vms")
    if sort_val is None:
        sort_val = s.value("dashboard/sort_VMS")
    assert type_val == "CT"
    assert sort_val == "CPU"
    d2 = Dashboard()
    d2.apply_theme("dark")
    d2.show()
    qapp.processEvents()
    assert d2._type_filter[VMS].currentText() == "CT"
    assert d2._sort_combo[VMS].currentText() == "CPU"
    assert d2._running_only[VMS].isChecked() is True
    d2.close()
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()
    QSettings("PhantomPixelDev", "ProxmoxWidget").sync()


def test_type_filter_filters_guests(dash, qapp):
    # VMS tab with type CT should show 0 (since VMS only shows VMs)
    dash.update_health(_health_mixed())
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    dash._type_filter[VMS].setCurrentText("CT")
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    assert dash._counts[VMS].text().startswith("0")
    dash._type_filter[VMS].setCurrentText("All")
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    assert dash._counts[VMS].text() != "0/4"
