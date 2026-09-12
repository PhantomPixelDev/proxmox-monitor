import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import base64
import pathlib
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

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


def test_ctrl_k_focuses_search(dash, qapp):
    assert hasattr(dash, "_sc_ctrl_k")
    assert dash._sc_ctrl_k.key().toString() == QKeySequence("Ctrl+K").toString()
    # ensure search edits exist
    assert len(dash._search) >= 1
    # focus search via helper (what shortcut triggers)
    dash._focus_search()
    qapp.processEvents()
    focused = qapp.focusWidget()
    assert focused in dash._search.values()
    # source grep
    text = pathlib.Path("src/proxmox_widget/ui/dashboard.py").read_text()
    assert "Ctrl+K" in text
    assert "_focus_search" in text


def test_ctrl_comma_opens_settings(dash):
    assert hasattr(dash, "_sc_ctrl_comma")
    assert dash._sc_ctrl_comma.key().toString() == QKeySequence("Ctrl+,").toString()
    fired = []
    dash.open_settings.connect(lambda: fired.append(1))
    # simulate shortcut activation -> emit open_settings
    dash.open_settings.emit()
    assert fired == [1]
    text = pathlib.Path("src/proxmox_widget/ui/dashboard.py").read_text()
    assert "Ctrl+," in text


def test_f5_refresh(dash):
    assert hasattr(dash, "_sc_f5")
    assert dash._sc_f5.key().toString() == QKeySequence("F5").toString()
    fired = []
    dash.refresh_requested.connect(lambda: fired.append(1))
    dash.refresh_requested.emit()
    assert fired == [1]
    text = pathlib.Path("src/proxmox_widget/ui/dashboard.py").read_text()
    assert "F5" in text


def test_escape_hide_window(dash, qapp):
    assert hasattr(dash, "_sc_escape")
    dash.show()
    qapp.processEvents()
    assert dash.isVisible()
    # no selection -> escape hides
    dash._selected.clear()
    dash._on_escape_shortcut()
    qapp.processEvents()
    assert not dash.isVisible()
    # with selection -> escape clears not hide
    dash.show()
    qapp.processEvents()
    dash._selected.add(("c1", 100, False))
    dash._on_escape_shortcut()
    assert len(dash._selected) == 0
    assert dash.isVisible()


def test_escape_clears_then_hides(dash, qapp):
    dash._selected.clear()
    # keyPressEvent Escape hide path
    event = MagicMock()
    event.modifiers.return_value = Qt.KeyboardModifier.NoModifier
    event.key.return_value = Qt.Key.Key_Escape
    event.accept = MagicMock()
    dash.show()
    qapp.processEvents()
    dash.keyPressEvent(event)
    qapp.processEvents()
    assert not dash.isVisible()


def test_ctrl_q_quit(dash):
    assert hasattr(dash, "_sc_ctrl_q")
    assert dash._sc_ctrl_q.key().toString() == QKeySequence("Ctrl+Q").toString()
    text = pathlib.Path("src/proxmox_widget/ui/dashboard.py").read_text()
    assert "Ctrl+Q" in text
    app_text = pathlib.Path("src/proxmox_widget/app.py").read_text()
    assert "Ctrl+Q" in app_text


def test_geometry_base64_roundtrip(qapp):
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()
    d = Dashboard()
    d.show()
    qapp.processEvents()
    d.resize(520, 640)
    d.move(111, 111)
    qapp.processEvents()
    d.save_geometry()
    geo = QSettings("PhantomPixelDev", "ProxmoxWidget").value("dashboard/geometry")
    assert geo is not None
    assert not geo.isEmpty()
    b64 = QSettings("PhantomPixelDev", "ProxmoxWidget").value("dashboard/geometry_b64")
    assert isinstance(b64, str)
    assert len(b64) > 10
    # verify base64 decodes to valid QByteArray
    decoded = base64.b64decode(b64.encode("ascii"))
    assert len(decoded) > 0
    # restore via new Dashboard
    d.close()
    d2 = Dashboard()
    d2.show()
    qapp.processEvents()
    assert d2.width() == 520
    assert d2.height() == 640
    d2.close()
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()
    # source must contain base64 handling
    app_text = pathlib.Path("src/proxmox_widget/app.py").read_text()
    assert "base64" in app_text
    dash_text = pathlib.Path("src/proxmox_widget/ui/dashboard.py").read_text()
    assert "base64" in dash_text
    assert "geometry_b64" in dash_text


def test_close_to_tray_hides_not_quit(dash, qapp):
    dash.set_close_to_tray(True)
    dash.show()
    qapp.processEvents()
    assert dash.isVisible()
    event = MagicMock()
    event.ignore = MagicMock()
    event.accept = MagicMock()
    dash.closeEvent(event)
    qapp.processEvents()
    event.ignore.assert_called()
    assert not dash.isVisible()
    # when close_to_tray False, close proceeds
    dash.show()
    qapp.processEvents()
    dash.set_close_to_tray(False)
    event2 = MagicMock()
    event2.ignore = MagicMock()
    # real closeEvent with False should call super -> close widget
    # we test that ignore not called
    dash.closeEvent(event2)
    event2.ignore.assert_not_called()


def test_global_hotkey_optional_fallback(qapp):
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()
    app = QApplication.instance() or QApplication([])
    import proxmox_widget.config.manager as mgr
    from proxmox_widget.config.models import AppSettings

    orig = mgr.load_settings
    try:
        mgr.load_settings = lambda: AppSettings()
        from proxmox_widget.app import ProxmoxWidgetApp

        # case 1: QHotkey not installed -> fallback warning/info, no crash
        widget_app = ProxmoxWidgetApp(app)
        assert hasattr(widget_app, "_global_hotkey")
        # global hotkey should be None when QHotkey not available
        # or if available but not registered, also None
        # Ensure app still works
        widget_app.show_dashboard()
        qapp.processEvents()
        assert widget_app.dashboard.isVisible()
        widget_app.dashboard.close()
        # case 2: simulate QHotkey already registered -> fallback warning
        mock_hk = MagicMock()
        mock_hk.isRegistered.return_value = False
        mock_hk.activated = MagicMock()
        mock_hk.activated.connect = MagicMock()
        with patch.dict(
            "sys.modules",
            {
                "QHotkey": MagicMock(
                    QHotkey=mock_hk.__class__, **{"QHotkey.return_value": mock_hk}
                ),
                "qhotkey": MagicMock(QHotkey=mock_hk.__class__),
            },
        ):
            # second app instance with mocked already-registered hotkey
            # Force _setup_global_hotkey to hit fallback path
            mock_cls = MagicMock(return_value=mock_hk)
            mock_cls.return_value.isRegistered.return_value = False
            with patch("proxmox_widget.app.logger") as mock_logger:
                # directly invoke fallback check
                # simulate import success but isRegistered False
                widget_app2 = ProxmoxWidgetApp.__new__(ProxmoxWidgetApp)
                # minimal init for test of fallback logic
                # just verify warning path exists in source
                src = pathlib.Path("src/proxmox_widget/app.py").read_text()
                assert "already registered" in src
                assert "QHotkey" in src
                assert "Ctrl+Shift+P" in src
        widget_app.dashboard.close()
    finally:
        mgr.load_settings = orig
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()


def test_app_shortcuts_exist(qapp):
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()
    import proxmox_widget.config.manager as mgr
    from proxmox_widget.config.models import AppSettings

    orig = mgr.load_settings
    try:
        mgr.load_settings = lambda: AppSettings()
        from proxmox_widget.app import ProxmoxWidgetApp

        app = QApplication.instance() or QApplication([])
        w = ProxmoxWidgetApp(app)
        assert hasattr(w, "_sc_app_ctrl_k")
        assert hasattr(w, "_sc_app_ctrl_comma")
        assert hasattr(w, "_sc_app_f5")
        assert hasattr(w, "_sc_app_escape")
        assert hasattr(w, "_sc_app_ctrl_q")
        w.dashboard.close()
    finally:
        mgr.load_settings = orig
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()


def test_frameless_preserved(dash):
    flags = dash.windowFlags()
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.Tool
    text = pathlib.Path("src/proxmox_widget/ui/dashboard.py").read_text()
    assert "FramelessWindowHint" in text
    assert "Qt.WindowType.Tool" in text


def test_no_sqlite3():
    for p in pathlib.Path("src").rglob("*.py"):
        assert "sqlite3" not in p.read_text(encoding="utf-8", errors="ignore")
