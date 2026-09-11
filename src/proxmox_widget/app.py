from __future__ import annotations

import asyncio
import base64
import sys
from collections.abc import Awaitable, Callable
from typing import Any, cast

from loguru import logger
from PySide6.QtCore import QByteArray, QObject, QTimer, Signal
from PySide6.QtGui import QIcon, QKeySequence
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

import proxmox_widget.ui.font_fix  # noqa: F401  # ensure QFont clamp at import
from proxmox_widget.api.client import ProxmoxClient
from proxmox_widget.config.manager import load_settings
from proxmox_widget.config.models import AppSettings, ClusterConfig, ClusterHealth
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


def _sanitize_error(err: object, limit: int = 150) -> str:
    """Banner-safe error text: never leaks host/token/secret."""
    raw = str(err) if err is not None else "Unknown error"
    low = raw.lower()
    if "token" in low or "secret" in low or "pveapitoken" in low:
        return "Authentication failed — check token and permissions"[:limit]
    if "certificate" in low or "fingerprint" in low:
        return "TLS verification failed — check host certificate"[:limit]
    if "host" in low or "connect" in low or "timeout" in low:
        # generic connectivity, avoid leaking host/ip
        detail = raw[:limit]
        # redact anything that looks like an IP/host:port by truncating anyway
        if len(detail) > limit:
            detail = detail[:limit]
        # strip bracketed cluster prefix but keep it: [id] is ok
        return detail if "[" in detail[:12] else "Connection failed — check host and network"
    return raw[:limit]


def _pick_icon() -> QIcon:
    return make_app_icon(256)


class ProxmoxWidgetApp(QObject):
    # emitted from the worker thread; Qt queues them onto the GUI thread
    message = Signal(str, str, int)

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app: QApplication = app
        self.settings: AppSettings = load_settings()
        self.app.setQuitOnLastWindowClosed(False)
        icon: QIcon = _pick_icon()
        self.app.setWindowIcon(icon)

        self.tray_icon: QSystemTrayIcon = QSystemTrayIcon(make_tray_icon(64, online=True), app)
        self.tray: TrayManager = TrayManager(self.tray_icon)

        self.dashboard: Dashboard = Dashboard()
        self.dashboard.setWindowIcon(icon)
        self.notifier: Notifier = Notifier(self.tray_icon, self.settings)

        self._health: list[ClusterHealth] = []
        self._browser_note_shown: bool = False
        self._refreshing: bool = False
        self._runner: AsyncRunner = AsyncRunner()
        self.app.aboutToQuit.connect(self._runner.stop)

        self._timer: QTimer = QTimer(self)
        self._timer.timeout.connect(self.refresh_now)
        self._apply_theme()
        self._wire()
        try:
            self.dashboard.set_close_to_tray(bool(self.settings.close_to_tray))
        except Exception:
            pass
        self._setup_shortcuts()
        self._setup_global_hotkey()

        if not self.settings.start_minimized:
            QTimer.singleShot(400, self.show_dashboard)

    # ----------------------------------------------------------------- wiring

    def _setup_shortcuts(self) -> None:
        try:
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QKeySequence, QShortcut

            sc = QShortcut(QKeySequence("Ctrl+K"), self.dashboard)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(self.dashboard._focus_search)
            self._sc_app_ctrl_k = sc
            sc2 = QShortcut(QKeySequence("Ctrl+,"), self.dashboard)
            sc2.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc2.activated.connect(self.show_settings)
            self._sc_app_ctrl_comma = sc2
            sc3 = QShortcut(QKeySequence("F5"), self.dashboard)
            sc3.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc3.activated.connect(self.refresh_now)
            self._sc_app_f5 = sc3
            sc4 = QShortcut(QKeySequence("Escape"), self.dashboard)
            sc4.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc4.activated.connect(self.dashboard._on_escape_shortcut)
            self._sc_app_escape = sc4
            sc5 = QShortcut(QKeySequence("Ctrl+Q"), self.dashboard)
            sc5.setContext(Qt.ShortcutContext.WindowShortcut)
            sc5.activated.connect(self.app.quit)
            self._sc_app_ctrl_q = sc5
        except Exception as e:
            logger.debug("app shortcuts setup failed: {}", _sanitize_error(e, 150))

    def _setup_global_hotkey(self) -> None:
        self._global_hotkey: Any = None
        try:
            try:
                from QHotkey import QHotkey  # type: ignore[import-not-found]
            except ImportError:
                try:
                    from qhotkey import QHotkey  # type: ignore[import-not-found, no-redef]
                except ImportError:
                    logger.info("global hotkey QHotkey not available, skipping")
                    return
            from typing import cast

            hk_any: Any = cast(Any, QHotkey)(QKeySequence("Ctrl+Shift+P"), True)
            hk: Any = hk_any
            if not cast(Any, hk).isRegistered():
                logger.warning("global hotkey Ctrl+Shift+P already registered, skipping")
                return
            cast(Any, hk).activated.connect(self.show_dashboard)
            self._global_hotkey = hk
            logger.info("global hotkey Ctrl+Shift+P registered")
        except Exception as e:
            logger.warning("global hotkey setup failed: {}", _sanitize_error(e, 150))

    def _wire(self) -> None:
        self.tray.show_dashboard.connect(self.show_dashboard)
        self.tray.show_settings.connect(self.show_settings)
        self.tray.refresh_requested.connect(self.refresh_now)
        self.tray.quit_requested.connect(self.app.quit)
        self.dashboard.open_settings.connect(self.show_settings)
        self.dashboard.open_proxmox_requested.connect(self._open_proxmox)
        self.dashboard.action_requested.connect(self._on_action)
        self.dashboard.console_requested.connect(self._on_console)
        self.dashboard.bulk_action_requested.connect(self._on_bulk_action)
        self.dashboard.refresh_requested.connect(self.refresh_now)
        self.notifier.notification_requested.connect(self._on_notify)
        self.message.connect(self.dashboard.show_message)
        from typing import cast

        cast(Any, self.tray).set_clusters(self.settings.clusters)
        cast(Any, self.dashboard).set_clusters(self.settings.clusters)

    def _spawn(
        self,
        factory: Callable[[], Awaitable[Any]],
        on_done: Callable[[Any], None] | None = None,
        on_error: Callable[[object], None] | None = None,
    ) -> None:
        self._runner.submit(factory, on_done, on_error)

    def _on_notify(self, title: str, msg: str) -> None:
        try:
            if self.tray_icon.supportsMessages():
                self.tray_icon.showMessage(title, msg, QSystemTrayIcon.MessageIcon.Information, 3000)
            else:
                raise RuntimeError("no native support")
        except Exception:
            kind = "warning" if "offline" in title.lower() or "stopped" in title.lower() else "info"
            self.dashboard.show_message(f"{title} — {msg}", kind, 5000)
        logger.info("notify {} {}", title, msg)

    def _apply_theme(self) -> None:
        try:
            from proxmox_widget.ui.font_fix import ensure_valid_app_font

            ensure_valid_app_font(self.app)
        except Exception:
            pass
        theme: str = self.settings.theme.value
        self.app.setStyleSheet(qss_for(theme))
        self.dashboard.apply_theme(theme)
        try:
            self.tray.rebuild_icons(theme)
        except Exception:
            pass

    def start(self) -> None:
        interval: int = max(5, self.settings.refresh_interval_seconds)
        self._timer.start(interval * 1000)
        self.refresh_now()

    # ------------------------------------------------------------------ views

    def show_dashboard(self) -> None:
        has_saved: bool = False
        try:
            saved: Any = self.dashboard._qsettings.value("dashboard/geometry")
            if saved is not None:
                try:
                    if isinstance(saved, QByteArray):
                        if not saved.isEmpty():
                            self.dashboard.restoreGeometry(saved)
                            has_saved = True
                    elif isinstance(saved, str) and saved:
                        try:
                            decoded = base64.b64decode(saved.encode("ascii"))
                            self.dashboard.restoreGeometry(QByteArray(decoded))
                            has_saved = True
                        except Exception:
                            pass
                    else:
                        is_empty: bool = bool(
                            cast(Any, saved).isEmpty() if hasattr(saved, "isEmpty") else not saved
                        )
                        if not is_empty:
                            cast(Any, self.dashboard).restoreGeometry(saved)
                            has_saved = True
                except Exception:
                    pass
            if not has_saved:
                b64: Any = self.dashboard._qsettings.value("dashboard/geometry_b64")
                if isinstance(b64, str) and b64:
                    try:
                        decoded = base64.b64decode(b64.encode("ascii"))
                        self.dashboard.restoreGeometry(QByteArray(decoded))
                        has_saved = True
                    except Exception:
                        pass
                elif isinstance(b64, QByteArray) and not b64.isEmpty():
                    try:
                        decoded = base64.b64decode(bytes(b64))
                        self.dashboard.restoreGeometry(QByteArray(decoded))
                        has_saved = True
                    except Exception:
                        try:
                            self.dashboard.restoreGeometry(b64)
                            has_saved = True
                        except Exception:
                            pass
        except Exception:
            pass
        self.dashboard.show()
        self.dashboard.raise_()
        self.dashboard.activateWindow()
        try:
            from PySide6.QtGui import QCursor, QGuiApplication

            pos = QCursor.pos()
            geo = self.dashboard.frameGeometry()
            screen = QGuiApplication.screenAt(pos)
            if screen is None:
                screen = QGuiApplication.primaryScreen()
            if screen is None:
                screen = self.app.primaryScreen()
            if screen is not None:
                dpr = float(screen.devicePixelRatio())
                avail = screen.availableGeometry()
                margin = int(8 * dpr) if dpr > 1.0 else 8
                margin = max(8, min(16, margin))
                if has_saved:
                    x = min(max(geo.x(), avail.x() + margin), avail.right() - geo.width() - margin)
                    y = min(
                        max(geo.y(), avail.y() + margin), avail.bottom() - geo.height() - margin
                    )
                    if x != geo.x() or y != geo.y():
                        self.dashboard.move(x, y)
                else:
                    x = min(
                        max(pos.x() - geo.width() // 2, avail.x() + margin),
                        avail.right() - geo.width() - margin,
                    )
                    y = min(
                        max(pos.y() - geo.height() - 20, avail.y() + margin),
                        avail.bottom() - geo.height() - margin,
                    )
                    self.dashboard.move(x, y)
        except Exception:
            pass

    def show_settings(self) -> None:
        dlg: SettingsDialog = SettingsDialog(self.settings, None)
        dlg.settings_saved.connect(self._on_settings_saved)
        dlg.test_requested.connect(self._on_test_cluster)
        dlg.exec()

    def _on_settings_saved(self, new_settings: AppSettings) -> None:
        self.settings = new_settings
        try:
            self.notifier.set_settings(new_settings)
        except Exception:
            pass
        try:
            self.dashboard.set_close_to_tray(bool(getattr(new_settings, "close_to_tray", True)))
        except Exception:
            pass
        cast(Any, self.tray).set_clusters(self.settings.clusters)
        cast(Any, self.dashboard).set_clusters(self.settings.clusters)
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
            on_error=lambda err: self._show_test_result(_sanitize_error(err, 200), False),
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
                c: ClusterConfig | None = next(
                    (x for x in self.settings.clusters if x.id == h.cluster_id), None
                )
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
        clusters: list[ClusterConfig] = list(self.settings.clusters)
        if not clusters:
            return []

        async def one(c: ClusterConfig) -> ClusterHealth:
            try:
                async with ProxmoxClient(c) as client:
                    return await client.fetch_health()
            except Exception as e:
                logger.warning("cluster {} failed: {}", c.id, _sanitize_error(e, 150))
                return ClusterHealth(
                    cluster_id=c.id, cluster_name=c.name, online=False, error=_sanitize_error(e, 150)
                )

        return list(await asyncio.gather(*(one(c) for c in clusters)))

    def _on_health(self, results: object) -> None:
        self._refreshing = False
        from typing import cast

        health: list[ClusterHealth] = cast(list[ClusterHealth], results) if isinstance(results, list) else []
        self._health = health
        self.dashboard.update_health(health)
        self.tray.update_from_health(health)
        online: int = sum(1 for h in health if h.online)
        alerts: int = sum(1 for h in health if not h.online)
        self.tray_icon.setIcon(make_tray_icon(64, online=(online > 0), alerts=alerts))
        self.notifier.check(health)

    def _on_fetch_failed(self, error: object) -> None:
        self._refreshing = False
        logger.warning("refresh failed: {}", _sanitize_error(error, 120))
        self.dashboard.show_message(f"Refresh failed: {_sanitize_error(error, 120)}", "error", 5000)

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

        if kind == "ssh":
            # SSH goes directly to the target, not via the PVE host
            if vmid == 0:
                # node card — SSH straight to that node
                target_host = node
                if not launcher.open_ssh(target_host, cluster.ssh_user, cluster.ssh_port):
                    self.dashboard.show_message(
                        "No ssh client found — install OpenSSH client", "error", 5000
                    )
                    return
                self.dashboard.show_message(
                    f"SSH to {cluster.ssh_user}@{target_host}", "info", 3000
                )
                return

            # guest (VM / LXC) — fetch its IP via the guest agent / interfaces, then SSH there
            self.dashboard.show_message("Asking the guest for its address…", "info", 2500)

            async def _ssh() -> str:
                async with ProxmoxClient(cluster) as c:
                    ips = await c.lxc_ips(node, vmid) if is_lxc else await c.agent_ips(node, vmid)
                target = launcher.pick_rdp_host(ips, near=cluster.host)
                if not target:
                    raise RuntimeError("The guest reported no usable IPv4 address")
                if not launcher.open_ssh(target, cluster.ssh_user, cluster.ssh_port):
                    raise RuntimeError("No ssh client found — install OpenSSH client")
                return f"{cluster.ssh_user}@{target}"

            self._spawn(
                _ssh,
                on_done=lambda t: self.dashboard.show_message(f"SSH to {t}", "success", 3000),
                on_error=self._on_console_failed,
            )
            return

        if kind in ("shell", "novnc", "lxc_shell"):
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
            self.dashboard.show_message("Asking the guest for its address…", "info", 2500)

            async def _rdp() -> str:
                async with ProxmoxClient(cluster) as c:
                    ips = await c.lxc_ips(node, vmid) if is_lxc else await c.agent_ips(node, vmid)
                target = launcher.pick_rdp_host(ips, near=cluster.host)
                if not target:
                    raise RuntimeError("The guest reported no usable IPv4 address")
                path = launcher.write_rdp_file(
                    launcher.build_rdp_file(target, cluster.rdp_port, cluster.rdp_user),
                    vmid,
                )
                if not launcher.open_rdp_file(path):
                    raise RuntimeError("No RDP client found (mstsc, xfreerdp, remmina)")
                return f"{target}:{cluster.rdp_port}"

            self._spawn(
                _rdp,
                on_done=lambda t: self._on_rdp_ready(str(t)),
                on_error=self._on_console_failed,
            )

    def _on_rdp_ready(self, target: str) -> None:
        self.dashboard.show_message(f"RDP to {target}", "success", 3000)

    def _on_spice_ready(self, path: object) -> None:
        logger.debug("spice file {}", path)
        self.dashboard.show_message("SPICE handed to remote-viewer", "success", 3000)
        path_str: str = str(path)
        QTimer.singleShot(SPICE_FILE_TTL_MS, lambda: cast(Any, launcher).discard(path_str))

    def _on_console_failed(self, error: object) -> None:
        logger.warning("console failed: {}", _sanitize_error(error, 120))
        self.dashboard.show_message(_sanitize_error(error, 170), "error", 7000)

    # ---------------------------------------------------------------- actions

    def _on_action(self, cluster_id: str, node: str, vmid: int, action: str, is_lxc: bool) -> None:
        cluster: ClusterConfig | None = next(
            (c for c in self.settings.clusters if c.id == cluster_id), None
        )
        if not cluster:
            return
        want: str = {
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
            on_error=lambda err: _finish(f"{action} failed: {_sanitize_error(err, 120)}", "error"),
        )

    def _on_bulk_action(self, action: str) -> None:
        if action in ("migrate", "snapshot"):
            self.dashboard.show_message(f"Bulk {action} not allowed", "error", 4000)
            return
        allowed = {"start", "stop", "shutdown", "reboot"}
        if action not in allowed:
            self.dashboard.show_message(f"Bulk {action} not allowed", "error", 4000)
            return
        selected = list(self.dashboard._selected)
        if not selected:
            self.dashboard.show_message("No guests selected", "warning", 3000)
            return
        items: list[tuple[str, str, int, bool]] = []
        for cid, vmid, is_lxc in selected:
            node: str | None = None
            for h in self._health:
                if h.cluster_id != cid:
                    continue
                guests = h.containers if is_lxc else h.vms
                for g in guests:
                    if g.vmid == vmid:
                        node = g.node
                        break
                if node:
                    break
            if node is None:
                continue
            items.append((cid, node, vmid, is_lxc))
        if not items:
            self.dashboard.show_message("No matching guests for bulk action", "warning", 3000)
            return
        for cid, _node, vmid, is_lxc in items:
            self.dashboard.set_busy(cid, vmid, is_lxc, action)
        self.dashboard.show_message(f"{action} {len(items)} guests…", "info", 2000)

        by_cluster: dict[str, list[tuple[str, int, bool]]] = {}
        for cid, node, vmid, is_lxc in items:
            by_cluster.setdefault(cid, []).append((node, vmid, is_lxc))

        async def _do_bulk() -> str:
            # pre-flight privilege gate per cluster
            for cid in list(by_cluster.keys()):
                cluster = next((c for c in self.settings.clusters if c.id == cid), None)
                if cluster is None:
                    raise RuntimeError(f"Cluster {cid} not found")
                async with ProxmoxClient(cluster) as cc:
                    if not await cc.has_privilege("VM.PowerMgmt"):
                        raise PermissionError(
                            f"Token lacks VM.PowerMgmt on {cid} — add it in Datacenter, Permissions"
                        )
            sem = asyncio.Semaphore(3)
            successes = 0
            failures: dict[str, int] = {}

            async def _one(cid: str, node: str, vmid: int, is_lxc: bool) -> None:
                nonlocal successes
                cluster = next((c for c in self.settings.clusters if c.id == cid), None)
                assert cluster is not None
                async with sem:
                    try:
                        async with ProxmoxClient(cluster) as client:
                            upid = await client.vm_action(node, vmid, action, is_lxc=is_lxc)
                            logger.info("bulk {} {} -> {}", action, vmid, upid)
                            # poll task status until not running
                            for _ in range(60):
                                st = await client.get_task_status(node, upid)
                                if st.lower() != "running":
                                    break
                                await asyncio.sleep(0.5)
                    except Exception as exc:
                        name = type(exc).__name__
                        failures[name] = failures.get(name, 0) + 1
                        logger.warning("bulk {} {} failed: {}", action, vmid, _sanitize_error(exc, 150))
                    else:
                        successes += 1

            await asyncio.gather(*[_one(cid, node, vmid, is_lxc) for cid, node, vmid, is_lxc in items])
            total = len(items)
            banner = f"{successes}/{total} succeeded"
            if failures:
                parts = ", ".join(f"{cnt}x {name}" for name, cnt in sorted(failures.items()))
                banner = f"{banner}, {parts}"
            return banner

        def _finish_bulk(text: str) -> None:
            for cid, _node, vmid, is_lxc in items:
                self.dashboard.set_busy(cid, vmid, is_lxc, None)
            kind = "success" if text.startswith(f"{len(items)}/{len(items)}") else ("warning" if "succeeded" in text and not text.startswith("0/") else "error")
            self.dashboard.show_message(text, kind, 5000)
            self.refresh_now()

        def _fail_bulk(err: object) -> None:
            for cid, _node, vmid, is_lxc in items:
                self.dashboard.set_busy(cid, vmid, is_lxc, None)
            self.dashboard.show_message(_sanitize_error(err, 200), "error", 5000)

        self._spawn(_do_bulk, on_done=lambda t: _finish_bulk(str(t)), on_error=_fail_bulk)


def _ensure_valid_app_font(app: QApplication) -> None:
    from proxmox_widget.ui.font_fix import ensure_valid_app_font as _central

    _central(app)


def create_app(argv: list[str] | None = None) -> tuple[QApplication, ProxmoxWidgetApp]:
    argv = argv if argv is not None else sys.argv
    try:
        from proxmox_widget.ui.font_fix import install_qfont_suppress_filter

        install_qfont_suppress_filter()
    except Exception:
        pass
    try:
        import proxmox_widget.ui.font_fix  # noqa: F401  # side-effect patch
    except Exception:
        pass
    app = QApplication(argv)
    _ensure_valid_app_font(app)
    try:
        from PySide6.QtGui import QFont as _QFont

        f = app.font()
        if f.pointSize() <= 0 and f.pixelSize() <= 0:
            nf = _QFont("Segoe UI", 9)
            if nf.pointSize() <= 0:
                nf.setPointSize(9)
            app.setFont(nf)
    except Exception:
        pass
    app.setApplicationName("ProxmoxWidget")
    app.setApplicationDisplayName("ProxmoxWidget")
    app.setOrganizationName("ProxmoxWidget")
    _ensure_valid_app_font(app)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        logger.warning("System tray not available")
    w = ProxmoxWidgetApp(app)
    return app, w
