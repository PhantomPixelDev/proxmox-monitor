from __future__ import annotations

import asyncio
from typing import Any

import httpx
from loguru import logger

from proxmox_widget.config.manager import get_cluster_secret
from proxmox_widget.config.models import (
    AuthMode,
    ClusterConfig,
    ClusterHealth,
    LxcContainer,
    ProxmoxNode,
    QemuVm,
    StorageStatus,
)

from .exceptions import ActionFailedError, AuthError, ConnectionError

# interfaces a guest creates for its own containers or VMs, never the address
# you want to reach the guest on
VIRTUAL_IFACE_PREFIXES = ("lo", "docker", "veth", "virbr", "vmbr", "br-", "tap", "tun", "zt", "wg")


class ProxmoxClient:
    def __init__(self, cluster: ClusterConfig, secret: str | None = None) -> None:
        self.cluster = cluster
        self._secret = secret if secret is not None else get_cluster_secret(cluster.id)
        self._client: httpx.AsyncClient | None = None
        self._ticket: str | None = None
        self._csrf: str | None = None
        self._privs: set[str] | None = None

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
            resp = await c.post(
                url, data={"username": self.cluster.username, "password": self._secret}
            )
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
            raise ConnectionError(self._connect_hint(e)) from e
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
            raise ConnectionError(self._connect_hint(e)) from e
        finally:
            if close_after:
                await client.aclose()

    def _connect_hint(self, error: Exception) -> str:
        """Turn a handshake failure into something the user can act on."""
        text = str(error)
        if "CERTIFICATE_VERIFY_FAILED" in text or "certificate verify failed" in text:
            return (
                f"[{self.cluster.id}] TLS certificate not trusted — add your CA to the system "
                "store, or turn off Verify TLS for this cluster in Settings"
            )
        return f"[{self.cluster.id}] connect failed: {text}"

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

        async def _for_node(
            n: ProxmoxNode,
        ) -> tuple[list[QemuVm], list[LxcContainer], list[StorageStatus]]:
            if n.status != "online":
                return [], [], []
            vms: list[QemuVm] = []
            cts: list[LxcContainer] = []
            stor: list[StorageStatus] = []
            try:
                vms = await self.fetch_qemu(n.node)
            except Exception as e:
                logger.warning("node {} qemu failed: {}", n.node, e)
            try:
                cts = await self.fetch_lxc(n.node)
            except Exception as e:
                msg = str(e)
                if "500" in msg or "Connection reset" in msg:
                    logger.warning("node {} lxc 500 transient, retrying once", n.node)
                    await asyncio.sleep(0.7)
                    try:
                        cts = await self.fetch_lxc(n.node)
                    except Exception as e2:
                        logger.warning("node {} lxc retry failed: {}", n.node, e2)
                else:
                    logger.warning("node {} lxc failed: {}", n.node, e)
            try:
                stor = await self.fetch_storage(n.node)
            except Exception as e:
                logger.warning("node {} storage failed: {}", n.node, e)
            return vms, cts, stor

        results = await asyncio.gather(*[_for_node(n) for n in nodes])
        all_vms: list[QemuVm] = []
        all_cts: list[LxcContainer] = []
        all_stor: list[StorageStatus] = []
        seen_shared: set[str] = set()
        for vms, cts, stor in results:
            all_vms.extend(vms)
            all_cts.extend(cts)
            for st in stor:
                # a shared store is attached to every node and would otherwise
                # be listed once per node
                if st.shared:
                    if st.storage in seen_shared:
                        continue
                    seen_shared.add(st.storage)
                all_stor.append(st)
        return ClusterHealth(
            cluster_id=self.cluster.id,
            cluster_name=self.cluster.name,
            online=True,
            nodes=nodes,
            vms=all_vms,
            containers=all_cts,
            storages=all_stor,
        )

    # ---- console / remote access -------------------------------------------------

    def console_url(self, node: str, vmid: int, name: str = "", is_lxc: bool = False) -> str:
        """noVNC web-console deep link into the Proxmox UI."""
        from urllib.parse import urlencode

        q = {
            "console": "lxc" if is_lxc else "kvm",
            "novnc": 1,
            "vmid": vmid,
            "vmname": name or str(vmid),
            "node": node,
            "resize": "off",
        }
        return f"{self.cluster.base_url}/?{urlencode(q)}"

    def node_shell_url(self, node: str) -> str:
        """noVNC shell for a node."""
        from urllib.parse import urlencode

        return (
            f"{self.cluster.base_url}/?{urlencode({'console': 'shell', 'novnc': 1, 'node': node})}"
        )

    async def version(self) -> str:
        data = await self._get("/version")
        return str(data.get("version", "unknown")) if isinstance(data, dict) else "unknown"

    async def privileges(self) -> set[str]:
        """Every privilege this token holds, flattened across all paths."""
        if self._privs is not None:
            return self._privs
        out: set[str] = set()
        try:
            data = await self._get("/access/permissions")
        except Exception as e:
            logger.warning("permission lookup failed: {}", e)
            return out
        if isinstance(data, dict):
            for privs in data.values():
                if isinstance(privs, dict):
                    out.update(k for k, v in privs.items() if v)
        self._privs = out
        return out

    async def has_privilege(self, name: str) -> bool:
        return name in await self.privileges()

    async def spice_config(self, node: str, vmid: int) -> dict[str, Any]:
        """POST spiceproxy — returns the key/values that make up a .vv file."""
        try:
            data = await self._post(f"/nodes/{node}/qemu/{vmid}/spiceproxy")
        except AuthError as e:
            if "403" in str(e):
                raise ActionFailedError(
                    "Token lacks VM.Console — add it in Datacenter, Permissions"
                ) from e
            raise
        except Exception as e:
            msg = str(e)
            # PVE only opens a SPICE port when the guest has a SPICE display
            if "no spice port" in msg or ("spice" in msg.lower() and "500" in msg):
                raise ActionFailedError(
                    f"VM {vmid} has no SPICE display — set Display to SPICE (qxl) "
                    "in its Hardware tab, then reboot it"
                ) from e
            raise ActionFailedError(f"SPICE unavailable: {msg[:120]}") from e
        if not isinstance(data, dict):
            raise ActionFailedError(f"spiceproxy returned no config for {vmid}")
        return data

    @staticmethod
    def spice_vv(config: dict[str, Any]) -> str:
        """Render a remote-viewer .vv file from a spiceproxy response."""
        lines = ["[virt-viewer]"]
        for k, v in config.items():
            if v is None:
                continue
            if isinstance(v, bool):
                v = 1 if v else 0
            lines.append(f"{k}={v}")
        return chr(10).join(lines) + chr(10)

    async def agent_ips(self, node: str, vmid: int) -> list[str]:
        """IPv4 addresses reported by the QEMU guest agent (loopback/link-local dropped)."""
        try:
            data = await self._get(f"/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces")
        except Exception as e:
            msg = str(e)
            if "No QEMU guest agent configured" in msg:
                raise ActionFailedError(
                    f"VM {vmid} has no guest agent enabled — tick QEMU Guest Agent "
                    "in its Options tab, then reboot it"
                ) from e
            if "not running" in msg:
                raise ActionFailedError(
                    f"Guest agent not answering on VM {vmid} — start the QEMU Guest Agent "
                    "service inside the guest, and reboot the VM if you only just enabled it"
                ) from e
            if "403" in msg:
                raise ActionFailedError(
                    "Token lacks VM.GuestAgent.Audit — add it in Datacenter, Permissions"
                ) from e
            raise ActionFailedError(f"Guest agent unavailable: {msg[:120]}") from e
        ifaces = data.get("result", data) if isinstance(data, dict) else data
        out: list[str] = []
        for iface in ifaces or []:
            if not isinstance(iface, dict):
                continue
            name = (iface.get("name") or "").lower()
            if name.startswith(VIRTUAL_IFACE_PREFIXES):
                continue
            for addr in iface.get("ip-addresses") or []:
                ip = str(addr.get("ip-address", ""))
                if addr.get("ip-address-type") != "ipv4" or not ip:
                    continue
                if ip.startswith(("127.", "169.254.")):
                    continue
                out.append(ip)
        return out

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

    async def get_guest_status(self, node: str, vmid: int, is_lxc: bool = False) -> str:
        kind = "lxc" if is_lxc else "qemu"
        try:
            data = await self._get(f"/nodes/{node}/{kind}/{vmid}/status/current")
            return str(data.get("status", "unknown")) if isinstance(data, dict) else "unknown"
        except Exception:
            return "unknown"

    async def get_task_status(self, node: str, upid: str) -> str:
        try:
            data = await self._get(f"/nodes/{node}/tasks/{upid}/status")
            return str(data.get("status", "unknown")) if isinstance(data, dict) else "unknown"
        except Exception:
            return "unknown"

    async def wait_for_guest(
        self, node: str, vmid: int, want: str, is_lxc: bool = False, timeout: float = 45.0
    ) -> bool:
        deadline = asyncio.get_event_loop().time() + timeout
        want = want.lower()
        while asyncio.get_event_loop().time() < deadline:
            cur = await self.get_guest_status(node, vmid, is_lxc=is_lxc)
            if cur.lower() == want:
                return True
            await asyncio.sleep(1.0)
        return False
