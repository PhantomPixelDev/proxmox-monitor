from __future__ import annotations

import time

from loguru import logger
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QSystemTrayIcon

from proxmox_widget.config.models import AppSettings, ClusterHealth


class Notifier(QObject):
    notification_requested = Signal(str, str)

    def __init__(
        self,
        tray: QSystemTrayIcon | None = None,
        settings: AppSettings | None = None,
    ) -> None:
        super().__init__()
        self._tray = tray
        self._settings = settings
        self._prev: dict[str, bool] = {}
        self._prev_vms: dict[str, str] = {}
        # per-key cooldown: key -> expiry monotonic (or last) timestamp
        self._cooldown: dict[str, float] = {}
        self._cooldown_sec: float = 300

    def attach_tray(self, tray: QSystemTrayIcon) -> None:
        self._tray = tray

    def set_settings(self, settings: AppSettings) -> None:
        self._settings = settings

    def _key(self, cid: str, vmid: int, is_lxc: bool) -> str:
        return f"{cid}:{'ct' if is_lxc else 'vm'}:{vmid}"

    def _is_cooldown(self, key: str) -> bool:
        now = time.monotonic()
        expiry = self._cooldown.get(key)
        if expiry is None:
            return False
        return now < expiry

    def _mark_cooldown(self, key: str) -> None:
        self._cooldown[key] = time.monotonic() + self._cooldown_sec

    def check(
        self,
        health_list: list[ClusterHealth],
        settings: AppSettings | bool | None = None,
    ) -> None:
        # Resolve notifications_enabled
        # Priority: explicit check param > self._settings
        notifications_enabled: bool | None = None
        if isinstance(settings, bool):
            notifications_enabled = settings
        elif isinstance(settings, AppSettings):
            notifications_enabled = settings.notifications_enabled
        elif self._settings is not None:
            notifications_enabled = self._settings.notifications_enabled
        else:
            notifications_enabled = True  # default enabled if no settings injected

        if notifications_enabled is False:
            for h in health_list:
                self._prev[h.cluster_id] = h.online
                for vm in h.vms:
                    key = self._key(h.cluster_id, vm.vmid, False)
                    self._prev_vms[key] = vm.status
                for ct in h.containers:
                    key = self._key(h.cluster_id, ct.vmid, True)
                    self._prev_vms[key] = ct.status
            return

        # collect cluster events with cooldown
        cluster_events: list[tuple[str, str]] = []
        for h in health_list:
            was_online = self._prev.get(h.cluster_id, True)
            if was_online and not h.online:
                ckey = f"{h.cluster_id}:cluster:offline"
                if not self._is_cooldown(ckey):
                    cluster_events.append(
                        (f"{h.cluster_name} offline", h.error or "Cluster unreachable")
                    )
                    self._mark_cooldown(ckey)
            elif not was_online and h.online:
                ckey = f"{h.cluster_id}:cluster:online"
                if not self._is_cooldown(ckey):
                    cluster_events.append(
                        (f"{h.cluster_name} back online", "Cluster reachable again")
                    )
                    self._mark_cooldown(ckey)
            self._prev[h.cluster_id] = h.online

        stopped: list[tuple[str, str, str]] = []
        for h in health_list:
            for vm in h.vms:
                key = self._key(h.cluster_id, vm.vmid, False)
                prev = self._prev_vms.get(key)
                cur = vm.status
                if (
                    prev
                    and prev != cur
                    and prev == "running"
                    and cur == "stopped"
                    and not self._is_cooldown(key)
                ):
                    stopped.append((key, f"{vm.name} stopped", f"VM {vm.vmid} on {h.cluster_name}"))
                self._prev_vms[key] = cur
            for ct in h.containers:
                key = self._key(h.cluster_id, ct.vmid, True)
                prev = self._prev_vms.get(key)
                cur = ct.status
                if (
                    prev
                    and prev != cur
                    and prev == "running"
                    and cur == "stopped"
                    and not self._is_cooldown(key)
                ):
                    stopped.append((key, f"{ct.name} stopped", f"CT {ct.vmid} on {h.cluster_name}"))
                self._prev_vms[key] = ct.status

        # emit cluster events individually (rare, not batched)
        for title, msg in cluster_events:
            self._notify(title, msg)

        # batch logic for stopped guests: >3 => summary 1
        if len(stopped) > 3:
            # mark cooldown for each involved key so they don't re-fire next poll
            for k, _, _ in stopped:
                self._mark_cooldown(k)
            summary_title = f"{len(stopped)} guests stopped"
            # also update summary cooldown to prevent spam
            batch_key = "batch:stopped"
            if not self._is_cooldown(batch_key):
                self._mark_cooldown(batch_key)
                self._notify(summary_title, f"{len(stopped)} guests stopped")
            return

        # emit individually and mark cooldown
        for k, title, msg in stopped:
            self._mark_cooldown(k)
            self._notify(title, msg)

    def _notify(self, title: str, msg: str) -> None:
        logger.info("notify: {} - {}", title, msg)
        # native toast when possible, else dashboard banner via signal
        tray = self._tray
        try:
            if tray is not None and hasattr(tray, "supportsMessages"):
                # QSystemTrayIcon.supportsMessages is static, but also instance callable
                supports = False
                try:
                    # try instance
                    supports = bool(tray.supportsMessages())  # type: ignore[call-arg]
                except Exception:
                    try:
                        supports = bool(QSystemTrayIcon.supportsMessages())
                    except Exception:
                        supports = False
                if supports:
                    try:
                        tray.showMessage(title, msg, QSystemTrayIcon.MessageIcon.Information, 3000)
                    except Exception:
                        pass
        except Exception:
            pass
        self.notification_requested.emit(title, msg)
