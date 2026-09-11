"""Pydantic models for app configuration."""

from __future__ import annotations

import ipaddress
import pathlib
import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")
# hostname labels: 1-63 chars, start/end alnum, interior hyphens, dots separate
_HOSTNAME_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


def _parse_host_port(raw: str) -> tuple[str, int]:
    raw = raw.strip()
    raw = re.sub(r"^https?://", "", raw)
    raw = raw.strip("/")
    if ":" in raw:
        host, port_s = raw.rsplit(":", 1)
        try:
            return host, int(port_s)
        except ValueError:
            return host, 8006
    return raw, 8006


class ThemeMode(str, Enum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


class AuthMode(str, Enum):
    TOKEN = "token"
    PASSWORD = "password"


class ClusterConfig(BaseModel):
    """Single Proxmox cluster / endpoint.

    Secrets (token_value / password) are NOT stored here — they live in keyring.
    """

    id: str = Field(description="Unique id, e.g. 'pve-home'")
    name: str = Field(description="Display name")
    host: str = Field(description="Hostname or IP, e.g. '192.168.1.10'")
    port: int = Field(default=8006, ge=1, le=65535)
    verify_ssl: bool = Field(default=True, description="Verify TLS; turn off for self-signed")
    auth_mode: AuthMode = Field(default=AuthMode.TOKEN)
    token_id: str = Field(default="", description="Full token id e.g. 'root@pam!widget'")
    username: str = Field(
        default="root@pam", description="Username for password auth, e.g. root@pam"
    )
    # remote access — ssh opens in the user's own terminal with system keys, so
    # only the account name and port are remembered here, never credentials
    ssh_user: str = Field(default="root", description="Login name for SSH to nodes and LXC")
    ssh_port: int = Field(default=22, ge=1, le=65535, description="SSH port on host and nodes")
    rdp_user: str = Field(
        default="", description="Pre-fill RDP username; empty lets the client ask"
    )
    rdp_port: int = Field(default=3389, ge=1, le=65535, description="RDP port on guests")
    ca_bundle: str | None = Field(default=None, description="Path to CA bundle file")

    @field_validator("id", mode="before")
    @classmethod
    def _validate_id(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("id must be a string")
        # do not silently trim inner spaces - regex will reject
        if not _ID_RE.match(v):
            raise ValueError(
                "id must match ^[a-z0-9][a-z0-9_-]{1,31}$ (2-32 chars, lower alnum start)"
            )
        return v

    @field_validator("host")
    @classmethod
    def _validate_host(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("host must be a string")
        raw = v.strip()
        if not raw:
            raise ValueError("host must not be empty")
        # reject any internal whitespace immediately
        if re.search(r"\s", raw):
            raise ValueError("host must not contain whitespace")
        # strip scheme for checks
        stripped = re.sub(r"^https?://", "", raw)
        # reject inner "/" (allow only trailing slashes)
        if "/" in stripped.strip("/"):
            raise ValueError("host must not contain '/'")
        # handle bracketed IPv6 [::1]:port
        bracket_m = re.match(r"^\[([^\]]+)\](?::\d+)?/?$", stripped.strip("/"))
        if bracket_m:
            host_candidate = bracket_m.group(1)
            try:
                ipaddress.ip_address(host_candidate)
                return host_candidate.lower()
            except ValueError as e:
                raise ValueError("invalid host") from e
        # try raw IPv6 without brackets before port parsing
        # if stripped looks like IPv6, try ip_address directly
        no_trail = stripped.strip("/")
        # count colons: IPv6 has at least 2 colons
        if no_trail.count(":") >= 2:
            # could be IPv6 without port; try as IP
            try:
                ipaddress.ip_address(no_trail)
                return no_trail.lower()
            except ValueError:
                # maybe IPv6 with port without brackets is ambiguous; fall through to port parsing
                pass
        # use shared parser to strip scheme and trailing slashes and extract port
        parsed_host, _port = _parse_host_port(raw)
        # reject "/" and any whitespace in the parsed host
        if "/" in parsed_host:
            raise ValueError("host must not contain '/'")
        if re.search(r"\s", parsed_host):
            raise ValueError("host must not contain whitespace")
        host_lower = parsed_host.lower()
        if not host_lower:
            raise ValueError("host must not be empty")
        # try IP first
        try:
            ipaddress.ip_address(host_lower)
            return host_lower
        except ValueError:
            pass
        # hostname via idna
        try:
            ascii_host = host_lower.encode("idna").decode("ascii")
        except Exception as e:
            raise ValueError(f"invalid host: {e}") from e
        if len(ascii_host) > 253:
            raise ValueError("host too long")
        if not _HOSTNAME_RE.match(ascii_host):
            raise ValueError("invalid hostname")
        # each label <=63 already enforced by regex, but double-check
        for label in ascii_host.split("."):
            if len(label) > 63 or not label:
                raise ValueError("invalid hostname label")
        return host_lower

    @field_validator("ca_bundle")
    @classmethod
    def _validate_ca_bundle(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("ca_bundle must be a string or null")
        # empty string treated as None? spec says str|None, but empty should be rejected if not existing
        # allow empty to be treated as None for compat
        if v == "":
            return None
        p = pathlib.Path(v)
        if not p.exists():
            raise ValueError(f"ca_bundle path does not exist: {v}")
        return v

    @model_validator(mode="after")
    def _check_token_id(self) -> ClusterConfig:
        if self.auth_mode == AuthMode.TOKEN and self.token_id and "!" not in self.token_id:
            raise ValueError(
                'token_id must contain "!" when auth_mode is TOKEN (e.g. "user@realm!token")'
            )
        return self

    @property
    def base_url(self) -> str:
        scheme = "https"
        return f"{scheme}://{self.host}:{self.port}"

    @property
    def api_url(self) -> str:
        return f"{self.base_url}/api2/json"


class AppSettings(BaseModel):
    """Persisted app settings (JSON via platformdirs)."""

    clusters: list[ClusterConfig] = Field(default_factory=list)
    refresh_interval_seconds: int = Field(default=30, ge=5, le=3600)
    theme: ThemeMode = Field(default=ThemeMode.SYSTEM)
    notifications_enabled: bool = Field(default=True)
    start_minimized: bool = Field(default=True)
    close_to_tray: bool = Field(default=True)

    # UI state
    window_geometry: str | None = Field(default=None)

    config_version: int = Field(default=2)

    @model_validator(mode="before")
    @classmethod
    def _migrate_config_version(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "config_version" not in data:
            data["config_version"] = 2
        # migrate old clusters without ca_bundle key
        clusters = data.get("clusters")
        if isinstance(clusters, list):
            for item in clusters:
                if isinstance(item, dict) and "ca_bundle" not in item:
                    item["ca_bundle"] = None
        return data


class ProxmoxNode(BaseModel):
    node: str
    status: Literal["online", "offline", "unknown"] = "unknown"
    cpu: float = Field(default=0, ge=0, le=1, description="0..1")
    maxcpu: int = 0
    mem: int = 0
    maxmem: int = 0
    disk: int = 0
    maxdisk: int = 0
    uptime: int = 0
    pve_version: str | None = None

    @field_validator("cpu", mode="before")
    @classmethod
    def _clamp_cpu(cls, v: object) -> float:
        try:
            f = float(v or 0)  # type: ignore[arg-type]
            return max(0.0, min(1.0, f))
        except Exception:
            return 0.0


class QemuVm(BaseModel):
    vmid: int
    name: str
    node: str
    status: Literal["running", "stopped", "paused", "unknown"] = "unknown"
    cpus: int = 0
    cpu: float = Field(default=0, ge=0, le=1)
    mem: int = 0
    maxmem: int = 0
    disk: int = 0
    maxdisk: int = 0
    uptime: int = 0
    template: bool = False


class LxcContainer(BaseModel):
    vmid: int
    name: str
    node: str
    status: Literal["running", "stopped", "unknown"] = "unknown"
    cpus: int = 0
    cpu: float = Field(default=0, ge=0, le=1)
    mem: int = 0
    maxmem: int = 0
    disk: int = 0
    maxdisk: int = 0
    uptime: int = 0


class StorageStatus(BaseModel):
    storage: str
    node: str
    type: str = ""
    status: str = "unknown"
    total: int = 0
    used: int = 0
    avail: int = 0
    enabled: bool = True
    shared: bool = False


class ClusterHealth(BaseModel):
    cluster_id: str
    cluster_name: str
    online: bool
    error: str | None = None
    nodes: list[ProxmoxNode] = Field(default_factory=list)
    vms: list[QemuVm] = Field(default_factory=list)
    containers: list[LxcContainer] = Field(default_factory=list)
    storages: list[StorageStatus] = Field(default_factory=list)
