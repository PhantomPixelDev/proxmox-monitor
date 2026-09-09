"""Pydantic models for app configuration."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


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
    verify_ssl: bool = Field(default=False, description="Verify TLS; false for self-signed")
    auth_mode: AuthMode = Field(default=AuthMode.TOKEN)
    token_id: str = Field(default="", description="Full token id e.g. 'root@pam!widget'")
    username: str = Field(default="root@pam", description="Username for password auth, e.g. root@pam")

    @field_validator("host")
    @classmethod
    def _strip_host(cls, v: str) -> str:
        return v.strip().strip("/")

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
