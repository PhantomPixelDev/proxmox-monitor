from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from proxmox_widget.config.models import ClusterHealth
from proxmox_widget.resources.icons import make_app_icon
from proxmox_widget.utils.format import fmt_bytes, fmt_uptime

ICONS = {
    "cluster": "🏢",
    "node": "🖥️",
    "vm": "🖥️",
    "ct": "📦",
    "storage": "💾",
    "cpu": "⚡",
    "ram": "🧠",
    "disk": "💽",
    "uptime": "⏱️",
    "status": "●",
    "net": "🌐",
    "health": "💚",
    "warn": "⚠️",
    "offline": "🔴",
    "online": "🟢",
    "paused": "🟡",
}


class Dashboard(QWidget):
    open_settings = Signal()
    open_proxmox_requested = Signal()
    action_requested = Signal(str, str, int, str, bool)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("root")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Popup | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFixedWidth(440)
        self.setMinimumHeight(560)
        self.setMaximumHeight(800)
        self._health: list[ClusterHealth] = []
        self._busy: dict[tuple[str, int, bool], str] = {}
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 14)
        root.setSpacing(10)
        self._banner = QFrame()
        self._banner.setObjectName("banner")
        self._banner.setVisible(False)
        self._banner.setStyleSheet("QFrame#banner { background: #2a2d45; border: 1px solid #3a3d53; border-radius: 8px; }")
        bl = QHBoxLayout(self._banner)
        bl.setContentsMargins(10, 8, 10, 8)
        bl.setSpacing(8)
        self._banner_icon = QLabel()
        self._banner_icon.setFixedWidth(18)
        bl.addWidget(self._banner_icon, 0)
        self._banner_label = QLabel()
        self._banner_label.setWordWrap(True)
        self._banner_label.setStyleSheet("font-size: 12px; font-weight: 500;")
        bl.addWidget(self._banner_label, 1)
        self._banner_close = QPushButton("✕")
        self._banner_close.setFixedSize(22, 22)
        self._banner_close.setObjectName("ghost")
        self._banner_close.setStyleSheet("font-size: 11px; padding: 0px;")
        self._banner_close.clicked.connect(lambda: self._banner.setVisible(False))
        bl.addWidget(self._banner_close, 0)
        root.addWidget(self._banner)
        from PySide6.QtCore import QTimer as _QTimer
        self._banner_timer = _QTimer(self)
        self._banner_timer.setSingleShot(True)
        self._banner_timer.timeout.connect(lambda: self._banner.setVisible(False))

        header = QHBoxLayout()
        header.setSpacing(10)
        # app icon
        icon_lbl = QLabel()
        icon_lbl.setPixmap(make_app_icon(28).pixmap(28, 28))
        icon_lbl.setFixedSize(28, 28)
        icon_lbl.setStyleSheet("background: transparent;")
        header.addWidget(icon_lbl, 0)
        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        title = QLabel("ProxmoxWidget")
        title.setObjectName("title")
        subtitle = QLabel("live infrastructure  •  least-priv ready")
        subtitle.setObjectName("subtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col, 1)
        header.addStretch()
        btn_settings = QPushButton("⚙")
        btn_settings.setObjectName("ghost")
        btn_settings.setFixedSize(36, 36)
        btn_settings.setToolTip("Settings")
        btn_settings.clicked.connect(lambda: self.open_settings.emit())
        header.addWidget(btn_settings)
        root.addLayout(header)

        sep = QFrame()
        sep.setObjectName("lineSep")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        root.addWidget(sep)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        self.tab_dashboard = QWidget()
        self.tab_nodes = QWidget()
        self.tab_vms = QWidget()
        self.tab_cts = QWidget()
        self.tab_storage = QWidget()

        self.tabs.addTab(self._wrap_scroll(self.tab_dashboard), "Dashboard")
        self.tabs.addTab(self._wrap_scroll(self.tab_nodes), "Nodes")
        self.tabs.addTab(self._wrap_scroll(self.tab_vms), "VMs")
        self.tabs.addTab(self._wrap_scroll(self.tab_cts), "Containers")
        self.tabs.addTab(self._wrap_scroll(self.tab_storage), "Storage")

        for w in [self.tab_dashboard, self.tab_nodes, self.tab_vms, self.tab_cts, self.tab_storage]:
            lay = QVBoxLayout(w)
            lay.setContentsMargins(2, 6, 2, 6)
            lay.setSpacing(10)
            lay.addStretch()

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.btn_open = QPushButton("↗  Open Proxmox")
        self.btn_open.setObjectName("primary")
        self.btn_open.clicked.connect(lambda: self.open_proxmox_requested.emit())
        footer.addWidget(self.btn_open, 1)
        self.btn_refresh = QPushButton("↻")
        self.btn_refresh.setObjectName("ghost")
        self.btn_refresh.setFixedSize(40, 36)
        self.btn_refresh.setToolTip("Refresh now")
        self.btn_refresh.clicked.connect(lambda: self._placeholder_refresh())
        footer.addWidget(self.btn_refresh)
        root.addLayout(footer)

        self.lbl_status = QLabel("No clusters — open Settings → Add Cluster")
        self.lbl_status.setObjectName("muted")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setContentsMargins(2, 0, 2, 0)
        root.addWidget(self.lbl_status)

    def _wrap_scroll(self, w: QWidget) -> QScrollArea:
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setWidget(w)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sa.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        return sa

    def set_clusters(self, clusters: list) -> None:
        self._clusters = {c.id: c for c in clusters}
        if clusters:
            self.btn_open.setText(f"↗  Open {clusters[0].name}")
            self.btn_open.setToolTip(clusters[0].base_url)
            self.btn_open.setEnabled(True)
        else:
            self.btn_open.setText("↗  Open Proxmox")
            self.btn_open.setEnabled(False)

    def set_busy(self, cluster_id: str, vmid: int, is_lxc: bool, action: str | None) -> None:
        key = (cluster_id, vmid, is_lxc)
        if action is None:
            self._busy.pop(key, None)
        else:
            self._busy[key] = action
        self.update_health(self._health)

    def clear_busy(self) -> None:
        self._busy.clear()
        self.update_health(self._health)

    def show_message(self, text: str, kind: str = "info", duration_ms: int = 4000) -> None:
        colors = {"info": ("#89b4fa", "ℹ️"), "success": ("#a6e3a1", "✓"), "warning": ("#f9e2af", "⚠️"), "error": ("#f38ba8", "✕")}
        color, icon = colors.get(kind, ("#89b4fa", "ℹ️"))
        self._banner_icon.setText(icon)
        self._banner_icon.setStyleSheet(f"color: {color}; font-weight: 700;")
        self._banner_label.setText(text)
        self._banner_label.setStyleSheet(f"color: #cdd6f4; font-size: 12px;")
        self._banner.setStyleSheet(f"QFrame#banner {{ background: #2a2d45; border: 1px solid {color}; border-radius: 8px; }}")
        self._banner.setVisible(True)
        self._banner_timer.start(duration_ms)

    def _placeholder_refresh(self) -> None:
        self.show_message("Refreshing…", "info", 1500)

    def update_health(self, health: list[ClusterHealth]) -> None:
        self._health = health
        for w in [self.tab_dashboard, self.tab_nodes, self.tab_vms, self.tab_cts, self.tab_storage]:
            lay = w.layout()
            assert lay is not None
            while lay.count():
                item = lay.takeAt(0)
                if item and item.widget():
                    item.widget().deleteLater()
            lay.addStretch()

        if not health:
            self.lbl_status.setText("No clusters — Settings → Add Cluster (e.g. 192.168.10.2:8006)")
            return

        online_count = sum(1 for h in health if h.online)
        total_nodes = sum(len(h.nodes) for h in health)
        total_vms = sum(len(h.vms) for h in health)
        total_cts = sum(len(h.containers) for h in health)
        self.lbl_status.setText(f"{online_count}/{len(health)} clusters • {total_nodes} nodes • {total_vms} VMs • {total_cts} containers")

        for h in health:
            self._add_cluster_to_dashboard(h)
            self._add_nodes(h)
            self._add_vms(h)
            self._add_cts(h)
            self._add_storage(h)

    def _card(self, parent_layout: QVBoxLayout) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        try:
            from PySide6.QtWidgets import QGraphicsDropShadowEffect

            from PySide6.QtGui import QColor

            eff = QGraphicsDropShadowEffect(card)
            eff.setBlurRadius(18)
            eff.setOffset(0, 6)
            eff.setColor(QColor(0, 0, 0, 80))
            card.setGraphicsEffect(eff)
        except Exception:
            pass
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)
        parent_layout.insertWidget(parent_layout.count() - 1, card)
        return card, lay

    def _section_row(self, icon: str, title: str, badge: str | None = None, badge_color: str | None = None) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = QLabel(f"{icon}  {title}")
        lbl.setObjectName("cardTitle")
        row.addWidget(lbl, 1)
        if badge:
            b = QLabel(badge)
            b.setObjectName("badge")
            b.setFixedHeight(20)
            if badge_color:
                b.setStyleSheet(f"background: {badge_color}; color: white; border-radius: 8px; padding: 2px 8px; font-size: 10.5px; font-weight: 700;")
            row.addWidget(b, 0)
        return row

    def _add_cluster_to_dashboard(self, h: ClusterHealth) -> None:
        lay = self.tab_dashboard.layout()
        assert isinstance(lay, QVBoxLayout)
        _, card_lay = self._card(lay)
        dot = ICONS["online"] if h.online else ICONS["offline"]
        badge = "ONLINE" if h.online else "OFFLINE"
        color = "#2ecc71" if h.online else "#ff3b30"
        card_lay.addLayout(self._section_row(ICONS["cluster"], f"{h.cluster_name}", badge, color))
        sub = QLabel(f"{h.cluster_id}  ·  {len(h.nodes)} nodes")
        sub.setObjectName("muted")
        card_lay.addWidget(sub)
        if not h.online:
            err = QLabel(h.error or "Offline")
            err.setObjectName("muted")
            err.setWordWrap(True)
            err.setStyleSheet("color:#f38ba8;")
            card_lay.addWidget(err)
            return
        for n in h.nodes:
            ndot = ICONS["online"] if n.status == "online" else ICONS["offline"]
            line = QLabel(f"{ndot}  {n.node}  ·  {ICONS['uptime']} {fmt_uptime(n.uptime)}  ·  {ICONS['cpu']} {n.maxcpu}c")
            line.setObjectName("muted")
            card_lay.addWidget(line)
            for icon, label, val, oid in [(ICONS["cpu"], "CPU", n.cpu, ""), (ICONS["ram"], "RAM", n.mem / n.maxmem if n.maxmem else 0, "ram"), (ICONS["disk"], "Disk", n.disk / n.maxdisk if n.maxdisk else 0, "disk")]:
                row = QHBoxLayout()
                row.setSpacing(8)
                lk = QLabel(f"{icon} {label}")
                lk.setFixedWidth(58)
                lk.setObjectName("muted")
                row.addWidget(lk)
                bar = QProgressBar()
                if oid:
                    bar.setObjectName(oid)
                bar.setRange(0, 100)
                bar.setValue(int(val * 100))
                bar.setFormat(f"{int(val*100)}%")
                bar.setFixedHeight(14)
                row.addWidget(bar, 1)
                card_lay.addLayout(row)
        if h.vms or h.containers:
            sep = QFrame()
            sep.setObjectName("lineSep")
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setFixedHeight(1)
            card_lay.addWidget(sep)
            summ = QLabel(f"{ICONS['vm']} {len(h.vms)} VMs  ·  {ICONS['ct']} {len(h.containers)} containers  ·  {ICONS['storage']} {len(h.storages)} storages")
            summ.setObjectName("muted")
            card_lay.addWidget(summ)

    def _add_nodes(self, h: ClusterHealth) -> None:
        lay = self.tab_nodes.layout()
        assert isinstance(lay, QVBoxLayout)
        for n in h.nodes:
            _, cl = self._card(lay)
            dot = ICONS["online"] if n.status == "online" else ICONS["offline"]
            color = "#2ecc71" if n.status == "online" else "#ff3b30"
            cl.addLayout(self._section_row(ICONS["node"], n.node, n.status.upper(), color))
            sub = QLabel(f"{ICONS['cluster']} {h.cluster_name}  ·  {ICONS['cpu']} {n.maxcpu}c  ·  {ICONS['uptime']} {fmt_uptime(n.uptime)}")
            sub.setObjectName("muted")
            cl.addWidget(sub)
            for icon, label, used, total, oid in [(ICONS["cpu"], "CPU", n.cpu, 1.0, ""), (ICONS["ram"], "RAM", n.mem, n.maxmem, "ram"), (ICONS["disk"], "Disk", n.disk, n.maxdisk, "disk")]:
                pct = int(used * 100) if oid == "" else int(used / total * 100) if total else 0
                row = QHBoxLayout()
                row.setSpacing(8)
                lk = QLabel(f"{icon} {label}")
                lk.setFixedWidth(58)
                lk.setObjectName("muted")
                row.addWidget(lk)
                bar = QProgressBar()
                if oid:
                    bar.setObjectName(oid)
                bar.setRange(0, 100)
                bar.setValue(int(pct))
                bar.setFormat(f"{int(pct)}%")
                row.addWidget(bar, 1)
                cl.addLayout(row)
                if oid:
                    det = QLabel(f"{fmt_bytes(int(used))} / {fmt_bytes(int(total))}")
                    det.setObjectName("muted")
                    det.setStyleSheet("font-size: 10.5px; margin-left: 66px;")
                    cl.addWidget(det)
            cl.addWidget(self._kv(f"{ICONS['status']} Status", n.status))
            cl.addWidget(self._kv(f"{ICONS['uptime']} Uptime", fmt_uptime(n.uptime)))

    def _add_vms(self, h: ClusterHealth) -> None:
        lay = self.tab_vms.layout()
        assert isinstance(lay, QVBoxLayout)
        for vm in h.vms:
            _, cl = self._card(lay)
            busy = self._busy.get((h.cluster_id, vm.vmid, False))
            dot = ICONS["online"] if vm.status == "running" else ICONS["offline"] if vm.status == "stopped" else ICONS["paused"]
            head = QHBoxLayout()
            head.setSpacing(8)
            lbl_name = QLabel(f"{dot}  {vm.name}")
            lbl_name.setObjectName("cardTitle")
            lbl_name.setWordWrap(True)
            head.addWidget(lbl_name, 1)
            if busy:
                b = QLabel(f"⏳ {busy.upper()}")
                b.setStyleSheet("background:#f9e2af; color:#1e1e2e; border-radius:8px; padding:2px 8px; font-size:10.5px; font-weight:700;")
                b.setFixedWidth(88)
                b.setAlignment(Qt.AlignmentFlag.AlignCenter)
                head.addWidget(b, 0)
            lbl_id = QLabel(f"#{vm.vmid}")
            lbl_id.setObjectName("badge")
            lbl_id.setFixedWidth(62)
            lbl_id.setAlignment(Qt.AlignmentFlag.AlignCenter)
            head.addWidget(lbl_id, 0)
            cl.addLayout(head)
            if busy:
                prog = QProgressBar()
                prog.setRange(0, 0)
                prog.setFixedHeight(6)
                prog.setTextVisible(False)
                cl.addWidget(prog)
            loc = QLabel(f"{ICONS['cluster']} {h.cluster_name}  ·  {ICONS['node']} {vm.node}")
            loc.setObjectName("muted")
            cl.addWidget(loc)
            status_color = "#f9e2af" if busy else ("#2ecc71" if vm.status == "running" else "#ff3b30" if vm.status == "stopped" else "#f1c40f")
            status_txt = busy if busy else vm.status
            cl.addWidget(self._kv(f"{ICONS['status']} Status", f'<span style=\"color:{status_color}; font-weight:600;\">{status_txt}</span>' + ("  · template" if vm.template else "")))
            cl.addWidget(self._kv(f"{ICONS['cpu']} vCPUs", str(vm.cpus)))
            if vm.status == "running":
                for icon, label, used, total, oid in [(ICONS["cpu"], "CPU", vm.cpu, 1.0, ""), (ICONS["ram"], "RAM", vm.mem, vm.maxmem, "ram")]:
                    pct = int(used * 100) if oid == "" else int(used / total * 100) if total else 0
                    row = QHBoxLayout()
                    row.setSpacing(8)
                    lk = QLabel(f"{icon} {label}")
                    lk.setFixedWidth(58)
                    lk.setObjectName("muted")
                    row.addWidget(lk)
                    bar = QProgressBar()
                    if oid:
                        bar.setObjectName(oid)
                    bar.setRange(0, 100)
                    bar.setValue(pct)
                    bar.setFormat(f"{pct}%")
                    row.addWidget(bar, 1)
                    cl.addLayout(row)
            else:
                cl.addWidget(self._kv(f"{ICONS['cpu']} CPU", f"{vm.cpu*100:.0f}%"))
                cl.addWidget(self._kv(f"{ICONS['ram']} RAM", f"{fmt_bytes(vm.mem)} / {fmt_bytes(vm.maxmem)}"))
            row = QHBoxLayout()
            row.setSpacing(6)
            for label, act in [("▶ Start", "start"), ("⏹ Stop", "stop"), ("↻ Reboot", "reboot")]:
                b = QPushButton(label)
                b.setFixedHeight(30)
                b.setEnabled(vm.status != "unknown" and not busy)
                b.clicked.connect(lambda _=False, a=act, vm=vm: self.action_requested.emit(h.cluster_id, vm.node, vm.vmid, a, False))
                row.addWidget(b, 1)
            cl.addLayout(row)

    def _add_cts(self, h: ClusterHealth) -> None:
        lay = self.tab_cts.layout()
        assert isinstance(lay, QVBoxLayout)
        for ct in h.containers:
            _, cl = self._card(lay)
            busy = self._busy.get((h.cluster_id, ct.vmid, True))
            dot = ICONS["online"] if ct.status == "running" else ICONS["offline"]
            head = QHBoxLayout()
            head.setSpacing(8)
            lbl_name = QLabel(f"{dot}  {ct.name}")
            lbl_name.setObjectName("cardTitle")
            lbl_name.setWordWrap(True)
            head.addWidget(lbl_name, 1)
            if busy:
                b = QLabel(f"⏳ {busy.upper()}")
                b.setStyleSheet("background:#f9e2af; color:#1e1e2e; border-radius:8px; padding:2px 8px; font-size:10.5px; font-weight:700;")
                b.setFixedWidth(88)
                b.setAlignment(Qt.AlignmentFlag.AlignCenter)
                head.addWidget(b, 0)
            lbl_id = QLabel(f"#{ct.vmid}")
            lbl_id.setObjectName("badge")
            lbl_id.setFixedWidth(62)
            lbl_id.setAlignment(Qt.AlignmentFlag.AlignCenter)
            head.addWidget(lbl_id, 0)
            cl.addLayout(head)
            if busy:
                prog = QProgressBar()
                prog.setRange(0, 0)
                prog.setFixedHeight(6)
                prog.setTextVisible(False)
                cl.addWidget(prog)
            loc = QLabel(f"{ICONS['cluster']} {h.cluster_name}  ·  {ICONS['node']} {ct.node}")
            loc.setObjectName("muted")
            cl.addWidget(loc)
            color = "#f9e2af" if busy else ("#2ecc71" if ct.status == "running" else "#ff3b30")
            status_txt = busy if busy else ct.status
            cl.addWidget(self._kv(f"{ICONS['status']} Status", f'<span style=\"color:{color}; font-weight:600;\">{status_txt}</span>'))
            if ct.status == "running":
                for icon, label, used, total, oid in [(ICONS["cpu"], "CPU", ct.cpu, 1.0, ""), (ICONS["ram"], "RAM", ct.mem, ct.maxmem, "ram")]:
                    pct = int(used * 100) if oid == "" else int(used / total * 100) if total else 0
                    row = QHBoxLayout()
                    row.setSpacing(8)
                    lk = QLabel(f"{icon} {label}")
                    lk.setFixedWidth(58)
                    lk.setObjectName("muted")
                    row.addWidget(lk)
                    bar = QProgressBar()
                    if oid:
                        bar.setObjectName(oid)
                    bar.setRange(0, 100)
                    bar.setValue(pct)
                    bar.setFormat(f"{pct}%")
                    row.addWidget(bar, 1)
                    cl.addLayout(row)
            else:
                cl.addWidget(self._kv(f"{ICONS['ram']} RAM", f"{fmt_bytes(ct.mem)} / {fmt_bytes(ct.maxmem)}"))
            row = QHBoxLayout()
            row.setSpacing(6)
            for label, act in [("▶ Start", "start"), ("⏹ Stop", "stop"), ("↻ Reboot", "reboot")]:
                b = QPushButton(label)
                b.setFixedHeight(30)
                b.setEnabled(not busy)
                b.clicked.connect(lambda _=False, a=act, ct=ct: self.action_requested.emit(h.cluster_id, ct.node, ct.vmid, a, True))
                row.addWidget(b, 1)
            cl.addLayout(row)

    def _add_storage(self, h: ClusterHealth) -> None:
        lay = self.tab_storage.layout()
        assert isinstance(lay, QVBoxLayout)
        for s in h.storages:
            _, cl = self._card(lay)
            cl.addLayout(self._section_row(ICONS["storage"], s.storage, s.type.upper()))
            sub = QLabel(f"{ICONS['node']} {s.node}  ·  {ICONS['status']} {s.status}  ·  {'🔗 shared' if s.shared else '📌 local'}")
            sub.setObjectName("muted")
            cl.addWidget(sub)
            used_pct = (s.used / s.total * 100) if s.total else 0
            row = QHBoxLayout()
            row.setSpacing(8)
            lk = QLabel(f"{ICONS['disk']} Use")
            lk.setFixedWidth(58)
            lk.setObjectName("muted")
            row.addWidget(lk)
            bar = QProgressBar()
            bar.setObjectName("disk")
            bar.setRange(0, 100)
            bar.setValue(int(used_pct))
            bar.setFormat(f"{used_pct:.0f}%")
            row.addWidget(bar, 1)
            cl.addLayout(row)
            det = QLabel(f"{fmt_bytes(s.used)} / {fmt_bytes(s.total)}  ·  {fmt_bytes(s.avail)} free")
            det.setObjectName("muted")
            det.setStyleSheet("font-size: 10.5px; margin-left: 66px;")
            cl.addWidget(det)
            if not s.enabled:
                warn = QLabel(f"{ICONS['warn']} disabled")
                warn.setStyleSheet("color: #f38ba8; font-size: 11px; font-weight: 600;")
                cl.addWidget(warn)

    def _kv(self, k: str, v: str) -> QLabel:
        row = QLabel(f"{k}  ·  {v}")
        row.setObjectName("muted")
        row.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.setWordWrap(True)
        return row
