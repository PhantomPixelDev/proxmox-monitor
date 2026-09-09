"""Raw Proxmox API mapping helpers + re-exports."""

from __future__ import annotations

# Re-export typed models from config for convenience, plus raw mapping utilities
from proxmox_widget.config.models import ClusterHealth, LxcContainer, ProxmoxNode, QemuVm, StorageStatus

__all__ = ["ClusterHealth", "LxcContainer", "ProxmoxNode", "QemuVm", "StorageStatus"]
