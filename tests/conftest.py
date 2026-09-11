import os

# Qt needs a platform plugin; CI has no display
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings


@pytest.fixture(autouse=True)
def _clear_dashboard_qsettings():
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()
    yield
    QSettings("PhantomPixelDev", "ProxmoxWidget").clear()


@pytest.fixture(autouse=True)
def _clear_which_cache():
    from proxmox_widget.core import launcher

    launcher._which_cache.clear()
    yield
    launcher._which_cache.clear()
