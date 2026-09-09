from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QSystemTrayIcon
from loguru import logger

from proxmox_widget.config.models import ClusterHealth


class Notifier(QObject):
    notification_requested = Signal(str, str)

    def __init__(self, tray: QSystemTrayIcon | None = None) -> None:
        super().__init__()
        self._tray = tray
        self._prev: dict[str, bool] = {}
        self._prev_vms: dict[str, str] = {}

    def attach_tray(self, tray: QSystemTrayIcon) -> None:
        self._tray = tray

    def check(self, health_list: list[ClusterHealth]) -> None:
        for h in health_list:
            was_online = self._prev.get(h.cluster_id, True)
            if was_online and not h.online:
                self._notify(f"{h.cluster_name} offline", h.error or "Cluster unreachable")
            elif not was_online and h.online:
                self._notify(f"{h.cluster_name} back online", "Cluster reachable again")
            self._prev[h.cluster_id] = h.online

            for vm in [*h.vms, *h.containers]:  # type: ignore[arg-type]
                key = f"{h.cluster_id}:{vm.vmid}"
                prev = self._prev_vms.get(key)
                cur = vm.status
                if prev and prev != cur and prev == "running" and cur == "stopped":
                    self._notify(f"{vm.name} stopped", f"VM {vm.vmid} on {h.cluster_name}")
                self._prev_vms[key] = cur

    def _notify(self, title: str, msg: str) -> None:
        logger.info("notify: {} - {}", title, msg)
        self.notification_requested.emit(title, msg)
