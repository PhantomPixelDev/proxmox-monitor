import asyncio

import pytest

from proxmox_widget.api.client import ProxmoxClient
from proxmox_widget.config.models import AuthMode, ClusterConfig
from proxmox_widget.core import launcher


def _client() -> ProxmoxClient:
    c = ClusterConfig(
        id="pve", name="PVE", host="1.2.3.4", token_id="root@pam!t", auth_mode=AuthMode.TOKEN
    )
    return ProxmoxClient(c, secret="s3cr3t")


def test_console_url_kvm():
    url = _client().console_url("pve", 112, "win10")
    assert url.startswith("https://1.2.3.4:8006/?")
    assert "console=kvm" in url
    assert "vmid=112" in url
    assert "vmname=win10" in url
    assert "node=pve" in url


def test_console_url_lxc():
    assert "console=lxc" in _client().console_url("pve", 107, "docker", is_lxc=True)


def test_node_shell_url():
    url = _client().node_shell_url("pve")
    assert "console=shell" in url
    assert "node=pve" in url


def test_spice_vv_renders_ini():
    vv = ProxmoxClient.spice_vv({"type": "spice", "host": "1.2.3.4", "tls-port": 61000})
    assert vv.splitlines()[0] == "[virt-viewer]"
    assert "tls-port=61000" in vv
    assert vv.endswith("\n")


@pytest.mark.asyncio
async def test_agent_ips_skips_loopback_and_ipv6(monkeypatch):
    client = _client()

    async def fake_get(path):
        assert path == "/nodes/pve/qemu/112/agent/network-get-interfaces"
        return {
            "result": [
                {
                    "name": "lo",
                    "ip-addresses": [{"ip-address": "127.0.0.1", "ip-address-type": "ipv4"}],
                },
                {
                    "name": "eth0",
                    "ip-addresses": [
                        {"ip-address": "fe80::1", "ip-address-type": "ipv6"},
                        {"ip-address": "169.254.3.4", "ip-address-type": "ipv4"},
                        {"ip-address": "192.168.10.55", "ip-address-type": "ipv4"},
                    ],
                },
            ]
        }

    monkeypatch.setattr(client, "_get", fake_get)
    assert await client.agent_ips("pve", 112) == ["192.168.10.55"]


def test_rdp_command_per_platform(monkeypatch):
    launcher._which_cache.clear()
    monkeypatch.setattr(launcher.platform, "system", lambda: "Windows")
    assert launcher.rdp_command("10.0.0.5") == ["mstsc", "/v:10.0.0.5:3389"]

    launcher._which_cache.clear()
    monkeypatch.setattr(launcher.platform, "system", lambda: "Linux")
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    assert launcher.rdp_command("10.0.0.5") is None

    launcher._which_cache.clear()
    monkeypatch.setattr(
        launcher.shutil, "which", lambda name: "/usr/bin/xfreerdp" if name == "xfreerdp" else None
    )
    assert launcher.rdp_command("10.0.0.5") == ["/usr/bin/xfreerdp", "/v:10.0.0.5:3389"]


def test_ssh_command_default_and_custom_port():
    assert launcher.ssh_command("pve.lan", "root", 22) == ["ssh", "-tt", "root@pve.lan"]
    assert launcher.ssh_command("pve.lan", "root", 2222) == [
        "ssh",
        "-tt",
        "-p",
        "2222",
        "root@pve.lan",
    ]


def test_terminal_command_picks_the_first_wrapper(monkeypatch):
    argv = ["ssh", "-tt", "root@pve"]

    launcher._which_cache.clear()
    monkeypatch.setattr(launcher.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        launcher.shutil, "which", lambda name: "C:/wt.exe" if name == "wt" else None
    )
    assert launcher.terminal_command(argv) == ["C:/wt.exe", "--", *argv]

    launcher._which_cache.clear()
    monkeypatch.setattr(launcher.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        launcher.shutil,
        "which",
        lambda name: "/usr/bin/konsole" if name == "konsole" else None,
    )
    assert launcher.terminal_command(argv) == ["/usr/bin/konsole", "-e", *argv]

    # nothing installed — caller falls back to the bare ssh argv
    launcher._which_cache.clear()
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    assert launcher.terminal_command(argv) is None


@pytest.mark.asyncio
async def test_open_ssh_needs_the_ssh_binary(monkeypatch):
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    assert launcher.open_ssh("pve.lan") is False


@pytest.mark.asyncio
async def test_open_ssh_launches_a_terminal(monkeypatch):
    launched = []
    launcher._which_cache.clear()

    monkeypatch.setattr(
        launcher.shutil, "which", lambda name: "C:/Windows/System32/OpenSSH/ssh.exe"
    )
    monkeypatch.setattr(
        launcher,
        "terminal_command",
        lambda argv: ["wt.exe", "--", *argv],
    )
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda cmd: launched.append(cmd))
    assert launcher.open_ssh("pve.lan", "root", 2222) is True
    assert launched[0][0] == "wt.exe"
    assert launched[0][-1] == "root@pve.lan"


def test_rdp_file_carries_address_port_and_user():
    text = launcher.build_rdp_file("10.0.0.5", 3390, "Admin")
    lines = text.split("\r\n")
    assert "full address:s:10.0.0.5:3390" in lines
    assert "username:s:Admin" in lines
    assert "smart sizing:i:1" in lines
    assert text.endswith("\r\n"), "mstsc expects CRLF line endings"


def test_rdp_file_without_user_omits_the_line():
    assert "username" not in launcher.build_rdp_file("10.0.0.5")


def test_rdp_file_is_written_private_and_removable():
    path = launcher.write_rdp_file(launcher.build_rdp_file("10.0.0.5"), 7)
    try:
        assert path.name == "rdp-7.rdp"
        assert "full address:s:10.0.0.5:3389" in path.read_text(encoding="utf-8")
    finally:
        launcher.discard(path)
    assert not path.exists()


def test_open_rdp_file_uses_mstsc_on_windows(monkeypatch):
    launched = []
    monkeypatch.setattr(launcher.platform, "system", lambda: "Windows")
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda cmd: launched.append(cmd))
    assert launcher.open_rdp_file(launcher.Path("C:/tmp/x.rdp")) is True
    assert launched[0] == ["mstsc", "C:\\tmp\\x.rdp"]


def test_open_rdp_file_reports_no_client(monkeypatch):
    monkeypatch.setattr(launcher.platform, "system", lambda: "Linux")
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    assert launcher.open_rdp_file(launcher.Path("/tmp/x.rdp")) is False


@pytest.mark.asyncio
async def test_privileges_flattens_paths(monkeypatch):
    client = _client()

    async def fake_get(path):
        assert path == "/access/permissions"
        return {
            "/": {"VM.Audit": 1, "VM.Console": 0},
            "/vms/112": {"VM.Console": 1, "VM.PowerMgmt": 1},
        }

    monkeypatch.setattr(client, "_get", fake_get)
    assert await client.privileges() == {"VM.Audit", "VM.Console", "VM.PowerMgmt"}
    assert await client.has_privilege("VM.Console")
    assert not await client.has_privilege("Sys.Modify")


@pytest.mark.asyncio
async def test_spice_403_names_the_missing_privilege(monkeypatch):
    from proxmox_widget.api.exceptions import ActionFailedError, AuthError

    client = _client()

    async def fake_post(path, data=None):
        raise AuthError("[pve] auth failed: 403")

    monkeypatch.setattr(client, "_post", fake_post)
    with pytest.raises(ActionFailedError, match=r"VM\.Console"):
        await client.spice_config("pve", 112)


@pytest.mark.asyncio
async def test_agent_missing_reads_plainly(monkeypatch):
    from proxmox_widget.api.exceptions import ActionFailedError

    client = _client()

    async def fake_get(path):
        raise RuntimeError("Server error '500 No QEMU guest agent configured' for url https://x")

    monkeypatch.setattr(client, "_get", fake_get)
    with pytest.raises(ActionFailedError, match="no guest agent enabled"):
        await client.agent_ips("pve", 112)


@pytest.mark.asyncio
async def test_lxc_ips_reads_inet_and_skips_bridges(monkeypatch):
    client = _client()

    async def fake_get(path):
        assert path == "/nodes/pve/lxc/200/interfaces"
        return [
            {"name": "lo", "inet": "127.0.0.1/8"},
            {"name": "eth0", "inet": "192.168.10.77/24"},
            {"name": "docker0", "inet": "172.17.0.1/16"},
        ]

    monkeypatch.setattr(client, "_get", fake_get)
    assert await client.lxc_ips("pve", 200) == ["192.168.10.77"]


def test_rdp_prefers_the_address_on_the_proxmox_network():
    ips = ["172.17.0.1", "10.8.0.4", "192.168.10.55"]
    assert launcher.pick_rdp_host(ips, near="192.168.10.2") == "192.168.10.55"


def test_rdp_falls_back_when_nothing_is_on_that_network():
    assert launcher.pick_rdp_host(["10.8.0.4"], near="192.168.10.2") == "10.8.0.4"
    assert launcher.pick_rdp_host([], near="192.168.10.2") is None
    assert launcher.pick_rdp_host(["127.0.0.1", "169.254.1.1"]) is None


def test_spice_file_is_private_and_removable():
    import os
    import stat

    path = launcher.write_spice_file("[virt-viewer]\npassword=TICKET\n", 42)
    try:
        assert path.read_text(encoding="utf-8").endswith("TICKET\n")
        if os.name != "nt":
            # the ticket is live; no other local user may read it
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    finally:
        launcher.discard(path)
    assert not path.exists()


@pytest.mark.asyncio
async def test_agent_ips_skips_container_bridges(monkeypatch):
    client = _client()

    async def fake_get(path):
        return {
            "result": [
                {
                    "name": "docker0",
                    "ip-addresses": [{"ip-address": "172.17.0.1", "ip-address-type": "ipv4"}],
                },
                {
                    "name": "veth0",
                    "ip-addresses": [{"ip-address": "172.18.0.1", "ip-address-type": "ipv4"}],
                },
                {
                    "name": "ens18",
                    "ip-addresses": [{"ip-address": "192.168.10.55", "ip-address-type": "ipv4"}],
                },
            ]
        }

    monkeypatch.setattr(client, "_get", fake_get)
    assert await client.agent_ips("pve", 112) == ["192.168.10.55"]


@pytest.mark.asyncio
async def test_spice_without_a_spice_display_says_so(monkeypatch):
    from proxmox_widget.api.exceptions import ActionFailedError

    client = _client()

    async def fake_post(path, data=None):
        raise RuntimeError("Server error '500 no spice port' for url https://x")

    async def running(node, vmid, is_lxc=False):
        return "running"

    monkeypatch.setattr(client, "_post", fake_post)
    monkeypatch.setattr(client, "get_guest_status", running)
    with pytest.raises(ActionFailedError, match="no SPICE display"):
        await client.spice_config("pve", 112)


@pytest.mark.asyncio
async def test_agent_installed_but_silent_says_so(monkeypatch):
    from proxmox_widget.api.exceptions import ActionFailedError

    client = _client()

    async def fake_get(path):
        raise RuntimeError("Server error '500 QEMU guest agent is not running' for url https://x")

    async def running(node, vmid, is_lxc=False):
        return "running"

    monkeypatch.setattr(client, "_get", fake_get)
    monkeypatch.setattr(client, "get_guest_status", running)
    with pytest.raises(ActionFailedError, match="not answering"):
        await client.agent_ips("pve", 112)


@pytest.mark.asyncio
async def test_stopped_vm_is_not_blamed_on_its_display(monkeypatch):
    """PVE answers 'no spice port' for a stopped guest too, which read as a
    misconfigured display even when the display was right."""
    from proxmox_widget.api.exceptions import ActionFailedError

    client = _client()

    async def fake_post(path, data=None):
        raise RuntimeError("Server error '500 no spice port' for url https://x")

    async def fake_status(node, vmid, is_lxc=False):
        return "stopped"

    monkeypatch.setattr(client, "_post", fake_post)
    monkeypatch.setattr(client, "get_guest_status", fake_status)
    with pytest.raises(ActionFailedError, match="is not running"):
        await client.spice_config("pve", 112)


@pytest.mark.asyncio
async def test_running_vm_without_a_spice_display_still_says_display(monkeypatch):
    from proxmox_widget.api.exceptions import ActionFailedError

    client = _client()

    async def fake_post(path, data=None):
        raise RuntimeError("Server error '500 no spice port' for url https://x")

    async def fake_status(node, vmid, is_lxc=False):
        return "running"

    monkeypatch.setattr(client, "_post", fake_post)
    monkeypatch.setattr(client, "get_guest_status", fake_status)
    with pytest.raises(ActionFailedError, match="no SPICE display"):
        await client.spice_config("pve", 112)


@pytest.mark.asyncio
async def test_spice_proxy_falls_back_to_the_configured_host(monkeypatch):
    """PVE hands back its own hostname, which often does not resolve for the user."""
    client = _client()

    async def fake_post(path, data=None):
        return {
            "proxy": "http://pve.homelab:3128",
            "host-subject": "CN=pve.homelab",
            "tls-port": 61000,
        }

    monkeypatch.setattr(client, "_post", fake_post)

    loop = asyncio.get_running_loop()

    async def fail_resolve(host, port):
        raise OSError("name does not resolve")

    monkeypatch.setattr(loop, "getaddrinfo", fail_resolve, raising=False)

    cfg = await client.spice_config("pve", 112)
    assert cfg["proxy"] == "http://1.2.3.4:3128"
    assert cfg["host-subject"] == "CN=pve.homelab", "TLS pinning must be left alone"
