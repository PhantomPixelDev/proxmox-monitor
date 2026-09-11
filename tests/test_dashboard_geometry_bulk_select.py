import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pathlib
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QApplication

from proxmox_widget.config.models import ClusterHealth, ProxmoxNode, QemuVm
from proxmox_widget.ui.dashboard import Dashboard


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


def _health(n=5):
    node = ProxmoxNode(node="pve", status="online", cpu=0.2, maxcpu=4, mem=4000000000, maxmem=16000000000)
    vms = [QemuVm(vmid=100 + i, name=f"vm-{i}", node="pve", status="running", cpus=2, cpu=0.5, mem=1000000000, maxmem=2000000000) for i in range(n)]
    return [ClusterHealth(cluster_id="c1", cluster_name="lab", online=True, nodes=[node], vms=vms, containers=[])]


def test_window_flags_tool_not_popup(dash):
    flags = dash.windowFlags()
    assert flags & Qt.WindowType.Tool
    text = pathlib.Path("src/proxmox_widget/ui/dashboard.py").read_text()
    assert "Qt.WindowType.Tool" in text
    assert "setMinimumWidth(468)" in text
    assert "setFixedWidth(468)" not in text
    assert flags & Qt.WindowType.FramelessWindowHint
    assert dash.minimumWidth() == 468
    assert dash.maximumWidth() > 468


def test_show_dashboard_uses_screenAt_and_dpi(qapp):
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()
    app = QApplication.instance() or QApplication([])
    import proxmox_widget.config.manager as mgr
    from proxmox_widget.config.models import AppSettings

    orig = mgr.load_settings
    try:
        mgr.load_settings = lambda: AppSettings()
        from proxmox_widget.app import ProxmoxWidgetApp

        widget_app = ProxmoxWidgetApp(app)
        fake_screen = MagicMock()
        fake_screen.devicePixelRatio.return_value = 2.0
        fake_screen.availableGeometry.return_value = QGuiApplication.primaryScreen().availableGeometry()
        with (
            patch.object(QGuiApplication, "screenAt", return_value=fake_screen) as mock_screenAt,
            patch.object(QCursor, "pos", return_value=QPoint(400, 400)),
        ):
            widget_app.show_dashboard()
            qapp.processEvents()
            mock_screenAt.assert_called()
            fake_screen.devicePixelRatio.assert_called()
        widget_app.dashboard.close()
    finally:
        mgr.load_settings = orig
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()
    t = pathlib.Path("src/proxmox_widget/app.py").read_text()
    assert "screenAt" in t
    assert "devicePixelRatio" in t
    assert "primaryScreen" in t


def test_bulk_selection_ctrl_3(dash, qapp):
    dash.update_health(_health(5))
    qapp.processEvents()
    dash.clear_selection()
    for i in range(3):
        dash._on_card_clicked("c1", 100 + i, False, Qt.KeyboardModifier.ControlModifier, Qt.MouseButton.LeftButton)
    assert len(dash._selected) == 3
    assert ("c1", 100, False) in dash._selected
    assert dash.is_selected("c1", 101, False)


def test_bulk_selection_shift(dash, qapp):
    dash.update_health(_health(5))
    qapp.processEvents()
    dash.clear_selection()
    dash._on_card_clicked("c1", 100, False, Qt.KeyboardModifier.NoModifier, Qt.MouseButton.LeftButton)
    dash._on_card_clicked("c1", 102, False, Qt.KeyboardModifier.ShiftModifier, Qt.MouseButton.LeftButton)
    assert len(dash._selected) == 3
    assert ("c1", 101, False) in dash._selected


def test_bulk_selection_select_all(dash, qapp):
    dash.update_health(_health(5))
    qapp.processEvents()
    dash.clear_selection()
    dash.select_all()
    assert len(dash._selected) == 5
    dash.clear_selection()
    event = MagicMock()
    event.modifiers.return_value = Qt.KeyboardModifier.ControlModifier
    event.key.return_value = Qt.Key.Key_A
    event.accept = MagicMock()
    dash.keyPressEvent(event)
    assert len(dash._selected) == 5


def test_geometry_persists(qapp):
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()
    d = Dashboard()
    d.show()
    qapp.processEvents()
    d.resize(500, 620)
    d.move(100, 100)
    qapp.processEvents()
    d.save_geometry()
    geo = QSettings("PhantomPixelDev", "ProxmoxWidget").value("dashboard/geometry")
    assert geo is not None
    assert not geo.isEmpty()
    d.close()
    d2 = Dashboard()
    d2.show()
    qapp.processEvents()
    assert d2.width() == 500
    assert d2.height() == 620
    assert abs(d2.pos().x() - 100) < 5
    assert abs(d2.pos().y() - 100) < 5
    d2.close()
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()


def test_no_sqlite3():
    for p in pathlib.Path("src").rglob("*.py"):
        assert "sqlite3" not in p.read_text(encoding="utf-8", errors="ignore")
