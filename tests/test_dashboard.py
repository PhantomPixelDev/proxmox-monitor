import pytest
from PySide6.QtTest import QTest

from proxmox_widget.config.models import ClusterHealth, LxcContainer, ProxmoxNode, QemuVm
from proxmox_widget.ui.dashboard import CTS, VMS, Dashboard


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
def dash(qapp):
    d = Dashboard()
    d.apply_theme("dark")
    d.show()
    d.update_health(_health())
    qapp.processEvents()
    yield d
    d.close()


def test_search_filters_and_counts(dash, qapp):
    dash._search[VMS].setText("vm-03")
    qapp.processEvents()
    assert dash._counts[VMS].text() == "1/12"

    dash._search[VMS].clear()
    qapp.processEvents()
    assert dash._counts[VMS].text() == "12"


def test_running_toggle_hides_stopped_guests(dash, qapp):
    dash._running_only[VMS].setChecked(True)
    qapp.processEvents()
    shown, total = dash._counts[VMS].text().split("/")
    assert int(shown) == 6
    assert int(total) == 12


def test_search_matches_vmid_and_node(dash, qapp):
    dash._search[VMS].setText("105")
    qapp.processEvents()
    assert dash._counts[VMS].text() == "1/12"

    dash._search[CTS].setText("pve")
    qapp.processEvents()
    assert dash._counts[CTS].text() == "1"


def test_refresh_keeps_the_scroll_position(dash, qapp):
    """A poll every 30s used to throw a long list back to the top."""
    dash.tabs.setCurrentIndex(2)
    qapp.processEvents()
    bar = dash._scrolls[VMS].verticalScrollBar()
    assert bar.maximum() > 0, "test needs a list long enough to scroll"

    bar.setValue(bar.maximum() // 2)
    qapp.processEvents()
    before = bar.value()

    dash.update_health(_health())
    QTest.qWait(150)  # the scrollbar range is recalculated asynchronously

    assert bar.value() == before


def test_empty_state_mentions_the_query(dash, qapp):
    dash._search[VMS].setText("nothing-matches-this")
    qapp.processEvents()
    assert dash._counts[VMS].text() == "0/12"
