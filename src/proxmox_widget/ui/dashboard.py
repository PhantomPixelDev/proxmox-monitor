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
    action_requested = Signal(str, str, int, str, bool)  # cluster_id, node, vmid, action, is_lxc

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Popup | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFixedWidth(380)
        self.setMinimumHeight(480)
        self._health: list[ClusterHealth] = []
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("🖥 ProxmoxWidget")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()
        btn_settings = QPushButton("⚙")
        btn_settings.setFixedSize(32, 32)
        btn_settings.clicked.connect(lambda: self.open_settings.emit())
        header.addWidget(btn_settings)
        root.addLayout(header)

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
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(8)
            lay.addStretch()

        footer = QHBoxLayout()
        self.btn_open = QPushButton("Open Proxmox")
        self.btn_open.setObjectName("primary")
        self.btn_open.clicked.connect(self._open_proxmox)
        footer.addWidget(self.btn_open, 1)
        self.btn_refresh = QPushButton("↻ Refresh")
        self.btn_refresh.clicked.connect(lambda: self._placeholder_refresh())
        footer.addWidget(self.btn_refresh)
        root.addLayout(footer)

        self.lbl_status = QLabel("No clusters configured — open Settings → Add Cluster")
        self.lbl_status.setObjectName("muted")
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)

    def _wrap_scroll(self, w: QWidget) -> QScrollArea:
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setWidget(w)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return sa

    def _open_proxmox(self) -> None:
        if not self._health:
            return
        # open first online cluster
        for h in self._health:
            if h.online:
                # find its config via health? we need host; fallback to health name
                webbrowser.open(f"https://{h.cluster_name}")
                return
        # fallback: try to open first cluster's base_url if we had it
        # we store cluster_id only; app will override this via callback if needed
        webbrowser.open("https://192.168.10.2:8006")

    def _placeholder_refresh(self) -> None:
        self.lbl_status.setText("Refreshing…")

    def update_health(self, health: list[ClusterHealth]) -> None:
        self._health = health
        # clear tabs
        for w in [self.tab_dashboard, self.tab_nodes, self.tab_vms, self.tab_cts, self.tab_storage]:
            lay = w.layout()
            assert lay is not None
            while lay.count():
                item = lay.takeAt(0)
                if item and item.widget():
                    item.widget().deleteLater()
            lay.addStretch()  # will be moved to bottom after inserts

        if not health:
            self.lbl_status.setText("No clusters — Settings → Add Cluster (e.g. 192.168.10.2:8006)")
            return

        online_count = sum(1 for h in health if h.online)
        total_nodes = sum(len(h.nodes) for h in health)
        total_vms = sum(len(h.vms) for h in health)
        total_cts = sum(len(h.containers) for h in health)
        self.lbl_status.setText(f"{online_count}/{len(health)} clusters online • {total_nodes} nodes • {total_vms} VMs • {total_cts} containers")

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
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)
        # insert before stretch
        parent_layout.insertWidget(parent_layout.count() - 1, card)
        return card, lay

    def _add_cluster_to_dashboard(self, h: ClusterHealth) -> None:
        lay = self.tab_dashboard.layout()
        assert isinstance(lay, QVBoxLayout)
        _, card_lay = self._card(lay)
        dot = "🟢" if h.online else "🔴"
        title = QLabel(f"{dot} {h.cluster_name}  ({h.cluster_id})")
        title.setStyleSheet("font-weight:600")
        card_lay.addWidget(title)
        if not h.online:
            err = QLabel(h.error or "Offline")
            err.setObjectName("muted")
            err.setWordWrap(True)
            card_lay.addWidget(err)
            return
        for n in h.nodes:
            ndot = "🟢" if n.status == "online" else "🔴"
            row = QLabel(f"{ndot} {n.node}  •  CPU {n.cpu*100:.0f}%  •  RAM {fmt_bytes(n.mem)}/{fmt_bytes(n.maxmem)}  •  {fmt_uptime(n.uptime)}")
            row.setWordWrap(True)
            card_lay.addWidget(row)
            # bars
            for label, val in [("CPU", n.cpu), ("RAM", n.mem / n.maxmem if n.maxmem else 0)]:
                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setValue(int(val * 100))
                bar.setFormat(f"{label} {int(val*100)}%")
                bar.setFixedHeight(14)
                card_lay.addWidget(bar)

        # quick VM summary
        if h.vms or h.containers:
            sep = QLabel(f"VMs: {len(h.vms)}  •  Containers: {len(h.containers)}")
            sep.setObjectName("muted")
            card_lay.addWidget(sep)

    def _add_nodes(self, h: ClusterHealth) -> None:
        lay = self.tab_nodes.layout()
        assert isinstance(lay, QVBoxLayout)
        for n in h.nodes:
            _, cl = self._card(lay)
            dot = "🟢" if n.status == "online" else "🔴"
            cl.addWidget(QLabel(f"{dot} {n.node}  —  {h.cluster_name}"))
            cl.addWidget(self._kv("Status", n.status))
            cl.addWidget(self._kv("CPU", f"{n.cpu*100:.1f}% / {n.maxcpu} cores"))
            cl.addWidget(self._kv("RAM", f"{fmt_bytes(n.mem)} / {fmt_bytes(n.maxmem)}"))
            cl.addWidget(self._kv("Disk", f"{fmt_bytes(n.disk)} / {fmt_bytes(n.maxdisk)}"))
            cl.addWidget(self._kv("Uptime", fmt_uptime(n.uptime)))

    def _add_vms(self, h: ClusterHealth) -> None:
        lay = self.tab_vms.layout()
        assert isinstance(lay, QVBoxLayout)
        for vm in h.vms:
            _, cl = self._card(lay)
            dot = "🟢" if vm.status == "running" else "🔴" if vm.status == "stopped" else "🟡"
            cl.addWidget(QLabel(f"{dot} {vm.name}  (#{vm.vmid})  •  {h.cluster_name}/{vm.node}"))
            cl.addWidget(self._kv("Status", vm.status + ("  [template]" if vm.template else "")))
            cl.addWidget(self._kv("CPU", f"{vm.cpu*100:.0f}%  •  {vm.cpus} vCPU"))
            cl.addWidget(self._kv("RAM", f"{fmt_bytes(vm.mem)} / {fmt_bytes(vm.maxmem)}"))
            # actions
            row = QHBoxLayout()
            for label, act in [("▶ Start", "start"), ("⏹ Stop", "stop"), ("↻ Reboot", "reboot")]:
                b = QPushButton(label)
                b.setEnabled(vm.status != "unknown")
                b.clicked.connect(lambda _=False, a=act, vm=vm: self.action_requested.emit(h.cluster_id, vm.node, vm.vmid, a, False))
                row.addWidget(b)
            cl.addLayout(row)

    def _add_cts(self, h: ClusterHealth) -> None:
        lay = self.tab_cts.layout()
        assert isinstance(lay, QVBoxLayout)
        for ct in h.containers:
            _, cl = self._card(lay)
            dot = "🟢" if ct.status == "running" else "🔴"
            cl.addWidget(QLabel(f"{dot} {ct.name}  (#{ct.vmid})  •  {h.cluster_name}/{ct.node}"))
            cl.addWidget(self._kv("Status", ct.status))
            cl.addWidget(self._kv("CPU", f"{ct.cpu*100:.0f}%"))
            cl.addWidget(self._kv("RAM", f"{fmt_bytes(ct.mem)} / {fmt_bytes(ct.maxmem)}"))
            row = QHBoxLayout()
            for label, act in [("▶ Start", "start"), ("⏹ Stop", "stop"), ("↻ Reboot", "reboot")]:
                b = QPushButton(label)
                b.clicked.connect(lambda _=False, a=act, ct=ct: self.action_requested.emit(h.cluster_id, ct.node, ct.vmid, a, True))
                row.addWidget(b)
            cl.addLayout(row)

    def _add_storage(self, h: ClusterHealth) -> None:
        lay = self.tab_storage.layout()
        assert isinstance(lay, QVBoxLayout)
        for s in h.storages:
            _, cl = self._card(lay)
            cl.addWidget(QLabel(f"💾 {s.storage}  ({s.type})  •  {s.node}"))
            cl.addWidget(self._kv("Status", s.status))
            used_pct = (s.used / s.total * 100) if s.total else 0
            cl.addWidget(self._kv("Usage", f"{fmt_bytes(s.used)} / {fmt_bytes(s.total)}  ({used_pct:.0f}%)"))
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(used_pct))
            bar.setFixedHeight(12)
            cl.addWidget(bar)

    def _kv(self, k: str, v: str) -> QLabel:
        lbl = QLabel(f"{k}:  {v}")
        lbl.setObjectName("muted")
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return lbl
