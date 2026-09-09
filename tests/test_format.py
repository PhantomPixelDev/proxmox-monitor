from proxmox_widget.utils.format import fmt_bytes, fmt_uptime

def test_fmt_bytes():
    assert fmt_bytes(0) == "0 B"
    assert "KB" in fmt_bytes(2048)

def test_fmt_uptime():
    assert fmt_uptime(0) == "—"
    assert "1d" in fmt_uptime(90000)
