from __future__ import annotations

import webbrowser

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
from proxmox_widget.utils.format import fmt_bytes, fmt_uptime


class Dashboard(QWidget):
    open_settings = Signal()
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
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 14)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("ProxmoxWidget")
        title.setObjectName("title")
        subtitle = QLabel("live infrastructure")
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
        self.btn_open.clicked.connect(self._open_proxmox)
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

    def _open_proxmox(self) -> None:
        if not self._health:
            webbrowser.open("https://192.168.10.2:8006")
            return
        for h in self._health:
            if h.online:
                webbrowser.open(f"https://192.168.10.2:8006")
                return
        webbrowser.open("https://192.168.10.2:8006")

    def _placeholder_refresh(self) -> None:
        self.lbl_status.setText("Refreshing…")

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
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)
        parent_layout.insertWidget(parent_layout.count() - 1, card)
        return card, lay

    def _section_row(self, icon: str, title: str, badge: str | None = None) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = QLabel(f"{icon}  {title}")
        lbl.setObjectName("cardTitle")
        row.addWidget(lbl, 1)
        if badge:
            b = QLabel(badge)
            b.setObjectName("badge")
            b.setFixedHeight(20)
            row.addWidget(b, 0)
        return row

    def _add_cluster_to_dashboard(self, h: ClusterHealth) -> None:
        lay = self.tab_dashboard.layout()
        assert isinstance(lay, QVBoxLayout)
        _, card_lay = self._card(lay)
        dot = "🟢" if h.online else "🔴"
        badge = "ONLINE" if h.online else "OFFLINE"
        card_lay.addLayout(self._section_row(dot, f"{h.cluster_name}", badge))
        sub = QLabel(h.cluster_id)
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
            ndot = "🟢" if n.status == "online" else "🔴"
            line = QLabel(f"{ndot}  {n.node}  ·  {fmt_uptime(n.uptime)}")
            line.setObjectName("muted")
            card_lay.addWidget(line)
            for label, val, oid in [("CPU", n.cpu, ""), ("RAM", n.mem / n.maxmem if n.maxmem else 0, "ram"), ("Disk", n.disk / n.maxdisk if n.maxdisk else 0, "disk")]:
                row = QHBoxLayout()
                row.setSpacing(8)
                lk = QLabel(label)
                lk.setFixedWidth(34)
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
            summ = QLabel(f"{len(h.vms)} VMs  ·  {len(h.containers)} containers  ·  {len(h.storages)} storages")
            summ.setObjectName("muted")
            card_lay.addWidget(summ)

    def _add_nodes(self, h: ClusterHealth) -> None:
        lay = self.tab_nodes.layout()
        assert isinstance(lay, QVBoxLayout)
        for n in h.nodes:
            _, cl = self._card(lay)
            dot = "🟢" if n.status == "online" else "🔴"
            cl.addLayout(self._section_row(dot, n.node, n.status.upper()))
            sub = QLabel(f"{h.cluster_name}  ·  {n.maxcpu} cores  ·  {fmt_uptime(n.uptime)}")
            sub.setObjectName("muted")
            cl.addWidget(sub)
            for label, used, total, oid in [("CPU", n.cpu, 1.0, ""), ("RAM", n.mem, n.maxmem, "ram"), ("Disk", n.disk, n.maxdisk, "disk")]:
                pct = (used / total * 100) if total and oid else (used * 100 if oid == "" else 0)
                if oid == "":
                    pct = int(used * 100)
                else:
                    pct = int(used / total * 100) if total else 0
                row = QHBoxLayout()
                row.setSpacing(8)
                lk = QLabel(label)
                lk.setFixedWidth(34)
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
                    # human readable under bar
                    det = QLabel(f"{fmt_bytes(int(used))} / {fmt_bytes(int(total))}" if oid else f"{pct:.0f}%")
                    det.setObjectName("muted")
                    det.setStyleSheet("font-size: 10.5px; margin-left: 42px;")
                    cl.addWidget(det)
            cl.addWidget(self._kv("Status", n.status))
            cl.addWidget(self._kv("Uptime", fmt_uptime(n.uptime)))

    def _add_vms(self, h: ClusterHealth) -> None:
        lay = self.tab_vms.layout()
        assert isinstance(lay, QVBoxLayout)
        for vm in h.vms:
            _, cl = self._card(lay)
            dot = "🟢" if vm.status == "running" else "🔴" if vm.status == "stopped" else "🟡"
            head = QHBoxLayout()
            head.setSpacing(8)
            lbl_name = QLabel(f"{dot}  {vm.name}")
            lbl_name.setObjectName("cardTitle")
            lbl_name.setWordWrap(True)
            head.addWidget(lbl_name, 1)
            lbl_id = QLabel(f"#{vm.vmid}")
            lbl_id.setObjectName("badge")
            lbl_id.setFixedWidth(62)
            lbl_id.setAlignment(Qt.AlignmentFlag.AlignCenter)
            head.addWidget(lbl_id, 0)
            cl.addLayout(head)
            loc = QLabel(f"{h.cluster_name} · {vm.node}")
            loc.setObjectName("muted")
            cl.addWidget(loc)
            cl.addWidget(self._kv("Status", vm.status + ("  · template" if vm.template else "")))
            cl.addWidget(self._kv("vCPUs", str(vm.cpus)))
            # usage bars for running VMs
            if vm.status == "running":
                for label, used, total, oid in [("CPU", vm.cpu, 1.0, ""), ("RAM", vm.mem, vm.maxmem, "ram")]:
                    pct = int(used * 100) if oid == "" else int(used / total * 100) if total else 0
                    row = QHBoxLayout()
                    row.setSpacing(8)
                    lk = QLabel(label)
                    lk.setFixedWidth(34)
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
                cl.addWidget(self._kv("CPU", f"{vm.cpu*100:.0f}%"))
                cl.addWidget(self._kv("RAM", f"{fmt_bytes(vm.mem)} / {fmt_bytes(vm.maxmem)}"))
            row = QHBoxLayout()
            row.setSpacing(6)
            for label, act in [("▶ Start", "start"), ("⏹ Stop", "stop"), ("↻ Reboot", "reboot")]:
                b = QPushButton(label)
                b.setFixedHeight(30)
                b.setEnabled(vm.status != "unknown")
                b.clicked.connect(lambda _=False, a=act, vm=vm: self.action_requested.emit(h.cluster_id, vm.node, vm.vmid, a, False))
                row.addWidget(b, 1)
            cl.addLayout(row)

    def _add_cts(self, h: ClusterHealth) -> None:
        lay = self.tab_cts.layout()
        assert isinstance(lay, QVBoxLayout)
        for ct in h.containers:
            _, cl = self._card(lay)
            dot = "🟢" if ct.status == "running" else "🔴"
            head = QHBoxLayout()
            head.setSpacing(8)
            lbl_name = QLabel(f"{dot}  {ct.name}")
            lbl_name.setObjectName("cardTitle")
            lbl_name.setWordWrap(True)
            head.addWidget(lbl_name, 1)
            lbl_id = QLabel(f"#{ct.vmid}")
            lbl_id.setObjectName("badge")
            lbl_id.setFixedWidth(62)
            lbl_id.setAlignment(Qt.AlignmentFlag.AlignCenter)
            head.addWidget(lbl_id, 0)
            cl.addLayout(head)
            loc = QLabel(f"{h.cluster_name} · {ct.node}")
            loc.setObjectName("muted")
            cl.addWidget(loc)
            cl.addWidget(self._kv("Status", ct.status))
            if ct.status == "running":
                for label, used, total, oid in [("CPU", ct.cpu, 1.0, ""), ("RAM", ct.mem, ct.maxmem, "ram")]:
                    pct = int(used * 100) if oid == "" else int(used / total * 100) if total else 0
                    row = QHBoxLayout()
                    row.setSpacing(8)
                    lk = QLabel(label)
                    lk.setFixedWidth(34)
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
                cl.addWidget(self._kv("RAM", f"{fmt_bytes(ct.mem)} / {fmt_bytes(ct.maxmem)}"))
            row = QHBoxLayout()
            row.setSpacing(6)
            for label, act in [("▶ Start", "start"), ("⏹ Stop", "stop"), ("↻ Reboot", "reboot")]:
                b = QPushButton(label)
                b.setFixedHeight(30)
                b.clicked.connect(lambda _=False, a=act, ct=ct: self.action_requested.emit(h.cluster_id, ct.node, ct.vmid, a, True))
                row.addWidget(b, 1)
            cl.addLayout(row)

    def _add_storage(self, h: ClusterHealth) -> None:
        lay = self.tab_storage.layout()
        assert isinstance(lay, QVBoxLayout)
        for s in h.storages:
            _, cl = self._card(lay)
            head = QLabel(f"💾  {s.storage}")
            head.setObjectName("cardTitle")
            cl.addWidget(head)
            sub = QLabel(f"{s.type}  ·  {s.node}  ·  {s.status}")
            sub.setObjectName("muted")
            cl.addWidget(sub)
            used_pct = (s.used / s.total * 100) if s.total else 0
            row = QHBoxLayout()
            row.setSpacing(8)
            lk = QLabel("Use")
            lk.setFixedWidth(34)
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
            det.setStyleSheet("font-size: 10.5px; margin-left: 42px;")
            cl.addWidget(det)
            if not s.enabled:
                warn = QLabel("disabled")
                warn.setStyleSheet("color: #f38ba8; font-size: 11px;")
                cl.addWidget(warn)

    def _kv(self, k: str, v: str) -> QLabel:
        row = QLabel(f"{k}  ·  {v}")
        row.setObjectName("muted")
        row.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.setWordWrap(True)
        return row
