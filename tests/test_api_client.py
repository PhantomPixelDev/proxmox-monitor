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
