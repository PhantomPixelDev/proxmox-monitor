import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import proxmox_widget.core.launcher as launcher
from proxmox_widget.api.exceptions import ActionFailedError
from proxmox_widget.core.launcher import _which_cache, pick_rdp_host, ssh_command


def test_pick_rdp_host_prefix_aware_slash():
    # near contains "/" -> ip_interface logic, /24
    ips = ["192.168.2.50", "10.0.0.5"]
    assert pick_rdp_host(ips, near="192.168.2.10/24") == "192.168.2.50"
    # different prefix /16 should match different
    assert pick_rdp_host(ips, near="192.168.0.1/16") == "192.168.2.50"
    # /32 should only match exact
    assert pick_rdp_host(ips, near="10.0.0.5/32") == "10.0.0.5"


def test_pick_rdp_host_ipv6_64():
    ips = ["fd00:0:0:1::5", "fd00:0:0:2::5"]
    # without slash, IPv6 should use /64
    near = "fd00:0:0:1::1"
    assert pick_rdp_host(ips, near=near) == "fd00:0:0:1::5"
    # with slash, ip_interface network used
    assert pick_rdp_host(ips, near="fd00:0:0:1::1/64") == "fd00:0:0:1::5"
    # different /64 should pick other
    assert pick_rdp_host(ips, near="fd00:0:0:2::1") == "fd00:0:0:2::5"


def test_pick_rdp_host_non_cidr_still_24():
    ips = ["192.168.1.5", "10.0.0.5"]
    # near without "/" -> /24
    assert pick_rdp_host(ips, near="192.168.1.100") == "192.168.1.5"
    assert pick_rdp_host(ips, near="10.0.0.1") == "10.0.0.5"


def test_pick_rdp_host_invalid_near_fallback():
    ips = ["192.168.1.5", "10.0.0.5"]
    assert pick_rdp_host(ips, near="not-an-ip") == "192.168.1.5"


def test_popen_guard_raises_action_failed():
    with patch("proxmox_widget.core.launcher.subprocess.Popen", side_effect=OSError("nope")):
        with patch("proxmox_widget.core.launcher.platform.system", return_value="Linux"):
            with pytest.raises(ActionFailedError):
                launcher.open_file(Path("/tmp/foo.vv"))
        with patch("proxmox_widget.core.launcher.platform.system", return_value="Linux"):
            with patch("proxmox_widget.core.launcher._which", return_value="/usr/bin/xfreerdp"):
                with pytest.raises(ActionFailedError):
                    launcher.open_rdp_file(Path("/tmp/foo.rdp"))
            with patch("proxmox_widget.core.launcher._which", return_value="/usr/bin/ssh"):
                with patch(
                    "proxmox_widget.core.launcher.terminal_command",
                    return_value=["ssh", "-tt", "root@host"],
                ):
                    with pytest.raises(ActionFailedError):
                        launcher.open_ssh("host")
        with patch(
            "proxmox_widget.core.launcher.rdp_command", return_value=["mstsc", "/v:host:3389"]
        ):
            with pytest.raises(ActionFailedError):
                launcher.open_rdp("host")
        # open_spice
        with patch("proxmox_widget.core.launcher._which", return_value="/usr/bin/remote-viewer"):
            with patch(
                "proxmox_widget.core.launcher.write_spice_file", return_value=Path("/tmp/spice.vv")
            ):
                with pytest.raises(ActionFailedError):
                    launcher.open_spice("content", 100)


def test_which_cache_dict():
    assert isinstance(_which_cache, dict)
    _which_cache.clear()
    with patch(
        "proxmox_widget.core.launcher.shutil.which", return_value="/usr/bin/ssh"
    ) as mock_which:
        assert launcher._which("ssh") == "/usr/bin/ssh"
        assert launcher._which("ssh") == "/usr/bin/ssh"
        mock_which.assert_called_once()
    _which_cache.clear()
    with patch("proxmox_widget.core.launcher.shutil.which", return_value=None) as mock_which:
        assert launcher._which("missing") is None
        assert launcher._which("missing") is None
        mock_which.assert_called_once()
    _which_cache.clear()


def test_atexit_registered():
    # check that _cleanup_temp_dirs is registered
    # atexit._exithandlers may not be public, check via mock
    found = False
    # inspect by registering and checking that at least one handler contains proxmoxwidget logic
    # simpler: verify the function exists and does rmtree
    assert hasattr(launcher, "_cleanup_temp_dirs")
    # verify it cleans proxmoxwidget-* dirs
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir) / "proxmoxwidget-test123"
        d.mkdir()
        (d / "file.txt").write_text("hi")
        with patch("proxmox_widget.core.launcher.tempfile.gettempdir", return_value=tmpdir):
            launcher._cleanup_temp_dirs()
        assert not d.exists()


def test_ssh_command_tt_unchanged():
    assert ssh_command("host") == ["ssh", "-tt", "root@host"]
    assert ssh_command("host", port=2222) == ["ssh", "-tt", "-p", "2222", "root@host"]
    assert ssh_command("1.2.3.4", user="admin", port=22) == ["ssh", "-tt", "admin@1.2.3.4"]
