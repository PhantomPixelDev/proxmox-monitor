from __future__ import annotations

import webbrowser

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from proxmox_widget.config.models import ClusterHealth
from proxmox_widget.ui import icons
from proxmox_widget.ui.themes import DARK


class TrayManager(QObject):
    show_dashboard = Signal()
    show_settings = Signal()
    quit_requested = Signal()
    refresh_requested = Signal()
    open_cluster_requested = Signal(str)

    def __init__(self, tray: QSystemTrayIcon) -> None:
        super().__init__()
        self.tray = tray
        self.tray.setToolTip("ProxmoxWidget — no data yet")
        self.tray.activated.connect(self._on_activated)
        self._clusters: list = []
        self._menu: QMenu | None = None
        self._open_menu: QMenu | None = None
        self._build_menu()
        self.tray.show()

    def _build_menu(self) -> None:
        m = QMenu()
        ink = DARK["text_dim"]
        self.act_show = QAction(icons.icon("vm", 15, ink), "Show Dashboard", m)
        self.act_show.triggered.connect(lambda: self.show_dashboard.emit())
        m.addAction(self.act_show)

        self.act_refresh = QAction(icons.icon("refresh", 15, ink), "Refresh now", m)
        self.act_refresh.triggered.connect(lambda: self.refresh_requested.emit())
        m.addAction(self.act_refresh)
        m.addSeparator()

        self._open_menu = m.addMenu("Open Proxmox")
        self._open_menu.setIcon(icons.icon("external", 15, ink))
        self._rebuild_open_menu()

        self.act_settings = QAction(icons.icon("settings", 15, ink), "Settings", m)
        self.act_settings.triggered.connect(lambda: self.show_settings.emit())
        m.addAction(self.act_settings)
        m.addSeparator()
        act_quit = QAction(icons.icon("close", 15, ink), "Quit", m)
        act_quit.triggered.connect(lambda: self.quit_requested.emit())
        m.addAction(act_quit)
        self.tray.setContextMenu(m)
        self._menu = m

    def _rebuild_open_menu(self) -> None:
        if self._open_menu is None:
            return
        self._open_menu.clear()
        if not self._clusters:
            a = QAction("No clusters — add in Settings", self._open_menu)
            a.setEnabled(False)
            self._open_menu.addAction(a)
            return
        for c in self._clusters:
            label = f"{c.name}  ({c.host}:{c.port})"
            a = QAction(label, self._open_menu)
            a.triggered.connect(lambda _=False, url=c.base_url: webbrowser.open(url))
            self._open_menu.addAction(a)
        if len(self._clusters) == 1:
            self._open_menu.setTitle(f"Open {self._clusters[0].name}")

    def set_clusters(self, clusters: list) -> None:
        self._clusters = list(clusters)
        self._rebuild_open_menu()

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

    def set_icon(self, icon: QIcon) -> None:
        self.tray.setIcon(icon)
