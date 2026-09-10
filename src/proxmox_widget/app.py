from __future__ import annotations

import asyncio
import sys

from loguru import logger
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from proxmox_widget.api.client import ProxmoxClient
from proxmox_widget.config.manager import load_settings
from proxmox_widget.config.models import ClusterConfig, ClusterHealth
from proxmox_widget.core import launcher
from proxmox_widget.core.notifier import Notifier
from proxmox_widget.core.runner import AsyncRunner
from proxmox_widget.resources.icons import make_app_icon, make_tray_icon
from proxmox_widget.ui.dashboard import Dashboard
from proxmox_widget.ui.settings_dialog import SettingsDialog
from proxmox_widget.ui.themes import qss_for
from proxmox_widget.ui.tray import TrayManager

# how long remote-viewer gets to read the SPICE ticket before it is deleted
SPICE_FILE_TTL_MS = 30_000


def _pick_icon() -> QIcon:
    return make_app_icon(256)


class ProxmoxWidgetApp(QObject):
    # emitted from the worker thread; Qt queues them onto the GUI thread
    message = Signal(str, str, int)

    def __init__(self, app: QApplication) -> None:
        super().__init__()
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
        self._browser_note_shown = False
        self._refreshing = False
        self._runner = AsyncRunner()
        self.app.aboutToQuit.connect(self._runner.stop)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_now)
        self._apply_theme()
        self._wire()

        if not self.settings.start_minimized:
            QTimer.singleShot(400, self.show_dashboard)

    # ----------------------------------------------------------------- wiring

    def _wire(self) -> None:
        self.tray.show_dashboard.connect(self.show_dashboard)
        self.tray.show_settings.connect(self.show_settings)
        self.tray.refresh_requested.connect(self.refresh_now)
        self.tray.quit_requested.connect(self.app.quit)
        self.dashboard.open_settings.connect(self.show_settings)
        self.dashboard.open_proxmox_requested.connect(self._open_proxmox)
        self.dashboard.action_requested.connect(self._on_action)
        self.dashboard.console_requested.connect(self._on_console)
        self.dashboard.refresh_requested.connect(self.refresh_now)
        self.notifier.notification_requested.connect(self._on_notify)
        self.message.connect(self.dashboard.show_message)
        self.tray.set_clusters(self.settings.clusters)
        self.dashboard.set_clusters(self.settings.clusters)

    def _spawn(self, factory, on_done=None, on_error=None) -> None:  # type: ignore[no-untyped-def]
        """Run a coroutine on the worker loop, with GUI-thread callbacks."""
        self._runner.submit(factory, on_done, on_error)

    def _on_notify(self, title: str, msg: str) -> None:
        kind = "warning" if "offline" in title.lower() or "stopped" in title.lower() else "info"
        self.dashboard.show_message(f"{title} — {msg}", kind, 5000)
        logger.info("notify {} {}", title, msg)

    def _apply_theme(self) -> None:
        theme = self.settings.theme.value
        self.app.setStyleSheet(qss_for(theme))
        self.dashboard.apply_theme(theme)

    def start(self) -> None:
        interval = max(5, self.settings.refresh_interval_seconds)
        self._timer.start(interval * 1000)
        self.refresh_now()

    # ------------------------------------------------------------------ views

    def show_dashboard(self) -> None:
        self.dashboard.show()
        self.dashboard.raise_()
        self.dashboard.activateWindow()
        try:
            from PySide6.QtGui import QCursor

            pos = QCursor.pos()
            geo = self.dashboard.frameGeometry()
            screen = self.app.primaryScreen()
            if screen:
                avail = screen.availableGeometry()
                x = min(
                    max(pos.x() - geo.width() // 2, avail.x() + 8), avail.right() - geo.width() - 8
                )
                y = min(
                    max(pos.y() - geo.height() - 20, avail.y() + 8),
                    avail.bottom() - geo.height() - 8,
                )
                self.dashboard.move(x, y)
        except Exception:
            pass

    def show_settings(self) -> None:
        dlg = SettingsDialog(self.settings, None)
        dlg.settings_saved.connect(self._on_settings_saved)
        dlg.test_requested.connect(self._on_test_cluster)
        dlg.exec()

    def _on_settings_saved(self, new_settings) -> None:  # type: ignore[no-untyped-def]
        self.settings = new_settings
        self.tray.set_clusters(self.settings.clusters)
        self.dashboard.set_clusters(self.settings.clusters)
        self._apply_theme()
        self._timer.start(max(5, self.settings.refresh_interval_seconds) * 1000)
        self.refresh_now()

    def _on_test_cluster(self, cluster: ClusterConfig, secret: str) -> None:
        """Settings asked to check one endpoint before saving it."""

        async def _test() -> str:
            client = ProxmoxClient(cluster, secret=secret or None)
            async with client:
                version = await client.version()
                privs = await client.privileges()
            line = f"Connected to Proxmox VE {version}."
            if not privs:
                return f"{line} Could not read the token's privileges."
            missing = [p for p in ("VM.PowerMgmt", "VM.Console") if p not in privs]
            if not missing:
                return f"{line} The token can monitor, power guests and open SPICE."
            lacks = " and ".join(
                "power guests" if m == "VM.PowerMgmt" else "open SPICE" for m in missing
            )
            return (
                f"{line} Monitoring works, but the token cannot {lacks}: add {', '.join(missing)}."
            )

        self._spawn(
            _test,
            on_done=lambda text: self._show_test_result(str(text), True),
            on_error=lambda err: self._show_test_result(str(err)[:200], False),
        )

    def _show_test_result(self, text: str, ok: bool) -> None:
        for widget in self.app.topLevelWidgets():
            if isinstance(widget, SettingsDialog):
                widget.show_test_result(text, ok)

    def _open_proxmox(self) -> None:
        if not self.settings.clusters:
            return
        for h in self._health:
            if h.online:
                c = next((x for x in self.settings.clusters if x.id == h.cluster_id), None)
                if c:
                    launcher.open_url(c.base_url)
                    return
        launcher.open_url(self.settings.clusters[0].base_url)

    # ---------------------------------------------------------------- refresh

    def refresh_now(self) -> None:
        if self._refreshing:
            logger.debug("refresh already in flight, skipping")
            return
        self._refreshing = True
        self._spawn(self._fetch_all, self._on_health, self._on_fetch_failed)

    async def _fetch_all(self) -> list[ClusterHealth]:
        """Query every cluster at once. No Qt object is touched here."""
        clusters = list(self.settings.clusters)
        if not clusters:
            return []

        async def one(c: ClusterConfig) -> ClusterHealth:
            try:
                async with ProxmoxClient(c) as client:
                    return await client.fetch_health()
            except Exception as e:
                logger.warning("cluster {} failed: {}", c.id, e)
                return ClusterHealth(
                    cluster_id=c.id, cluster_name=c.name, online=False, error=str(e)
                )

        return list(await asyncio.gather(*(one(c) for c in clusters)))

    def _on_health(self, results: object) -> None:
        self._refreshing = False
        health = list(results) if isinstance(results, list) else []
        self._health = health
        self.dashboard.update_health(health)
        self.tray.update_from_health(health)
        online = sum(1 for h in health if h.online)
        alerts = sum(1 for h in health if not h.online)
        self.tray_icon.setIcon(make_tray_icon(64, online=(online > 0), alerts=alerts))
        self.notifier.check(health)

    def _on_fetch_failed(self, error: object) -> None:
        self._refreshing = False
        logger.error("refresh failed: {}", error)
        self.dashboard.show_message(f"Refresh failed: {str(error)[:150]}", "error", 5000)

    # --------------------------------------------------------------- consoles

    _BROWSER_LOGIN_NOTE = (
        "Opened in your browser. If Proxmox says 401 no ticket, log in there once — "
        "API tokens cannot create a browser session."
    )

    def _guest_name(self, cluster_id: str, vmid: int, is_lxc: bool) -> str:
        for h in self._health:
            if h.cluster_id != cluster_id:
                continue
            for g in h.containers if is_lxc else h.vms:
                if g.vmid == vmid:
                    return g.name
        return str(vmid)

    def _on_console(self, cluster_id: str, node: str, vmid: int, kind: str, is_lxc: bool) -> None:
        cluster = next((c for c in self.settings.clusters if c.id == cluster_id), None)
        if not cluster:
            return

        if kind in ("shell", "novnc"):
            client = ProxmoxClient(cluster)
            if kind == "shell":
                launcher.open_url(client.node_shell_url(node))
            else:
                name = self._guest_name(cluster_id, vmid, is_lxc)
                launcher.open_url(client.console_url(node, vmid, name, is_lxc=is_lxc))
            if self._browser_note_shown:
                self.dashboard.show_message("Console opened in your browser", "info", 2500)
            else:
                self._browser_note_shown = True
                self.dashboard.show_message(self._BROWSER_LOGIN_NOTE, "warning", 9000)
            return

        if kind == "spice":
            self.dashboard.show_message("Requesting a SPICE ticket…", "info", 2500)

            async def _spice() -> str:
                async with ProxmoxClient(cluster) as c:
                    if not await c.has_privilege("VM.Console"):
                        raise PermissionError(
                            "Token lacks VM.Console — add it in Datacenter, Permissions"
                        )
                    cfg = await c.spice_config(node, vmid)
                return str(launcher.open_spice(ProxmoxClient.spice_vv(cfg), vmid))

            self._spawn(_spice, on_done=self._on_spice_ready, on_error=self._on_console_failed)
            return

        if kind == "rdp":
            self.dashboard.show_message("Asking the guest agent for an IP…", "info", 2500)

            async def _rdp() -> str:
                async with ProxmoxClient(cluster) as c:
                    ips = await c.agent_ips(node, vmid)
                target = launcher.pick_rdp_host(ips, near=cluster.host)
                if not target:
                    raise RuntimeError("The guest agent reported no usable IPv4 address")
                if not launcher.open_rdp(target):
                    raise RuntimeError("No RDP client found (mstsc, xfreerdp, remmina)")
                return target

            self._spawn(
                _rdp,
                on_done=lambda ip: self.dashboard.show_message(f"RDP to {ip}", "success", 3000),
                on_error=self._on_console_failed,
            )

    def _on_spice_ready(self, path: object) -> None:
        logger.info("spice file {}", path)
        self.dashboard.show_message("SPICE handed to remote-viewer", "success", 3000)
        # the ticket inside is single use and short lived; do not leave it on disk
        QTimer.singleShot(SPICE_FILE_TTL_MS, lambda p=str(path): launcher.discard(p))

    def _on_console_failed(self, error: object) -> None:
        logger.error("console failed: {}", error)
        self.dashboard.show_message(str(error)[:170], "error", 7000)

    # ---------------------------------------------------------------- actions

    def _on_action(self, cluster_id: str, node: str, vmid: int, action: str, is_lxc: bool) -> None:
        cluster = next((c for c in self.settings.clusters if c.id == cluster_id), None)
        if not cluster:
            return
        want = {
            "start": "running",
            "stop": "stopped",
            "shutdown": "stopped",
            "reboot": "running",
        }.get(action, "running")

        self.dashboard.set_busy(cluster_id, vmid, is_lxc, action)
        self.dashboard.show_message(f"{action} {vmid} on {node}…", "info", 2000)

        async def _do() -> str:
            async with ProxmoxClient(cluster) as client:
                upid = await client.vm_action(node, vmid, action, is_lxc=is_lxc)
                logger.info("action {} {} -> {}", action, vmid, upid)
                self.message.emit(f"{action} sent, waiting for {want}…", "info", 2500)
                if await client.wait_for_guest(node, vmid, want, is_lxc=is_lxc, timeout=45):
                    return f"{vmid} is now {want}"
                current = await client.get_guest_status(node, vmid, is_lxc=is_lxc)
                raise TimeoutError(f"{vmid} is {current}, expected {want}")

        def _finish(text: str, kind: str) -> None:
            self.dashboard.show_message(text, kind, 4000)
            self.dashboard.set_busy(cluster_id, vmid, is_lxc, None)
            self.refresh_now()

        self._spawn(
            _do,
            on_done=lambda text: _finish(str(text), "success"),
            on_error=lambda err: _finish(f"{action} failed: {str(err)[:150]}", "error"),
        )


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
