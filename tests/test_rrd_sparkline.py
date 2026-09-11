import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pathlib

import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

from proxmox_widget.api.client import ProxmoxClient
from proxmox_widget.config.models import AuthMode, ClusterConfig, ClusterHealth, QemuVm
from proxmox_widget.ui.dashboard import Dashboard, SparklineWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _cluster():
    return ClusterConfig(id="pve", name="PVE", host="1.2.3.4", token_id="root@pam!t", auth_mode=AuthMode.TOKEN)


@pytest.mark.asyncio
async def test_fetch_rrddata_24_points(monkeypatch):
    c = _cluster()
    client = ProxmoxClient(c, secret="s")
    called = {}

    async def fake_get(path):
        called["path"] = path
        assert "rrddata" in path
        assert "timeframe=hour" in path
        assert "/nodes/pve/qemu/100/rrddata" in path
        return [{"cpu": i / 100.0} for i in range(24)]

    monkeypatch.setattr(client, "_get", fake_get)
    points = await client.fetch_rrddata("pve", 100)
    assert len(points) == 24
    assert called["path"] == "/nodes/pve/qemu/100/rrddata?timeframe=hour"
    assert client._rrd_cache[("pve", 100, "hour")] == points


@pytest.mark.asyncio
async def test_fetch_rrddata_truncates_to_24(monkeypatch):
    c = _cluster()
    client = ProxmoxClient(c, secret="s")

    async def fake_get(path):
        return [{"cpu": i / 100.0} for i in range(50)]

    monkeypatch.setattr(client, "_get", fake_get)
    points = await client.fetch_rrddata("pve", 101)
    assert len(points) == 24
    assert points[0] == pytest.approx(26.0)


@pytest.mark.asyncio
async def test_fetch_rrddata_handles_empty_and_error(monkeypatch):
    c = _cluster()
    client = ProxmoxClient(c, secret="s")

    async def fake_get_ok(path):
        return []

    monkeypatch.setattr(client, "_get", fake_get_ok)
    points = await client.fetch_rrddata("pve", 102)
    assert points == []

    async def fake_get_err(path):
        raise RuntimeError("offline")

    monkeypatch.setattr(client, "_get", fake_get_err)
    points2 = await client.fetch_rrddata("pve", 999)
    assert points2 == []


@pytest.mark.asyncio
async def test_fetch_rrddata_non_list_returns_empty(monkeypatch):
    c = _cluster()
    client = ProxmoxClient(c, secret="s")

    async def fake_get(path):
        return {"cpu": 0.5}

    monkeypatch.setattr(client, "_get", fake_get)
    points = await client.fetch_rrddata("pve", 103)
    assert points == []


@pytest.mark.asyncio
async def test_fetch_rrddata_cache_in_memory(monkeypatch):
    c = _cluster()
    client = ProxmoxClient(c, secret="s")
    assert hasattr(client, "_rrd_cache")
    assert isinstance(client._rrd_cache, dict)

    async def fake_get(path):
        return [{"cpu": 0.5} for _ in range(24)]

    monkeypatch.setattr(client, "_get", fake_get)
    await client.fetch_rrddata("pve", 104)
    assert ("pve", 104, "hour") in client._rrd_cache
    assert len(client._rrd_cache[("pve", 104, "hour")]) == 24


def test_sparkline_sizehint(qapp):
    w = SparklineWidget(points=[10, 20, 30])
    assert w.sizeHint() == QSize(60, 20)
    assert w.minimumSize() == QSize(60, 20) or w.minimumWidth() == 60


def test_sparkline_paint_empty_and_single(qapp):
    w = SparklineWidget(points=[])
    w.resize(60, 20)
    w.show()
    w.repaint()
    qapp.processEvents()
    w2 = SparklineWidget(points=[50.0])
    w2.resize(60, 20)
    w2.show()
    w2.repaint()
    qapp.processEvents()
    w2.set_points([10, 90, 50, 30])
    assert w2._points == [10, 90, 50, 30]


def test_sparkline_draws_polyline(qapp):
    w = SparklineWidget(points=[float(i) for i in range(24)])
    w.resize(60, 20)
    w.show()
    qapp.processEvents()
    pix = w.grab()
    assert not pix.isNull()
    assert pix.width() >= 60
    w.deleteLater()


def test_guest_card_has_sparkline_when_running(qapp):
    dash = Dashboard()
    vm_running = QemuVm(vmid=100, name="web", node="pve", status="running", cpus=2, cpu=0.5, mem=512, maxmem=1024, uptime=100)
    vm_stopped = QemuVm(vmid=101, name="db", node="pve", status="stopped", cpus=2, cpu=0.0, mem=0, maxmem=1024, uptime=0)
    health = ClusterHealth(cluster_id="pve", cluster_name="PVE", online=True, nodes=[], vms=[vm_running, vm_stopped], containers=[], storages=[])
    dash.update_health([health])
    qapp.processEvents()
    vms_pane = dash._panes["vms"]
    cards = vms_pane.findChildren(SparklineWidget)
    assert len(cards) >= 1
    from PySide6.QtWidgets import QFrame

    all_cards = [c for c in vms_pane.findChildren(QFrame) if c.objectName() == "card"]
    assert len(all_cards) == 2
    spark_counts = sum(1 for c in all_cards if c.findChild(SparklineWidget) is not None)
    assert spark_counts == 1
    stopped_cards = [c for c in all_cards if c.findChild(SparklineWidget) is None]
    assert len(stopped_cards) == 1


def test_no_sqlite3_import():
    src = pathlib.Path("src")
    for p in src.rglob("*.py"):
        text = p.read_text(encoding="utf-8", errors="ignore")
        assert "sqlite3" not in text, f"sqlite3 found in {p}"
        assert "import sqlite" not in text
