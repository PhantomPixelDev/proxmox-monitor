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
    monkeypatch.setattr(launcher.platform, "system", lambda: "Windows")
    assert launcher.rdp_command("10.0.0.5") == ["mstsc", "/v:10.0.0.5:3389"]

    monkeypatch.setattr(launcher.platform, "system", lambda: "Linux")
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    assert launcher.rdp_command("10.0.0.5") is None

    monkeypatch.setattr(
        launcher.shutil, "which", lambda name: "/usr/bin/xfreerdp" if name == "xfreerdp" else None
    )
    assert launcher.rdp_command("10.0.0.5") == ["/usr/bin/xfreerdp", "/v:10.0.0.5:3389"]


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
    with pytest.raises(ActionFailedError, match="no QEMU guest agent enabled"):
        await client.agent_ips("pve", 112)


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
