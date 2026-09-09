from __future__ import annotations

import asyncio
from typing import Any

import httpx
from loguru import logger

from proxmox_widget.config.manager import get_cluster_secret
from proxmox_widget.config.models import AuthMode, ClusterConfig, ClusterHealth, LxcContainer, ProxmoxNode, QemuVm, StorageStatus

from .exceptions import ActionFailedError, AuthError, ConnectionError


class ProxmoxClient:
    def __init__(self, cluster: ClusterConfig, secret: str | None = None) -> None:
        self.cluster = cluster
        self._secret = secret if secret is not None else get_cluster_secret(cluster.id)
        self._client: httpx.AsyncClient | None = None
        self._ticket: str | None = None
        self._csrf: str | None = None

    def _token_headers(self) -> dict[str, str]:
        if self.cluster.auth_mode == AuthMode.TOKEN and self.cluster.token_id and self._secret:
            return {"Authorization": f"PVEAPIToken={self.cluster.token_id}={self._secret}"}
        return {}

    def _mk_client(self, extra_headers: dict[str, str] | None = None) -> httpx.AsyncClient:
        headers = self._token_headers()
        if extra_headers:
            headers.update(extra_headers)
        if self._ticket:
            headers["Cookie"] = f"PVEAuthCookie={self._ticket}"
        if self._csrf:
            headers["CSRFPreventionToken"] = self._csrf
        return httpx.AsyncClient(
            base_url=self.cluster.api_url,
            headers=headers,
            verify=self.cluster.verify_ssl,
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=False,
        )

    async def __aenter__(self) -> ProxmoxClient:
        if self.cluster.auth_mode == AuthMode.PASSWORD:
            await self._login_ticket()
        self._client = self._mk_client()
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _login_ticket(self) -> None:
        if not self._secret:
            raise AuthError(f"[{self.cluster.id}] no password in keyring")
        url = f"{self.cluster.base_url}/api2/json/access/ticket"
        async with httpx.AsyncClient(verify=self.cluster.verify_ssl, timeout=10.0) as c:
            resp = await c.post(url, data={"username": self.cluster.username, "password": self._secret})
            if resp.status_code in (401, 403):
                raise AuthError(f"[{self.cluster.id}] ticket login failed: {resp.text[:200]}")
            resp.raise_for_status()
            data = resp.json().get("data", {})
            self._ticket = data.get("ticket")
            self._csrf = data.get("CSRFPreventionToken")
            if not self._ticket:
                raise AuthError(f"[{self.cluster.id}] no ticket in response")

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            return self._mk_client()
        return self._client

    async def _get(self, path: str) -> Any:
        client = self._require_client()
        close_after = self._client is None
        if close_after and self.cluster.auth_mode == AuthMode.PASSWORD and not self._ticket:
            await self._login_ticket()
            client = self._mk_client()
        try:
            resp = await client.get(path)
            if resp.status_code == 401:
                raise AuthError(f"[{self.cluster.id}] 401 Unauthorized")
            if resp.status_code == 403:
                raise AuthError(f"[{self.cluster.id}] 403 Forbidden")
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", data)
        except httpx.ConnectError as e:
            raise ConnectionError(f"[{self.cluster.id}] connect failed: {e}") from e
        except httpx.TimeoutException as e:
            raise ConnectionError(f"[{self.cluster.id}] timeout: {e}") from e
        finally:
            if close_after:
                await client.aclose()

    async def _post(self, path: str, data: dict[str, Any] | None = None) -> Any:
        client = self._require_client()
        close_after = self._client is None
        if close_after and self.cluster.auth_mode == AuthMode.PASSWORD and not self._ticket:
            await self._login_ticket()
            client = self._mk_client()
        try:
            resp = await client.post(path, data=data)
            if resp.status_code in (401, 403):
                raise AuthError(f"[{self.cluster.id}] auth failed: {resp.status_code}")
            resp.raise_for_status()
            data_j = resp.json()
            return data_j.get("data", data_j)
        except httpx.ConnectError as e:
            raise ConnectionError(f"[{self.cluster.id}] connect failed: {e}") from e
        finally:
            if close_after:
                await client.aclose()

    async def fetch_nodes(self) -> list[ProxmoxNode]:
        raw = await self._get("/nodes")
        nodes: list[ProxmoxNode] = []
        for item in raw or []:
            try:
                nodes.append(
                    ProxmoxNode(
                        node=item.get("node", ""),
                        status=item.get("status", "unknown"),
                        cpu=float(item.get("cpu", 0) or 0),
                        maxcpu=int(item.get("maxcpu", 0) or 0),
                        mem=int(item.get("mem", 0) or 0),
                        maxmem=int(item.get("maxmem", 0) or 0),
                        disk=int(item.get("disk", 0) or 0),
                        maxdisk=int(item.get("maxdisk", 0) or 0),
                        uptime=int(item.get("uptime", 0) or 0),
                    )
                )
            except Exception as e:
                logger.warning("skip node parse {}: {}", item, e)
        return nodes

    async def fetch_qemu(self, node: str) -> list[QemuVm]:
        raw = await self._get(f"/nodes/{node}/qemu")
        vms: list[QemuVm] = []
        for item in raw or []:
            try:
                vms.append(
                    QemuVm(
                        vmid=int(item["vmid"]),
                        name=item.get("name", f"vm-{item['vmid']}"),
                        node=node,
                        status=item.get("status", "unknown"),
                        cpus=int(item.get("cpus", 0) or 0),
                        cpu=max(0.0, float(item.get("cpu", 0) or 0)),
                        mem=int(item.get("mem", 0) or 0),
                        maxmem=int(item.get("maxmem", 0) or 0),
                        disk=int(item.get("disk", 0) or 0),
                        maxdisk=int(item.get("maxdisk", 0) or 0),
                        uptime=int(item.get("uptime", 0) or 0),
                        template=bool(item.get("template", 0)),
                    )
                )
            except Exception as e:
                logger.warning("skip qemu parse {}: {}", item, e)
        return vms

    async def fetch_lxc(self, node: str) -> list[LxcContainer]:
        raw = await self._get(f"/nodes/{node}/lxc")
        out: list[LxcContainer] = []
        for item in raw or []:
            try:
                out.append(
                    LxcContainer(
                        vmid=int(item["vmid"]),
                        name=item.get("name", f"ct-{item['vmid']}"),
                        node=node,
                        status=item.get("status", "unknown"),
                        cpus=int(item.get("cpus", 0) or 0),
                        cpu=max(0.0, float(item.get("cpu", 0) or 0)),
                        mem=int(item.get("mem", 0) or 0),
                        maxmem=int(item.get("maxmem", 0) or 0),
                        disk=int(item.get("disk", 0) or 0),
                        maxdisk=int(item.get("maxdisk", 0) or 0),
                        uptime=int(item.get("uptime", 0) or 0),
                    )
                )
            except Exception as e:
                logger.warning("skip lxc parse {}: {}", item, e)
        return out

    async def fetch_storage(self, node: str) -> list[StorageStatus]:
        raw = await self._get(f"/nodes/{node}/storage")
        out: list[StorageStatus] = []
        for item in raw or []:
            try:
                out.append(
                    StorageStatus(
                        storage=item.get("storage", ""),
                        node=node,
                        type=item.get("type", ""),
                        status=item.get("status", "unknown"),
                        total=int(item.get("total", 0) or 0),
                        used=int(item.get("used", 0) or 0),
                        avail=int(item.get("avail", 0) or 0),
                        enabled=bool(item.get("enabled", 1)),
                        shared=bool(item.get("shared", 0)),
                    )
                )
            except Exception as e:
                logger.warning("skip storage parse {}: {}", item, e)
        return out

    async def fetch_health(self) -> ClusterHealth:
        try:
            nodes = await self.fetch_nodes()
        except Exception as e:
            return ClusterHealth(
                cluster_id=self.cluster.id,
                cluster_name=self.cluster.name,
                online=False,
                error=str(e),
            )

        async def _for_node(n: ProxmoxNode) -> tuple[list[QemuVm], list[LxcContainer], list[StorageStatus]]:
            if n.status != "online":
                return [], [], []
            try:
                vms, cts, stor = await asyncio.gather(
                    self.fetch_qemu(n.node),
                    self.fetch_lxc(n.node),
                    self.fetch_storage(n.node),
                )
                return vms, cts, stor
            except Exception as e:
                logger.warning("node {} fetch failed: {}", n.node, e)
                return [], [], []

        results = await asyncio.gather(*[_for_node(n) for n in nodes])
        all_vms: list[QemuVm] = []
        all_cts: list[LxcContainer] = []
        all_stor: list[StorageStatus] = []
        for vms, cts, stor in results:
            all_vms.extend(vms)
            all_cts.extend(cts)
            all_stor.extend(stor)
        return ClusterHealth(
            cluster_id=self.cluster.id,
            cluster_name=self.cluster.name,
            online=True,
            nodes=nodes,
            vms=all_vms,
            containers=all_cts,
            storages=all_stor,
        )

    async def vm_action(self, node: str, vmid: int, action: str, is_lxc: bool = False) -> str:
        kind = "lxc" if is_lxc else "qemu"
        path = f"/nodes/{node}/{kind}/{vmid}/status/{action}"
        try:
            data = await self._post(path)
            if isinstance(data, str):
                return data
            return str(data)
        except Exception as e:
            raise ActionFailedError(f"action {action} failed for {vmid} on {node}: {e}") from e
