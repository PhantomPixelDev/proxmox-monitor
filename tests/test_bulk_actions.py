import asyncio
import os
import pathlib

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import concurrent.futures
from unittest.mock import patch

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from proxmox_widget.api.exceptions import ActionFailedError
from proxmox_widget.config.models import (
    AppSettings,
    ClusterConfig,
    ClusterHealth,
    ProxmoxNode,
    QemuVm,
)
from proxmox_widget.ui.dashboard import Dashboard


def _run_coro(coro):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(asyncio.run, coro)
        return fut.result()


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def dash(qapp):
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()
    d = Dashboard()
    d.apply_theme("dark")
    d.show()
    qapp.processEvents()
    yield d
    try:
        for t in list(getattr(d, "_search_timers", {}).values()):
            t.stop()
    except Exception:
        pass
    d.close()
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()


def _health(n=5, cid="c1"):
    node = ProxmoxNode(
        node="pve", status="online", cpu=0.2, maxcpu=4, mem=4_000_000_000, maxmem=16_000_000_000
    )
    vms = [
        QemuVm(
            vmid=100 + i,
            name=f"vm-{i}",
            node="pve",
            status="running",
            cpus=2,
            cpu=0.5,
            mem=1_000_000_000,
            maxmem=2_000_000_000,
        )
        for i in range(n)
    ]
    return [
        ClusterHealth(
            cluster_id=cid, cluster_name="lab", online=True, nodes=[node], vms=vms, containers=[]
        )
    ]


def test_bulk_toolbar_exists(dash, qapp):
    assert hasattr(dash, "_bulk_bar")
    assert hasattr(dash, "_bulk_select_all")
    assert dash._bulk_select_all.text() == "Select All"
    assert hasattr(dash, "_bulk_buttons")
    for act in ("start", "shutdown", "reboot", "stop"):
        assert act in dash._bulk_buttons
    # bulk buttons emit signal
    captured = []
    dash.bulk_action_requested.connect(lambda a: captured.append(a))
    dash._bulk_buttons["start"].click()
    qapp.processEvents()
    assert "start" in captured
    # SelectAll
    dash.update_health(_health(5))
    qapp.processEvents()
    dash.clear_selection()
    dash._bulk_select_all.click()
    qapp.processEvents()
    assert len(dash._selected) == 5
    # no sqlite3
    for p in pathlib.Path("src").rglob("*.py"):
        assert "sqlite3" not in p.read_text(encoding="utf-8", errors="ignore")


def test_bulk_no_migrate_snapshot_source():
    text = pathlib.Path("src/proxmox_widget/app.py").read_text()
    assert "_on_bulk_action" in text
    assert "asyncio.Semaphore(3)" in text
    assert "has_privilege" in text
    assert "VM.PowerMgmt" in text
    assert "get_task_status" in text
    low = text.lower()
    assert "migrate" in low
    assert "snapshot" in low
    assert "not allowed" in low


def test_bulk_concurrency_le3(qapp, dash):
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()
    import proxmox_widget.config.manager as mgr

    orig_load = mgr.load_settings
    try:
        mgr.load_settings = lambda: AppSettings(
            clusters=[ClusterConfig(id="c1", name="lab", host="pve.example.com", port=8006)]
        )
        from proxmox_widget.app import ProxmoxWidgetApp

        app = QApplication.instance() or QApplication([])
        w = ProxmoxWidgetApp(app)
        # use same dash
        w.dashboard = dash
        w._health = _health(5)
        dash.update_health(w._health)
        dash.clear_selection()
        dash.select_all()
        assert len(dash._selected) == 5

        counter = {"cur": 0, "max": 0}
        task_calls = []

        async def fake_vm_action(self, node, vmid, action, is_lxc=False):
            counter["cur"] += 1
            counter["max"] = max(counter["max"], counter["cur"])
            await asyncio.sleep(0.05)
            counter["cur"] -= 1
            task_calls.append(vmid)
            return f"UPID:pve:000:{vmid}"

        async def fake_get_task_status(self, node, upid):
            return "stopped"

        async def fake_has_privilege(self, name):
            return True

        banners = []
        orig_show = dash.show_message
        dash.show_message = lambda t, k="info", d=4000: banners.append((t, k))

        results = {}

        def fake_spawn(factory, on_done=None, on_error=None):
            async def _run():
                try:
                    res = await factory()
                    if on_done:
                        on_done(res)
                    results["res"] = res
                except Exception as e:
                    if on_error:
                        on_error(e)
                    results["err"] = e

            _run_coro(_run())

        w._spawn = fake_spawn  # type: ignore[assignment]

        with (
            patch("proxmox_widget.app.ProxmoxClient.vm_action", fake_vm_action),
            patch("proxmox_widget.app.ProxmoxClient.get_task_status", fake_get_task_status),
            patch("proxmox_widget.app.ProxmoxClient.has_privilege", fake_has_privilege),
        ):
            w._on_bulk_action("start")
            assert counter["max"] <= 3, f"max concurrency {counter['max']} exceeds 3"
            assert counter["max"] >= 1
            assert len(task_calls) == 5
            assert "res" in results
            assert "5/5 succeeded" in results["res"]
        dash.show_message = orig_show
        w.dashboard.close()
    finally:
        mgr.load_settings = orig_load
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()


def test_bulk_aggregate_3_of_5(qapp, dash):
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()
    import proxmox_widget.config.manager as mgr

    orig_load = mgr.load_settings
    try:
        mgr.load_settings = lambda: AppSettings(
            clusters=[ClusterConfig(id="c1", name="lab", host="pve.example.com", port=8006)]
        )
        from proxmox_widget.app import ProxmoxWidgetApp

        app = QApplication.instance() or QApplication([])
        w = ProxmoxWidgetApp(app)
        w.dashboard = dash
        w._health = _health(5)
        dash.update_health(w._health)
        dash.clear_selection()
        dash.select_all()

        async def fake_vm_action(self, node, vmid, action, is_lxc=False):
            if vmid in (103, 104):
                raise ActionFailedError(f"action {action} failed for {vmid}")
            return f"UPID:pve:{vmid}"

        async def fake_get_task_status(self, node, upid):
            return "stopped"

        async def fake_has_privilege(self, name):
            return True

        results = {}

        def fake_spawn(factory, on_done=None, on_error=None):
            async def _run():
                try:
                    res = await factory()
                    if on_done:
                        on_done(res)
                    results["res"] = res
                except Exception as e:
                    if on_error:
                        on_error(e)
                    results["err"] = e

            _run_coro(_run())

        w._spawn = fake_spawn  # type: ignore[assignment]

        banners = []
        orig_show = dash.show_message
        dash.show_message = lambda t, k="info", d=4000: banners.append(t)

        with (
            patch("proxmox_widget.app.ProxmoxClient.vm_action", fake_vm_action),
            patch("proxmox_widget.app.ProxmoxClient.get_task_status", fake_get_task_status),
            patch("proxmox_widget.app.ProxmoxClient.has_privilege", fake_has_privilege),
        ):
            w._on_bulk_action("start")
            assert "res" in results
            banner = results["res"]
            assert "3/5 succeeded" in banner
            assert "2x ActionFailed" in banner

        dash.show_message = orig_show
        w.dashboard.close()
    finally:
        mgr.load_settings = orig_load
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()


def test_bulk_privilege_gate_blocks(qapp, dash):
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()
    import proxmox_widget.config.manager as mgr

    orig_load = mgr.load_settings
    try:
        mgr.load_settings = lambda: AppSettings(
            clusters=[ClusterConfig(id="c1", name="lab", host="pve.example.com", port=8006)]
        )
        from proxmox_widget.app import ProxmoxWidgetApp

        app = QApplication.instance() or QApplication([])
        w = ProxmoxWidgetApp(app)
        w.dashboard = dash
        w._health = _health(3)
        dash.update_health(w._health)
        dash.clear_selection()
        dash.select_all()

        vm_called = []

        async def fake_vm_action(self, node, vmid, action, is_lxc=False):
            vm_called.append(vmid)
            return "UPID:x"

        async def fake_has_privilege(self, name):
            return False

        errors = []

        def fake_spawn(factory, on_done=None, on_error=None):
            async def _run():
                try:
                    res = await factory()
                    if on_done:
                        on_done(res)
                except Exception as e:
                    if on_error:
                        on_error(e)
                    errors.append(str(e))

            _run_coro(_run())

        w._spawn = fake_spawn  # type: ignore[assignment]

        with (
            patch("proxmox_widget.app.ProxmoxClient.vm_action", fake_vm_action),
            patch("proxmox_widget.app.ProxmoxClient.has_privilege", fake_has_privilege),
        ):
            w._on_bulk_action("start")
            assert len(vm_called) == 0, "vm_action should not be called when privilege missing"
            assert any("VM.PowerMgmt" in e for e in errors)

        w.dashboard.close()
    finally:
        mgr.load_settings = orig_load
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()


def test_bulk_migrate_snapshot_blocked(qapp, dash):
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()
    import proxmox_widget.config.manager as mgr

    orig_load = mgr.load_settings
    try:
        mgr.load_settings = lambda: AppSettings(
            clusters=[ClusterConfig(id="c1", name="lab", host="pve.example.com", port=8006)]
        )
        from proxmox_widget.app import ProxmoxWidgetApp

        app = QApplication.instance() or QApplication([])
        w = ProxmoxWidgetApp(app)
        w.dashboard = dash
        w._health = _health(2)
        dash.update_health(w._health)
        dash.clear_selection()
        dash.select_all()

        vm_called = []

        async def fake_vm_action(self, node, vmid, action, is_lxc=False):
            vm_called.append(vmid)
            return "UPID:x"

        banners = []
        dash.show_message = lambda t, k="info", d=4000: banners.append((t, k))

        w._spawn = lambda f, on_done=None, on_error=None: (_ for _ in ()).throw(
            AssertionError("should not spawn for blocked action")
        )

        with patch("proxmox_widget.app.ProxmoxClient.vm_action", fake_vm_action):
            w._on_bulk_action("migrate")
            assert len(vm_called) == 0
            assert any("not allowed" in t.lower() for t, _ in banners)
            banners.clear()
            w._on_bulk_action("snapshot")
            assert len(vm_called) == 0
            assert any("not allowed" in t.lower() for t, _ in banners)

        w.dashboard.close()
    finally:
        mgr.load_settings = orig_load
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()
