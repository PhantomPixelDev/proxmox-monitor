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
                {"name": "lo", "ip-addresses": [{"ip-address": "127.0.0.1", "ip-address-type": "ipv4"}]},
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
