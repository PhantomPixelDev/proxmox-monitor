from __future__ import annotations

import asyncio
import sys
import webbrowser

from loguru import logger
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from proxmox_widget.api.client import ProxmoxClient
from proxmox_widget.config.manager import load_settings
from proxmox_widget.config.models import ClusterHealth
from proxmox_widget.core.notifier import Notifier
from proxmox_widget.resources.icons import make_app_icon, make_tray_icon
from proxmox_widget.ui.dashboard import Dashboard
from proxmox_widget.ui.settings_dialog import SettingsDialog
from proxmox_widget.ui.themes import qss_for
from proxmox_widget.ui.tray import TrayManager


def _pick_icon() -> QIcon:
    return make_app_icon(256)


class ProxmoxWidgetApp:
    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.settings = load_settings()
        self.app.setQuitOnLastWindowClosed(False)
        icon = _pick_icon()
        self.app.setWindowIcon(icon)

        self.tray_icon = QSystemTrayIcon(make_tray_icon(64, online=True), app)
        self.tray = TrayManager(self.tray_icon)

        self.dashboard = Dashboard()
        self.dashboard.setWindowIcon(icon)
        self.notifier = Notifier(self.tray_icon)

        self._health: list[ClusterHealth] = []
        self._timer = QTimer()
        self._timer.timeout.connect(self._on_timer)
        self._apply_theme()
        self._wire()

        if not self.settings.start_minimized:
            QTimer.singleShot(400, self.show_dashboard)

    def _wire(self) -> None:
        self.tray.show_dashboard.connect(self.show_dashboard)
        self.tray.show_settings.connect(self.show_settings)
        self.tray.refresh_requested.connect(self.refresh_now)
        self.tray.quit_requested.connect(self.app.quit)
        self.dashboard.open_settings.connect(self.show_settings)
        self.dashboard.open_proxmox_requested.connect(self._open_proxmox)
        self.dashboard.action_requested.connect(self._on_action)
        self.notifier.notification_requested.connect(lambda t, m: logger.info("notify {} {}", t, m))
        self.tray.set_clusters(self.settings.clusters)
        self.dashboard.set_clusters(self.settings.clusters)

    def _apply_theme(self) -> None:
        qss = qss_for(self.settings.theme.value)
        self.app.setStyleSheet(qss)
        self.dashboard.setStyleSheet(qss)

    def start(self) -> None:
        interval = max(5, self.settings.refresh_interval_seconds)
        self._timer.start(interval * 1000)
        self.refresh_now()

    def show_dashboard(self) -> None:
        # position near tray: bottom-right
        self.dashboard.show()
        self.dashboard.raise_()
        self.dashboard.activateWindow()
        # try to place near cursor/tray
        try:
            from PySide6.QtGui import QCursor

            pos = QCursor.pos()
            geo = self.dashboard.frameGeometry()
            screen = self.app.primaryScreen()
            if screen:
                avail = screen.availableGeometry()
                x = min(max(pos.x() - geo.width() // 2, avail.x() + 8), avail.right() - geo.width() - 8)
                y = min(max(pos.y() - geo.height() - 20, avail.y() + 8), avail.bottom() - geo.height() - 8)
                self.dashboard.move(x, y)
        except Exception:
            pass

    def show_settings(self) -> None:
        dlg = SettingsDialog(self.settings, None)
        dlg.settings_saved.connect(self._on_settings_saved)
        dlg.exec()

    def _on_settings_saved(self, new_settings) -> None:  # type: ignore[no-untyped-def]
        self.settings = new_settings
        self.tray.set_clusters(self.settings.clusters)
        self.dashboard.set_clusters(self.settings.clusters)
        self._apply_theme()
        self._timer.start(max(5, self.settings.refresh_interval_seconds) * 1000)
        self.refresh_now()

    def _open_proxmox(self) -> None:
        import webbrowser as wb

        if not self.settings.clusters:
            return
        for h in self._health:
            if h.online:
                c = next((x for x in self.settings.clusters if x.id == h.cluster_id), None)
                if c:
                    wb.open(c.base_url)
                    return
        wb.open(self.settings.clusters[0].base_url)

    def _on_timer(self) -> None:
        self.refresh_now()

    def refresh_now(self) -> None:
        # run async fetch without blocking UI — use asyncio.to_thread style via singleShot
        # we launch an asyncio run in a QTimer 0
        QTimer.singleShot(0, self._kick_async)

    def _kick_async(self) -> None:
        try:
            asyncio.run(self._fetch_all())
        except RuntimeError:
            # if already in event loop (pytest), create new loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._fetch_all())

    async def _fetch_all(self) -> None:
        if not self.settings.clusters:
            self.dashboard.update_health([])
            self.tray.update_from_health([])
            return
        results: list[ClusterHealth] = []
        for c in self.settings.clusters:
            client = ProxmoxClient(c)
            try:
                h = await client.fetch_health()
            except Exception as e:
                h = ClusterHealth(cluster_id=c.id, cluster_name=c.name, online=False, error=str(e))
            results.append(h)
        self._health = results
        self.dashboard.update_health(results)
        self.tray.update_from_health(results)
        # update tray icon color/badging based on health
        online = sum(1 for h in results if h.online)
        alerts = sum(1 for h in results if not h.online)
        self.tray_icon.setIcon(make_tray_icon(64, online=(online > 0), alerts=alerts))
        self.notifier.check(results)

    def _on_action(self, cluster_id: str, node: str, vmid: int, action: str, is_lxc: bool) -> None:
        cluster = next((c for c in self.settings.clusters if c.id == cluster_id), None)
        if not cluster:
            return
        proxmox_action = {"start": "start", "stop": "stop", "reboot": "reboot", "shutdown": "shutdown"}.get(action, action)
        want_map = {"start": "running", "stop": "stopped", "shutdown": "stopped", "reboot": "running"}
        want = want_map.get(proxmox_action, "running")

        self.dashboard.set_busy(cluster_id, vmid, is_lxc, proxmox_action)
        self.tray.tray.showMessage("ProxmoxWidget", f"{proxmox_action} {vmid} on {node}…", QSystemTrayIcon.MessageIcon.Information, 2000)

        async def _do() -> None:
            client = ProxmoxClient(cluster)
            try:
                upid = await client.vm_action(node, vmid, proxmox_action, is_lxc=is_lxc)
                logger.info("action {} {} -> {}", proxmox_action, vmid, upid)
                self.tray.tray.showMessage("ProxmoxWidget", f"{proxmox_action} sent → waiting for {want}…", QSystemTrayIcon.MessageIcon.Information, 2500)
                ok = await client.wait_for_guest(node, vmid, want, is_lxc=is_lxc, timeout=45)
                if ok:
                    self.tray.tray.showMessage("ProxmoxWidget ✓", f"{vmid} is now {want}", QSystemTrayIcon.MessageIcon.Information, 3000)
                else:
                    full = await client.get_guest_status(node, vmid, is_lxc=is_lxc)
                    self.tray.tray.showMessage("ProxmoxWidget", f"{vmid} status: {full} (want {want})", QSystemTrayIcon.MessageIcon.Warning, 4000)
            except Exception as e:
                logger.error("action failed: {}", e)
                self.tray.tray.showMessage("ProxmoxWidget — failed", str(e)[:220], QSystemTrayIcon.MessageIcon.Critical, 5000)
            finally:
                self.dashboard.set_busy(cluster_id, vmid, is_lxc, None)
                for _ in range(3):
                    await self._fetch_all()
                    await asyncio.sleep(1.0)
                await self._fetch_all()

        def _run() -> None:
            try:
                asyncio.run(_do())
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(_do())

        QTimer.singleShot(0, _run)


def create_app(argv: list[str] | None = None) -> tuple[QApplication, ProxmoxWidgetApp]:
    argv = argv if argv is not None else sys.argv
    app = QApplication(argv)
    app.setApplicationName("ProxmoxWidget")
    app.setApplicationDisplayName("ProxmoxWidget")
    app.setOrganizationName("ProxmoxWidget")
    if not QSystemTrayIcon.isSystemTrayAvailable():
        logger.warning("System tray not available")
    w = ProxmoxWidgetApp(app)
    return app, w
