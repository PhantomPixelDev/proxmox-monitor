import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame

from proxmox_widget.config.models import ClusterHealth, LxcContainer, ProxmoxNode, QemuVm
from proxmox_widget.ui.dashboard import VMS, Dashboard


def _health_synthetic(vm_count: int = 200, ct_count: int = 0, cpu_jitter: float = 0.3) -> list[ClusterHealth]:
    node = ProxmoxNode(
        node="pve",
        status="online",
        cpu=0.3,
        maxcpu=8,
        mem=4_000_000_000,
        maxmem=16_000_000_000,
        disk=100_000_000_000,
        maxdisk=500_000_000_000,
    )
    vms = [
        QemuVm(
            vmid=100 + i,
            name=f"vm-{i:03d}",
            node="pve",
            status="running",
            cpus=2,
            cpu=cpu_jitter + (i % 10) * 0.02,
            mem=1_000_000_000 + i * 1_000_000,
            maxmem=2_000_000_000,
            disk=0,
            maxdisk=0,
            uptime=10000,
        )
        for i in range(vm_count)
    ]
    cts = [
        LxcContainer(
            vmid=200 + i,
            name=f"ct-{i:03d}",
            node="pve",
            status="running",
            cpus=1,
            cpu=cpu_jitter,
            mem=512_000_000,
            maxmem=1 << 30,
            disk=500_000_000,
            maxdisk=2_000_000_000,
            uptime=5000,
        )
        for i in range(ct_count)
    ]
    return [
        ClusterHealth(
            cluster_id="c1",
            cluster_name="lab",
            online=True,
            nodes=[node],
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


def _card_count(dash: Dashboard, key: str) -> int:
    pane = dash._panes[key]
    lay = pane.layout()
    assert lay is not None
    cnt = 0
    for i in range(lay.count()):
        w = lay.itemAt(i).widget()
        if isinstance(w, QFrame) and w.objectName() == "card":
            cnt += 1
    return cnt


def test_guest_key_format(dash):
    assert dash._guest_key("c1", 100, False) == "c1:100:vm"
    assert dash._guest_key("c1", 100, True) == "c1:100:ct"
    assert dash._guest_key("my-cluster", 999, False) == "my-cluster:999:vm"


def test_widget_count_stable_on_metrics_update(dash, qapp):
    dash.update_health(_health_synthetic(200, 0, 0.3))
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    assert VMS in dash._card_cache
    assert len(dash._card_cache[VMS]) == 200
    cnt_before = _card_count(dash, VMS)
    assert cnt_before == 200
    ids_before = {k: id(w) for k, w in dash._card_cache[VMS].items()}

    dash.update_health(_health_synthetic(200, 0, 0.55))
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()

    cnt_after = _card_count(dash, VMS)
    assert cnt_after == 200
    assert len(dash._card_cache[VMS]) == 200
    ids_after = {k: id(w) for k, w in dash._card_cache[VMS].items()}
    assert ids_before == ids_after


def test_update_metrics_changes_bars(dash, qapp):
    dash.update_health(_health_synthetic(5, 0, 0.2))
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    key = "c1:100:vm"
    card = dash._card_cache[VMS][key]
    from PySide6.QtWidgets import QProgressBar

    bars_before = [b.value() for b in card.findChildren(QProgressBar) if b.objectName() != "busy"]
    assert bars_before

    dash.update_health(_health_synthetic(5, 0, 0.9))
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    card2 = dash._card_cache[VMS][key]
    assert card is card2
    bars_after = [b.value() for b in card2.findChildren(QProgressBar) if b.objectName() != "busy"]
    assert bars_after != bars_before
    assert bars_after[0] == 90


def test_diff_create_delete_only_added_removed(dash, qapp):
    dash.update_health(_health_synthetic(200, 0, 0.3))
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    before = _card_count(dash, VMS)
    assert before == 200

    health2 = _health_synthetic(200, 0, 0.3)
    health2[0].vms = health2[0].vms[5:]
    extra = [
        QemuVm(vmid=400 + i, name=f"vm-extra-{i}", node="pve", status="running", cpus=2, cpu=0.5, mem=1_000_000_000, maxmem=2_000_000_000, uptime=1000)
        for i in range(5)
    ]
    health2[0].vms.extend(extra)
    dash.update_health(health2)
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    after = _card_count(dash, VMS)
    assert after == 200
    assert "c1:100:vm" not in dash._card_cache[VMS]
    assert "c1:400:vm" in dash._card_cache[VMS]


def test_fallback_on_large_key_mismatch(dash, qapp):
    dash.update_health(_health_synthetic(200, 0, 0.3))
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    assert len(dash._card_cache[VMS]) == 200
    old_ids = {k: id(w) for k, w in dash._card_cache[VMS].items()}

    dash.update_health(_health_synthetic(40, 0, 0.3))
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    assert len(dash._card_cache[VMS]) == 40
    assert _card_count(dash, VMS) == 40
    new_ids = {k: id(w) for k, w in dash._card_cache[VMS].items()}
    overlap = set(old_ids.keys()) & set(new_ids.keys())
    for k in overlap:
        assert old_ids[k] != new_ids[k]

    dash.update_health(_health_synthetic(200, 0, 0.3))
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    assert len(dash._card_cache[VMS]) == 200
    assert _card_count(dash, VMS) == 200


def test_p95_under_16ms_synthetic_200(dash, qapp):
    dash.update_health(_health_synthetic(200, 0, 0.3))
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()

    timings: list[float] = []
    for i in range(30):
        jitter = 0.300 + (i % 5) * 0.0015
        h = _health_synthetic(200, 0, jitter)
        dash._health = h
        t0 = time.perf_counter()
        dash._rebuild(VMS)
        t1 = time.perf_counter()
        timings.append((t1 - t0) * 1000)
        qapp.processEvents()

    timings.sort()
    p95_idx = int(len(timings) * 0.95)
    p95 = timings[p95_idx]
    import sys

    threshold = 16 if sys.platform != "win32" else 32
    assert p95 < threshold, f"p95 {p95:.2f}ms exceeds {threshold}ms, timings {timings[:5]} .. {timings[-5:]}"


def test_matches_query_unchanged(dash, qapp):
    dash.update_health(_health_synthetic(12, 0, 0.3))
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    assert Dashboard._matches("", "anything") is True
    assert Dashboard._matches("vm-001", "vm-001", 101) is True
    assert Dashboard._matches("pve", "vm-001", "pve") is True
    assert Dashboard._matches("nomatch", "vm-001") is False


def test_clear_remains_fallback_helper(dash, qapp):
    dash.update_health(_health_synthetic(10, 0, 0.3))
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    assert _card_count(dash, VMS) == 10
    lay = dash._clear(VMS)
    qapp.processEvents()
    assert _card_count(dash, VMS) == 0
    assert VMS not in dash._card_cache or len(dash._card_cache[VMS]) == 0
    assert lay.count() >= 1
