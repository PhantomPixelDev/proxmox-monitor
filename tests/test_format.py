from proxmox_widget.utils.format import bar, fmt_bytes, fmt_uptime


def test_fmt_bytes():
    assert fmt_bytes(0) == "0 B"
    assert fmt_bytes(2048) == "2.0 KiB"
    assert fmt_bytes(1024**3) == "1.0 GiB"


def test_fmt_uptime():
    assert fmt_uptime(0) == "—"
    assert "1d" in fmt_uptime(90000)


def test_bar_basic():
    assert bar(0.0) == "░" * 10
    assert bar(1.0) == "█" * 10
    assert bar(0.5) == "█" * 5 + "░" * 5


def test_bar_edge():
    assert bar(0.0, 0) == ""
    assert bar(1.5) == "█" * 10
    assert bar(-1) == "░" * 10
    assert len(bar(0.33, 7)) == 7
    assert bar("bad", 4) == "░" * 4
