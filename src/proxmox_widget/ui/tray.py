from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from proxmox_widget.config.models import ClusterHealth
from proxmox_widget.core import launcher
from proxmox_widget.ui import icons
from proxmox_widget.ui.themes import DARK, palette_for


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
        self._health: list[ClusterHealth] = []
        self._theme: str = "dark"
        self._menu: QMenu | None = None
        self._open_menu: QMenu | None = None
        self._build_menu()
        self.tray.show()

    def _build_menu(self) -> None:
        m = QMenu()
        pal = palette_for(self._theme, True)
        ink = pal.get("text_dim", DARK["text_dim"])
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
        self.act_quit = act_quit
        self.tray.setContextMenu(m)
        self._menu = m

    def rebuild_icons(self, theme: str = "dark") -> None:
        self._theme = theme
        pal = palette_for(theme, True)
        ink = pal.get("text_dim", DARK["text_dim"])
        if hasattr(self, "act_show"):
            self.act_show.setIcon(icons.icon("vm", 15, ink))
        if hasattr(self, "act_refresh"):
            self.act_refresh.setIcon(icons.icon("refresh", 15, ink))
        if hasattr(self, "act_settings"):
            self.act_settings.setIcon(icons.icon("settings", 15, ink))
        if hasattr(self, "act_quit"):
            self.act_quit.setIcon(icons.icon("close", 15, ink))
        if self._open_menu is not None:
            self._open_menu.setIcon(icons.icon("external", 15, ink))
        # also refresh open menu in case ink matters there in future
        # do not rebuild full menu to avoid losing signal connections for top actions

    def _rebuild_open_menu(self) -> None:
        if self._open_menu is None:
            return
        self._open_menu.clear()
        if not self._clusters:
            a = QAction("No clusters — add in Settings", self._open_menu)
            a.setEnabled(False)
            self._open_menu.addAction(a)
            return
        # build lookup for health by cluster_id
        health_by_id = {h.cluster_id: h for h in self._health}
        for c in self._clusters:
            h = health_by_id.get(c.id)
            is_online = h.online if h is not None else True
            # if we have no health yet, treat as online (no dot)
            if h is None and self._health:
                # health exists but not for this cluster -> offline?
                is_online = False
            elif h is None:
                is_online = True
            label = f"{c.name}  ({c.host}:{c.port})"
            if not is_online:
                label = f"● {label}"
                a = QAction(label, self._open_menu)
                a.setEnabled(False)
                err = h.error if h and h.error else "offline"
                a.setToolTip(err)
                self._open_menu.addAction(a)
            else:
                a = QAction(label, self._open_menu)
                a.triggered.connect(lambda _=False, url=c.base_url: launcher.open_url(url))
                self._open_menu.addAction(a)
        if len(self._clusters) == 1:
            self._open_menu.setTitle(f"Open {self._clusters[0].name}")

    def set_clusters(self, clusters: list) -> None:
        self._clusters = list(clusters)
        self._rebuild_open_menu()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
            QSystemTrayIcon.ActivationReason.MiddleClick,
            QSystemTrayIcon.ActivationReason.Context,
        ):
            self.show_dashboard.emit()

    def update_from_health(self, health: list[ClusterHealth]) -> None:
        # store health for offline dots in open menu
        self._health = list(health) if health else []
        if not health:
            self.tray.setToolTip("ProxmoxWidget — no clusters")
            self._rebuild_open_menu()
            return
        online = sum(1 for h in health if h.online)
        total = sum(len(h.vms) + len(h.containers) for h in health if h.online)
        running = sum(
            1 for h in health if h.online for g in (*h.vms, *h.containers) if g.status == "running"
        )
        tip = f"ProxmoxWidget — {online}/{len(health)} clusters online • {running}/{total} VMs running"
        self.tray.setToolTip(tip)
        self._rebuild_open_menu()

    def set_icon(self, icon: QIcon) -> None:
        self.tray.setIcon(icon)
