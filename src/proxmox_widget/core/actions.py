from __future__ import annotations

import asyncio

from loguru import logger

from proxmox_widget.api.client import ProxmoxClient
from proxmox_widget.config.models import ClusterConfig


async def do_action(cluster: ClusterConfig, node: str, vmid: int, action: str, is_lxc: bool) -> str:
    client = ProxmoxClient(cluster)
    upid = await client.vm_action(node, vmid, action, is_lxc=is_lxc)
    logger.info("action {} {}@{} -> {}", action, vmid, node, upid)
    return upid


def do_action_sync(cluster: ClusterConfig, node: str, vmid: int, action: str, is_lxc: bool) -> str:
    return asyncio.run(do_action(cluster, node, vmid, action, is_lxc))
