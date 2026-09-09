from __future__ import annotations

import webbrowser

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from proxmox_widget.config.models import ClusterHealth


class TrayManager(QObject):
    show_dashboard = Signal()
    show_settings = Signal()
    quit_requested = Signal()
    refresh_requested = Signal()

    def __init__(self, tray: QSystemTrayIcon) -> None:
        super().__init__()
        self.tray = tray
        self.tray.setToolTip("ProxmoxWidget — no data yet")
        self.tray.activated.connect(self._on_activated)
        self._build_menu()
        self.tray.show()

    def _build_menu(self) -> None:
        m = QMenu()
        self.act_show = QAction("Show Dashboard", m)
        self.act_show.triggered.connect(lambda: self.show_dashboard.emit())
        m.addAction(self.act_show)

        self.act_refresh = QAction("↻ Refresh now", m)
        self.act_refresh.triggered.connect(lambda: self.refresh_requested.emit())
        m.addAction(self.act_refresh)

        m.addSeparator()
        self.act_open_pve = QAction("Open Proxmox → 192.168.10.2", m)
        self.act_open_pve.triggered.connect(lambda: webbrowser.open("https://192.168.10.2:8006"))
        m.addAction(self.act_open_pve)

        self.act_settings = QAction("⚙ Settings", m)
        self.act_settings.triggered.connect(lambda: self.show_settings.emit())
        m.addAction(self.act_settings)

        m.addSeparator()
        act_quit = QAction("Quit", m)
        act_quit.triggered.connect(lambda: self.quit_requested.emit())
        m.addAction(act_quit)

        self.tray.setContextMenu(m)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_dashboard.emit()

    def update_from_health(self, health: list[ClusterHealth]) -> None:
        if not health:
            self.tray.setToolTip("ProxmoxWidget — no clusters")
            return
        online = sum(1 for h in health if h.online)
        total_vms = sum(len(h.vms) for h in health if h.online)
        running = sum(1 for h in health for vm in h.vms if vm.status == "running")
        tip = f"ProxmoxWidget — {online}/{len(health)} clusters online • {running}/{total_vms} VMs running"
        self.tray.setToolTip(tip)
        # badge: we don't have real icon variants, use tooltip + message
        # icon could be swapped here based on health (green/red)

    def set_icon(self, icon: QIcon) -> None:
        self.tray.setIcon(icon)
