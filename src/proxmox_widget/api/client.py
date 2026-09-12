from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib
import socket
import ssl
import time
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
from filelock import FileLock, Timeout
from loguru import logger
from platformdirs import user_config_dir

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

from .exceptions import ActionFailedError, AuthError, ConnectionError, ProxmoxError

VIRTUAL_IFACE_PREFIXES = ("lo", "docker", "veth", "virbr", "vmbr", "br-", "tap", "tun", "zt", "wg")

APP_NAME = "ProxmoxWidget"
APP_AUTHOR = "ProxmoxWidget"


def _sanitize_error(err: object, limit: int = 150) -> str:
    raw = str(err) if err is not None else "Unknown error"
    low = raw.lower()
    if "token" in low or "secret" in low or "pveapitoken" in low:
        return "Authentication failed — check token and permissions"[:limit]
    if "certificate" in low or "fingerprint" in low:
        return "TLS verification failed — check host certificate"[:limit]
    return raw[:limit]


def _trust_path() -> pathlib.Path:
    d = pathlib.Path(user_config_dir(APP_NAME, APP_AUTHOR))
    d.mkdir(parents=True, exist_ok=True)
    return d / "trust.json"


def _load_trust() -> dict[str, str]:
    p = _trust_path()
    if not p.exists():
        return {}
    try:
        data_any: Any = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data_any, dict):
            data_dict: dict[Any, Any] = cast(dict[Any, Any], data_any)
            return {str(k): str(v) for k, v in data_dict.items() if isinstance(v, str)}
    except Exception as e:
        logger.debug("Failed to load trust store {}: {}", p, _sanitize_error(e, 150))
    return {}


def _save_trust(data: dict[str, str]) -> None:
    """Persist trust store to disk with file lock.

    Raises filelock.Timeout if trust.json lock not acquired in 2s
    """

    p = _trust_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(p.with_suffix(".lock")), timeout=2)
    try:
        with lock:
            tmp = pathlib.Path(str(p) + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(json.dumps(data, indent=2))
                f.flush()
                import os

                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
            import os as _os

            _os.replace(tmp, p)
            try:
                _os.chmod(p, 0o600)
            except Exception:
                pass
    except Timeout as e:
        logger.debug("trust store lock timeout for {}: {}", p, _sanitize_error(e, 120))


def _fetch_fingerprint(host: str, port: int) -> str:
    """Return sha256 hex of the server cert DER (via direct TLS)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with (
        socket.create_connection((host, port), timeout=5) as sock,
        ctx.wrap_socket(sock, server_hostname=host) as ssock,
    ):
        der = ssock.getpeercert(binary_form=True)
        if der is None:
            raise RuntimeError("no certificate returned")
        if isinstance(der, bytes):
            return hashlib.sha256(der).hexdigest()
        # fallback: der is dict when binary_form False — shouldn't happen
        raise RuntimeError("unexpected cert form")


def _is_virtual_iface(name: str) -> bool:
    """Return True if *name* looks like a virtual / container interface.

    ``br-`` is special-cased: docker creates ``br-<12-hex>`` bridges that
    should be dropped, but real bridges like ``br-01`` / ``br-1`` (short
    numeric suffix) must be kept. Everything else uses a straight prefix
    match to preserve existing docker/veth/vmbr filtering.
    """
    n = name.lower()
    if n.startswith("br-"):
        suffix = n[3:]
        return not (suffix and suffix.isdigit() and len(suffix) <= 4)
    for prefix in VIRTUAL_IFACE_PREFIXES:
        if prefix == "br-":
            continue
        if n.startswith(prefix):
            return True
    return False


class ProxmoxClient:
    def __init__(self, cluster: ClusterConfig, secret: str | None = None) -> None:
        self.cluster = cluster
        self._secret = secret if secret is not None else get_cluster_secret(cluster.id)
        self._client: httpx.AsyncClient | None = None
        self._ticket: str | None = None
        self._csrf: str | None = None
        self._privs: set[str] | None = None
        self._privs_time: float | None = None
        self._semaphore = asyncio.Semaphore(5)
        self._rrd_cache: dict[tuple[str, int, str], list[float]] = {}

    def _verify(self) -> bool | str:
        if self.cluster.ca_bundle and self.cluster.verify_ssl:
            return self.cluster.ca_bundle
        return self.cluster.verify_ssl

    def _needs_tofu(self) -> bool:
        return not (self.cluster.verify_ssl and not self.cluster.ca_bundle)

    async def _ensure_tofu(self) -> None:
        if not self._needs_tofu():
            return
        try:
            fp = await asyncio.to_thread(_fetch_fingerprint, self.cluster.host, self.cluster.port)
        except Exception as e:
            logger.warning(
                "TOFU fingerprint fetch failed for {}: {}", self.cluster.id, _sanitize_error(e, 150)
            )
            return
        trust = _load_trust()
        stored = trust.get(self.cluster.id)
        if stored is None:
            trust[self.cluster.id] = fp
            _save_trust(trust)
            logger.info("TOFU pinned {} {}", self.cluster.id, fp[:12])
        elif stored != fp:
            logger.warning(
                "certificate fingerprint mismatch for {} expected {} got {}",
                self.cluster.id,
                stored,
                fp,
            )
            raise ConnectionError(
                f"[{self.cluster.id}] certificate fingerprint mismatch: expected {stored} got {fp}"
            )

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
            verify=self._verify(),
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=False,
        )

    async def __aenter__(self) -> ProxmoxClient:
        await self._ensure_tofu()
        if self.cluster.auth_mode == AuthMode.PASSWORD:
            await self._login_ticket()
        self._client = self._mk_client()
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _login_ticket(self) -> None:
        await self._ensure_tofu()
        if not self._secret:
            raise AuthError(f"[{self.cluster.id}] no password in keyring")
        url = f"{self.cluster.base_url}/api2/json/access/ticket"
        async with httpx.AsyncClient(verify=self._verify(), timeout=10.0) as c:
            resp = await c.post(
                url, data={"username": self.cluster.username, "password": self._secret}
            )
            if resp.status_code in (401, 403):
                raise AuthError(
                    resp.status_code, f"[{self.cluster.id}] ticket login failed: {resp.text[:200]}"
                )
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
        await self._ensure_tofu()
        client = self._require_client()
        close_after = self._client is None
        if close_after and self.cluster.auth_mode == AuthMode.PASSWORD and not self._ticket:
            await self._login_ticket()
            client = self._mk_client()
        try:
            resp = await client.get(path)
            if resp.status_code == 401 and self.cluster.auth_mode == AuthMode.PASSWORD:
                await self._login_ticket()
                if close_after:
                    try:
                        await client.aclose()
                    except Exception:
                        pass
                    client = self._mk_client()
                else:
                    if self._client is not None:
                        try:
                            await self._client.aclose()
                        except Exception:
                            pass
                    self._client = self._mk_client()
                    client = self._client
                resp = await client.get(path)
                if resp.status_code == 401:
                    raise AuthError(401, f"[{self.cluster.id}] 401 Unauthorized")
                if resp.status_code == 403:
                    if (
                        self._privs is not None
                        and self._privs_time is not None
                        and time.monotonic() - self._privs_time > 300
                    ):
                        self._privs = None
                        self._privs_time = None
                        try:
                            await self.privileges()
                        except Exception:
                            pass
                    raise AuthError(403, f"[{self.cluster.id}] 403 Forbidden")
                resp.raise_for_status()
                data = resp.json()
                return data.get("data", data)
            if resp.status_code == 401:
                raise AuthError(401, f"[{self.cluster.id}] 401 Unauthorized")
            if resp.status_code == 403:
                if (
                    self._privs is not None
                    and self._privs_time is not None
                    and time.monotonic() - self._privs_time > 300
                ):
                    self._privs = None
                    self._privs_time = None
                    try:
                        await self.privileges()
                    except Exception:
                        pass
                raise AuthError(403, f"[{self.cluster.id}] 403 Forbidden")
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", data)
        except httpx.ConnectError as e:
            raise ConnectionError(self._connect_hint(e)) from e
        except httpx.TimeoutException as e:
            raise ConnectionError(f"[{self.cluster.id}] timeout: {e}") from e
        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response is not None else None
            raise ProxmoxError(status, f"[{self.cluster.id}] HTTP {status}: {e}") from e
        finally:
            if close_after:
                try:
                    await client.aclose()
                except Exception:
                    pass

    async def _post(self, path: str, data: dict[str, Any] | None = None) -> Any:
        await self._ensure_tofu()
        client = self._require_client()
        close_after = self._client is None
        if close_after and self.cluster.auth_mode == AuthMode.PASSWORD and not self._ticket:
            await self._login_ticket()
            client = self._mk_client()
        try:
            resp = await client.post(path, data=data)
            if resp.status_code == 401 and self.cluster.auth_mode == AuthMode.PASSWORD:
                await self._login_ticket()
                if close_after:
                    try:
                        await client.aclose()
                    except Exception:
                        pass
                    client = self._mk_client()
                else:
                    if self._client is not None:
                        try:
                            await self._client.aclose()
                        except Exception:
                            pass
                    self._client = self._mk_client()
                    client = self._client
                resp = await client.post(path, data=data)
                if resp.status_code == 401:
                    raise AuthError(401, f"[{self.cluster.id}] 401 Unauthorized")
                if resp.status_code == 403:
                    raise AuthError(403, f"[{self.cluster.id}] auth failed: 403")
                resp.raise_for_status()
                data_j = resp.json()
                return data_j.get("data", data_j)
            if resp.status_code in (401, 403):
                raise AuthError(
                    resp.status_code, f"[{self.cluster.id}] auth failed: {resp.status_code}"
                )
            resp.raise_for_status()
            data_j = resp.json()
            return data_j.get("data", data_j)
        except httpx.ConnectError as e:
            raise ConnectionError(self._connect_hint(e)) from e
        except httpx.TimeoutException as e:
            raise ConnectionError(f"[{self.cluster.id}] timeout: {e}") from e
        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response is not None else None
            raise ProxmoxError(status, f"[{self.cluster.id}] HTTP {status}: {e}") from e
        finally:
            if close_after:
                try:
                    await client.aclose()
                except Exception:
                    pass

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
        raw_any: Any = await self._get("/nodes")
        nodes: list[ProxmoxNode] = []
        items: list[Any] = (
            cast(list[Any], raw_any) if isinstance(raw_any, list) else cast(list[Any], [])
        )
        for item_any in items:
            item: dict[str, Any] = (
                cast(dict[str, Any], item_any) if isinstance(item_any, dict) else {}
            )
            try:
                nodes.append(
                    ProxmoxNode(
                        node=str(item.get("node", "")),
                        status=str(item.get("status", "unknown")),
                        cpu=float(cast(Any, item.get("cpu", 0)) or 0),
                        maxcpu=int(cast(Any, item.get("maxcpu", 0)) or 0),
                        mem=int(cast(Any, item.get("mem", 0)) or 0),
                        maxmem=int(cast(Any, item.get("maxmem", 0)) or 0),
                        disk=int(cast(Any, item.get("disk", 0)) or 0),
                        maxdisk=int(cast(Any, item.get("maxdisk", 0)) or 0),
                        uptime=int(cast(Any, item.get("uptime", 0)) or 0),
                    )
                )
            except Exception as e:
                logger.debug("skip node parse {}: {}", item, _sanitize_error(e, 120))
        return nodes

    async def fetch_qemu(self, node: str) -> list[QemuVm]:
        raw_any: Any = await self._get(f"/nodes/{node}/qemu")
        vms: list[QemuVm] = []
        items: list[Any] = (
            cast(list[Any], raw_any) if isinstance(raw_any, list) else cast(list[Any], [])
        )
        for item_any in items:
            item: dict[str, Any] = (
                cast(dict[str, Any], item_any) if isinstance(item_any, dict) else {}
            )
            try:
                vms.append(
                    QemuVm(
                        vmid=int(cast(Any, item["vmid"])),
                        name=str(item.get("name", f"vm-{item['vmid']}")),
                        node=node,
                        status=str(item.get("status", "unknown")),
                        cpus=int(cast(Any, item.get("cpus", 0)) or 0),
                        cpu=max(0.0, float(cast(Any, item.get("cpu", 0)) or 0)),
                        mem=int(cast(Any, item.get("mem", 0)) or 0),
                        maxmem=int(cast(Any, item.get("maxmem", 0)) or 0),
                        disk=int(cast(Any, item.get("disk", 0)) or 0),
                        maxdisk=int(cast(Any, item.get("maxdisk", 0)) or 0),
                        uptime=int(cast(Any, item.get("uptime", 0)) or 0),
                        template=bool(item.get("template", 0)),
                    )
                )
            except Exception as e:
                logger.debug("skip qemu parse {}: {}", item, _sanitize_error(e, 120))
        return vms

    async def fetch_lxc(self, node: str) -> list[LxcContainer]:
        raw_any: Any = await self._get(f"/nodes/{node}/lxc")
        out: list[LxcContainer] = []
        items: list[Any] = (
            cast(list[Any], raw_any) if isinstance(raw_any, list) else cast(list[Any], [])
        )
        for item_any in items:
            item: dict[str, Any] = (
                cast(dict[str, Any], item_any) if isinstance(item_any, dict) else {}
            )
            try:
                out.append(
                    LxcContainer(
                        vmid=int(cast(Any, item["vmid"])),
                        name=str(item.get("name", f"ct-{item['vmid']}")),
                        node=node,
                        status=str(item.get("status", "unknown")),
                        cpus=int(cast(Any, item.get("cpus", 0)) or 0),
                        cpu=max(0.0, float(cast(Any, item.get("cpu", 0)) or 0)),
                        mem=int(cast(Any, item.get("mem", 0)) or 0),
                        maxmem=int(cast(Any, item.get("maxmem", 0)) or 0),
                        disk=int(cast(Any, item.get("disk", 0)) or 0),
                        maxdisk=int(cast(Any, item.get("maxdisk", 0)) or 0),
                        uptime=int(cast(Any, item.get("uptime", 0)) or 0),
                    )
                )
            except Exception as e:
                logger.debug("skip lxc parse {}: {}", item, _sanitize_error(e, 120))
        return out

    async def fetch_storage(self, node: str) -> list[StorageStatus]:
        raw_any: Any = await self._get(f"/nodes/{node}/storage")
        out: list[StorageStatus] = []
        items: list[Any] = (
            cast(list[Any], raw_any) if isinstance(raw_any, list) else cast(list[Any], [])
        )
        for item_any in items:
            item: dict[str, Any] = (
                cast(dict[str, Any], item_any) if isinstance(item_any, dict) else {}
            )
            try:
                out.append(
                    StorageStatus(
                        storage=str(item.get("storage", "")),
                        node=node,
                        type=str(item.get("type", "")),
                        status=str(item.get("status", "unknown")),
                        total=int(cast(Any, item.get("total", 0)) or 0),
                        used=int(cast(Any, item.get("used", 0)) or 0),
                        avail=int(cast(Any, item.get("avail", 0)) or 0),
                        enabled=bool(item.get("enabled", 1)),
                        shared=bool(item.get("shared", 0)),
                    )
                )
            except Exception as e:
                logger.debug("skip storage parse {}: {}", item, _sanitize_error(e, 120))
        return out

    async def fetch_health(self) -> ClusterHealth:
        try:
            nodes = await self.fetch_nodes()
        except Exception as e:
            return ClusterHealth(
                cluster_id=self.cluster.id,
                cluster_name=self.cluster.name,
                online=False,
                error=_sanitize_error(e, 150),
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
                logger.warning("node {} qemu failed: {}", n.node, _sanitize_error(e, 150))
            try:
                cts = await self.fetch_lxc(n.node)
            except Exception as e:
                if getattr(e, "status", None) == 500:
                    logger.warning("node {} lxc 500 transient, retrying once", n.node)
                    await asyncio.sleep(0.7)
                    try:
                        cts = await self.fetch_lxc(n.node)
                    except Exception as e2:
                        logger.warning(
                            "node {} lxc retry failed: {}", n.node, _sanitize_error(e2, 150)
                        )
                else:
                    logger.warning("node {} lxc failed: {}", n.node, _sanitize_error(e, 150))
            try:
                stor = await self.fetch_storage(n.node)
            except Exception as e:
                logger.warning("node {} storage failed: {}", n.node, _sanitize_error(e, 150))
            return vms, cts, stor

        async def _for_node_sem(
            n: ProxmoxNode,
        ) -> tuple[list[QemuVm], list[LxcContainer], list[StorageStatus]]:
            async with self._semaphore:
                return await _for_node(n)

        results = await asyncio.gather(*[_for_node_sem(n) for n in nodes])
        all_vms: list[QemuVm] = []
        all_cts: list[LxcContainer] = []
        all_stor: list[StorageStatus] = []
        seen_shared: set[str] = set()
        for vms, cts, stor in results:
            all_vms.extend(vms)
            all_cts.extend(cts)
            for st in stor:
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

    def console_url(self, node: str, vmid: int, name: str = "", is_lxc: bool = False) -> str:
        from urllib.parse import urlencode

        q: dict[str, Any] = {
            "console": "lxc" if is_lxc else "kvm",
            "novnc": 1,
            "vmid": vmid,
            "vmname": name or str(vmid),
            "node": node,
            "resize": "off",
        }
        return f"{self.cluster.base_url}/?{urlencode(cast(Any, q))}"

    def node_shell_url(self, node: str) -> str:
        """noVNC shell for a node."""
        from urllib.parse import urlencode

        return (
            f"{self.cluster.base_url}/?{urlencode({'console': 'shell', 'novnc': 1, 'node': node})}"
        )

    async def version(self) -> str:
        data_any: Any = await self._get("/version")
        if isinstance(data_any, dict):
            data_dict: dict[str, Any] = cast(dict[str, Any], data_any)
            return str(data_dict.get("version", "unknown"))
        return "unknown"

    async def privileges(self) -> set[str]:
        """Every privilege this token holds, flattened across all paths."""
        if (
            self._privs is not None
            and self._privs_time is not None
            and time.monotonic() - self._privs_time <= 300
        ):
            return self._privs
        out: set[str] = set()
        try:
            data_any: Any = await self._get("/access/permissions")
        except Exception as e:
            logger.debug("permission lookup failed: {}", _sanitize_error(e, 150))
            return out
        if isinstance(data_any, dict):
            data_dict: dict[str, Any] = cast(dict[str, Any], data_any)
            for privs_any in data_dict.values():
                if isinstance(privs_any, dict):
                    privs_dict: dict[Any, Any] = cast(dict[Any, Any], privs_any)
                    out.update(str(k) for k, v in privs_dict.items() if v)
        self._privs = out
        self._privs_time = time.monotonic()
        return out

    async def has_privilege(self, name: str) -> bool:
        return name in await self.privileges()

    async def spice_config(self, node: str, vmid: int) -> dict[str, Any]:
        """POST spiceproxy — returns the key/values that make up a .vv file."""
        try:
            data_any_sc: Any = await self._post(f"/nodes/{node}/qemu/{vmid}/spiceproxy")
            data: Any = data_any_sc
        except AuthError as e:
            if getattr(e, "status", None) == 403 or "403" in str(e):
                raise ActionFailedError(
                    "Token lacks VM.Console — add it in Datacenter, Permissions"
                ) from e
            raise
        except Exception as e:
            msg = str(e)
            if "no spice port" in msg or getattr(e, "status", None) == 500:
                if await self.get_guest_status(node, vmid) != "running":
                    raise ActionFailedError(f"VM {vmid} is not running") from e
                raise ActionFailedError(
                    f"VM {vmid} has no SPICE display — set Display to SPICE (qxl) "
                    "in its Hardware tab, then reboot it"
                ) from e
            raise ActionFailedError(f"SPICE unavailable: {msg[:120]}") from e
        if not isinstance(data, dict):
            raise ActionFailedError(f"spiceproxy returned no config for {vmid}")
        return await self._reachable_spice_proxy(cast(dict[str, Any], data))

    async def _reachable_spice_proxy(self, cfg: dict[str, Any]) -> dict[str, Any]:
        """Point the ticket at an address this machine can actually resolve.

        PVE fills in the node's own hostname, which often only resolves inside
        the server's network. TLS is pinned through host-subject rather than the
        address, so swapping in the host the user configured is safe.
        """
        proxy = str(cfg.get("proxy") or "")
        if not proxy:
            return cfg
        parsed = urlsplit(proxy)
        hostname = parsed.hostname
        if not hostname or hostname == self.cluster.host:
            return cfg
        loop = asyncio.get_running_loop()
        try:
            await loop.getaddrinfo(hostname, parsed.port or 3128)
            return cfg
        except OSError:
            pass
        port = f":{parsed.port}" if parsed.port else ""
        cfg["proxy"] = f"{parsed.scheme or 'http'}://{self.cluster.host}{port}"
        logger.info("spice proxy {} does not resolve, using {}", hostname, cfg["proxy"])
        return cfg

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
        try:
            data_any: Any = await self._get(
                f"/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces"
            )
        except Exception as e:
            msg = str(e)
            if "No QEMU guest agent configured" in msg:
                raise ActionFailedError(
                    f"VM {vmid} has no guest agent enabled — tick QEMU Guest Agent "
                    "in its Options tab, then reboot it"
                ) from e
            if "not running" in msg:
                if await self.get_guest_status(node, vmid) != "running":
                    raise ActionFailedError(f"VM {vmid} is not running") from e
                raise ActionFailedError(
                    f"Guest agent not answering on VM {vmid} — start the QEMU Guest Agent "
                    "service inside the guest, and reboot the VM if you only just enabled it"
                ) from e
            if getattr(e, "status", None) == 403:
                raise ActionFailedError(
                    "Token lacks VM.GuestAgent.Audit — add it in Datacenter, Permissions"
                ) from e
            raise ActionFailedError(f"Guest agent unavailable: {msg[:120]}") from e
        data_dict_check: Any = data_any
        if isinstance(data_dict_check, dict):
            dict_val: dict[str, Any] = cast(dict[str, Any], data_dict_check)
            ifaces_any: Any = dict_val.get("result", data_any)
        else:
            ifaces_any = data_any
        out: list[str] = []
        ifaces_list: list[Any] = cast(list[Any], ifaces_any) if isinstance(ifaces_any, list) else []
        for iface_any in ifaces_list:
            if not isinstance(iface_any, dict):
                continue
            iface: dict[str, Any] = cast(dict[str, Any], iface_any)
            name = str(iface.get("name") or "").lower()
            if _is_virtual_iface(name):
                continue
            addrs_any: Any = iface.get("ip-addresses") or []
            addrs_list: list[Any] = (
                cast(list[Any], addrs_any) if isinstance(addrs_any, list) else []
            )
            for addr_any in addrs_list:
                if not isinstance(addr_any, dict):
                    continue
                addr: dict[str, Any] = cast(dict[str, Any], addr_any)
                ip = str(addr.get("ip-address", ""))
                if str(addr.get("ip-address-type")) != "ipv4" or not ip:
                    continue
                if ip.startswith(("127.", "169.254.")):
                    continue
                out.append(ip)
        return out

    async def lxc_ips(self, node: str, vmid: int) -> list[str]:
        try:
            data_any2: Any = await self._get(f"/nodes/{node}/lxc/{vmid}/interfaces")
        except Exception as e:
            msg = str(e)
            if getattr(e, "status", None) == 403:
                raise ActionFailedError(
                    "Token lacks VM.GuestAgent.Audit — add it in Datacenter, Permissions"
                ) from e
            if "not running" in msg:
                raise ActionFailedError(f"Container {vmid} is not running") from e
            raise ActionFailedError(f"Could not read container interfaces: {msg[:120]}") from e
        out: list[str] = []
        data_list: list[Any] = cast(list[Any], data_any2) if isinstance(data_any2, list) else []
        for iface_any in data_list:
            if not isinstance(iface_any, dict):
                continue
            iface: dict[str, Any] = cast(dict[str, Any], iface_any)
            name = str(iface.get("name") or "").lower()
            if _is_virtual_iface(name):
                continue
            raw = str(iface.get("inet") or "")
            if not raw:
                continue
            ip = raw.split("/")[0]
            if ip.startswith(("127.", "169.254.")):
                continue
            out.append(ip)
        return out

    async def vm_action(self, node: str, vmid: int, action: str, is_lxc: bool = False) -> str:
        kind = "lxc" if is_lxc else "qemu"
        path = f"/nodes/{node}/{kind}/{vmid}/status/{action}"
        try:
            data_any3: Any = await self._post(path)
            if isinstance(data_any3, str):
                return data_any3
            return str(data_any3)
        except Exception as e:
            raise ActionFailedError(
                f"action {action} failed for {vmid} on {node}: {_sanitize_error(e, 120)}"
            ) from e

    async def get_guest_status(self, node: str, vmid: int, is_lxc: bool = False) -> str:
        kind = "lxc" if is_lxc else "qemu"
        try:
            data_any4: Any = await self._get(f"/nodes/{node}/{kind}/{vmid}/status/current")
            if isinstance(data_any4, dict):
                d4: dict[str, Any] = cast(dict[str, Any], data_any4)
                return str(d4.get("status", "unknown"))
            return "unknown"
        except Exception:
            return "unknown"

    async def get_task_status(self, node: str, upid: str) -> str:
        try:
            data_any5: Any = await self._get(f"/nodes/{node}/tasks/{upid}/status")
            if isinstance(data_any5, dict):
                d5: dict[str, Any] = cast(dict[str, Any], data_any5)
                return str(d5.get("status", "unknown"))
            return "unknown"
        except Exception:
            return "unknown"

    async def wait_for_guest(
        self, node: str, vmid: int, want: str, is_lxc: bool = False, timeout: float = 45.0
    ) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        want = want.lower()
        while asyncio.get_running_loop().time() < deadline:
            cur = await self.get_guest_status(node, vmid, is_lxc=is_lxc)
            if cur.lower() == want:
                return True
            await asyncio.sleep(1.0)
        return False

    async def fetch_rrddata(self, node: str, vmid: int, timeframe: str = "hour") -> list[float]:
        """Fetch RRD data for a QEMU guest.

        Hits ``/api2/json/nodes/{node}/qemu/{vmid}/rrddata?timeframe=hour`` and
        returns up to 24 cpu points (0-100). Results are cached in-memory per
        ``(node, vmid, timeframe)`` — no sqlite, no disk.
        """
        key: tuple[str, int, str] = (node, vmid, timeframe)
        try:
            raw_any6: Any = await self._get(
                f"/nodes/{node}/qemu/{vmid}/rrddata?timeframe={timeframe}"
            )
        except Exception:
            return self._rrd_cache.get(key, [])
        if not isinstance(raw_any6, list):
            return self._rrd_cache.get(key, [])
        raw_list: list[Any] = cast(list[Any], raw_any6)
        points: list[float] = []
        for entry_any in raw_list:
            if not isinstance(entry_any, dict):
                continue
            entry: dict[str, Any] = cast(dict[str, Any], entry_any)
            cpu: Any = entry.get("cpu", entry.get("value", 0))
            try:
                v = float(cpu or 0)
            except (TypeError, ValueError):
                v = 0.0
            if 0 <= v <= 1.0:
                v *= 100.0
            v = max(0.0, min(100.0, v))
            points.append(v)
        if len(points) > 24:
            points = points[-24:]
        self._rrd_cache[key] = points
        return points
