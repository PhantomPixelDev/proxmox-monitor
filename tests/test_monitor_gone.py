import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import asyncio
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication

from proxmox_widget.config.models import ClusterConfig, ClusterHealth


def _qapp():
    return QApplication.instance() or QApplication([])


def test_monitor_file_deleted():
    assert not pathlib.Path("src/proxmox_widget/core/monitor.py").exists(), (
        "monitor.py should be deleted"
    )


def test_no_monitor_import_in_src():
    hits = []
    for p in pathlib.Path("src").rglob("*.py"):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        if (
            "from proxmox_widget.core.monitor import" in text
            or "from .monitor import" in text
            or "from proxmox_widget.core import Monitor" in text
        ):
            hits.append(str(p))
    assert hits == [], f"monitor imports remain: {hits}"
    # core __init__ should not export Monitor
    core_init = pathlib.Path("src/proxmox_widget/core/__init__.py").read_text(encoding="utf-8")
    assert "Monitor" not in core_init
    assert "monitor" not in core_init.lower()


def test_grep_from_monitor_import_returns_zero():
    # mirrors: grep -r "from.*monitor import" src → 0
    import re

    pat = re.compile(r"from.*monitor\s+import")
    matches = []
    for p in pathlib.Path("src").rglob("*.py"):
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            if pat.search(line):
                matches.append(f"{p}:{line}")
    assert matches == []


def test_import_monitor_fails():
    with pytest.raises((ImportError, ModuleNotFoundError)):
        import proxmox_widget.core.monitor  # type: ignore  # noqa: F401


def test_app_fetch_all_is_single_source():
    text = pathlib.Path("src/proxmox_widget/app.py").read_text(encoding="utf-8")
    assert "async def _fetch_all" in text
    assert "asyncio.gather" in text
    assert "from proxmox_widget.core.monitor" not in text
    assert "Monitor(" not in text


def test_app_refresh_without_monitor():
    _qapp()
    fake_settings = MagicMock()
    c = ClusterConfig(id="c1", name="lab", host="10.0.0.1", port=8006, token_id="root@pam!t")
    fake_settings.clusters = [c]
    fake_settings.theme.value = "dark"
    fake_settings.refresh_interval_seconds = 30
    fake_settings.start_minimized = True
    fake_settings.notifications_enabled = False

    fake_health = ClusterHealth(
        cluster_id="c1", cluster_name="lab", online=True, vms=[], containers=[]
    )

    with (
        patch("proxmox_widget.app.load_settings", return_value=fake_settings),
        patch("proxmox_widget.app.ProxmoxClient") as MockClient,
    ):
        mock_inst = AsyncMock()
        mock_inst.fetch_health = AsyncMock(return_value=fake_health)
        mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
        mock_inst.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_inst

        from proxmox_widget.app import ProxmoxWidgetApp

        app = QApplication.instance() or QApplication([])
        w = ProxmoxWidgetApp(app)

        # _fetch_all should query via ProxmoxClient, not Monitor
        result = asyncio.run(w._fetch_all())
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].cluster_id == "c1"
        assert result[0].online is True

        # refresh_now delegates to _fetch_all via runner
        w._fetch_all = AsyncMock(return_value=[fake_health])  # type: ignore[method-assign]
        called = []

        orig_spawn = w._spawn

        def capture_spawn(factory, on_done=None, on_error=None):
            called.append(factory)
            # verify factory is w._fetch_all
            assert factory is w._fetch_all

        w._spawn = capture_spawn  # type: ignore[method-assign]
        w._refreshing = False
        w.refresh_now()
        assert len(called) == 1

        # second refresh while refreshing should be skipped (single source guard)
        w._refreshing = True
        w.refresh_now()
        assert len(called) == 1  # not called again

        w._runner.stop()
