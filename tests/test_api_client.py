import pytest

from proxmox_widget.api.client import ProxmoxClient
from proxmox_widget.config.models import AuthMode, ClusterConfig


@pytest.mark.asyncio
async def test_fetch_nodes_token(monkeypatch):
    c = ClusterConfig(
        id="pve", name="PVE", host="1.2.3.4", token_id="root@pam!t", auth_mode=AuthMode.TOKEN
    )
    client = ProxmoxClient(c, secret="s3cr3t")

    async def fake_get(path):
        assert path == "/nodes"
        return [
            {
                "node": "pve",
                "status": "online",
                "cpu": 0.3,
                "maxcpu": 4,
                "mem": 1000,
                "maxmem": 4000,
                "disk": 1,
                "maxdisk": 10,
                "uptime": 1000,
            }
        ]

    monkeypatch.setattr(client, "_get", fake_get)
    nodes = await client.fetch_nodes()
    assert nodes[0].node == "pve"
    assert nodes[0].cpu == 0.3


@pytest.mark.asyncio
async def test_shared_storage_is_counted_once(monkeypatch):
    """A shared store is reported by every node and used to appear N times."""
    from proxmox_widget.config.models import ProxmoxNode, StorageStatus

    c = ClusterConfig(
        id="pve", name="PVE", host="1.2.3.4", token_id="root@pam!t", auth_mode=AuthMode.TOKEN
    )
    client = ProxmoxClient(c, secret="s")

    async def fake_nodes():
        return [
            ProxmoxNode(node="pve", status="online"),
            ProxmoxNode(node="pve-2", status="online"),
        ]

    async def fake_storage(node):
        return [
            StorageStatus(storage="local", node=node, type="dir", shared=False, total=10, used=1),
            StorageStatus(storage="nas", node=node, type="nfs", shared=True, total=99, used=9),
        ]

    async def empty(node):
        return []

    monkeypatch.setattr(client, "fetch_nodes", fake_nodes)
    monkeypatch.setattr(client, "fetch_storage", fake_storage)
    monkeypatch.setattr(client, "fetch_qemu", empty)
    monkeypatch.setattr(client, "fetch_lxc", empty)

    health = await client.fetch_health()
    names = sorted(s.storage for s in health.storages)
    assert names == ["local", "local", "nas"]
