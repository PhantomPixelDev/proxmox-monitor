from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from proxmox_widget.config.models import ClusterHealth
from proxmox_widget.resources.icons import make_app_icon
from proxmox_widget.ui import icons
from proxmox_widget.ui.themes import DARK, palette_for, qss_for
from proxmox_widget.utils.format import fmt_bytes, fmt_uptime

# tab keys, in tab-bar order
OVERVIEW, NODES, VMS, CTS, STORAGE = "overview", "nodes", "vms", "cts", "storage"
LIST_TABS = (NODES, VMS, CTS, STORAGE)


def _plural(n: int, word: str) -> str:
    return word if n == 1 else f"{word}s"


class Dashboard(QWidget):
    open_settings = Signal()
    open_proxmox_requested = Signal()
    refresh_requested = Signal()
    # cluster_id, node, vmid, action, is_lxc
    action_requested = Signal(str, str, int, str, bool)
    # cluster_id, node, vmid, kind ("novnc" | "spice" | "rdp" | "shell"), is_lxc
    console_requested = Signal(str, str, int, str, bool)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("root")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Popup
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setFixedWidth(468)
        self.setMinimumHeight(620)
        self.setMaximumHeight(900)
        self.pal: dict[str, str] = DARK
        self._health: list[ClusterHealth] = []
        self._clusters: dict[str, object] = {}
        self._busy: dict[tuple[str, int, bool], str] = {}
        self._panes: dict[str, QWidget] = {}
        self._search: dict[str, QLineEdit] = {}
        self._counts: dict[str, QLabel] = {}
        self._running_only: dict[str, QPushButton] = {}
        self._scrolls: dict[str, QScrollArea] = {}
        self._scroll_handlers: dict[str, object] = {}
        self._build()

    # ------------------------------------------------------------------ chrome

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)

        root.addWidget(self._build_banner())
        root.addLayout(self._build_header())

        sep = QFrame()
        sep.setObjectName("lineSep")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        root.addWidget(sep)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs, 1)
        for key, title in (
            (OVERVIEW, "Overview"),
            (NODES, "Nodes"),
            (VMS, "VMs"),
            (CTS, "LXC"),
            (STORAGE, "Storage"),
        ):
            self.tabs.addTab(self._build_tab(key), title)

        root.addLayout(self._build_footer())

        self.lbl_status = QLabel("No clusters — open Settings then Add Cluster")
        self.lbl_status.setObjectName("meta")
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)

    def _build_banner(self) -> QFrame:
        self._banner = QFrame()
        self._banner.setObjectName("banner")
        self._banner.setVisible(False)
        bl = QHBoxLayout(self._banner)
        bl.setContentsMargins(10, 8, 8, 8)
        bl.setSpacing(8)
        self._banner_icon = QLabel()
        self._banner_icon.setFixedSize(16, 16)
        bl.addWidget(self._banner_icon, 0, Qt.AlignmentFlag.AlignTop)
        self._banner_label = QLabel()
        self._banner_label.setWordWrap(True)
        bl.addWidget(self._banner_label, 1)
        close = QPushButton()
        close.setObjectName("ghost")
        close.setIcon(icons.icon("close", 12, DARK["text_dim"]))
        close.setFixedSize(22, 22)
        close.clicked.connect(lambda: self._banner.setVisible(False))
        bl.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        self._banner_timer = QTimer(self)
        self._banner_timer.setSingleShot(True)
        self._banner_timer.timeout.connect(lambda: self._banner.setVisible(False))
        return self._banner

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(10)
        app_icon = QLabel()
        app_icon.setPixmap(make_app_icon(26).pixmap(26, 26))
        app_icon.setFixedSize(26, 26)
        header.addWidget(app_icon, 0)

        col = QVBoxLayout()
        col.setSpacing(1)
        title = QLabel("ProxmoxWidget")
        title.setObjectName("title")
        self.lbl_sub = QLabel("connecting…")
        self.lbl_sub.setObjectName("subtitle")
        col.addWidget(title)
        col.addWidget(self.lbl_sub)
        header.addLayout(col, 1)
        header.addStretch()

        self.btn_refresh = self._icon_button("refresh", "Refresh now")
        self.btn_refresh.clicked.connect(self._on_refresh_clicked)
        header.addWidget(self.btn_refresh)
        self.btn_settings = self._icon_button("settings", "Settings")
        self.btn_settings.clicked.connect(lambda: self.open_settings.emit())
        header.addWidget(self.btn_settings)
        return header

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.btn_open = QPushButton("  Open Proxmox")
        self.btn_open.setObjectName("primary")
        self.btn_open.setIcon(icons.icon("external", 15, DARK["accent_ink"]))
        self.btn_open.setMinimumHeight(34)
        self.btn_open.clicked.connect(lambda: self.open_proxmox_requested.emit())
        footer.addWidget(self.btn_open, 1)
        return footer

    def _icon_button(self, name: str, tip: str) -> QPushButton:
        b = QPushButton()
        b.setObjectName("ghost")
        b.setIcon(icons.icon(name, 15, self.pal["text_dim"]))
        b.setFixedSize(32, 30)
        b.setToolTip(tip)
        return b

    def _build_tab(self, key: str) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(8)

        if key in LIST_TABS:
            lay.addWidget(self._build_search(key))

        content = QWidget()
        content_lay = QVBoxLayout(content)
        content_lay.setContentsMargins(1, 2, 6, 8)
        content_lay.setSpacing(10)
        content_lay.addStretch()
        self._panes[key] = content

        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sa.setWidget(content)
        self._scrolls[key] = sa
        lay.addWidget(sa, 1)
        return page

    def _build_search(self, key: str) -> QFrame:
        placeholder = {
            NODES: "Search nodes…",
            VMS: "Search VMs by name, id or node…",
            CTS: "Search containers…",
            STORAGE: "Search storage…",
        }[key]
        bar = QFrame()
        bar.setObjectName("searchBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(1, 0, 6, 0)
        lay.setSpacing(6)

        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setClearButtonEnabled(True)
        edit.addAction(
            icons.icon("search", 14, self.pal["text_faint"]),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        edit.textChanged.connect(lambda _t, k=key: self._rebuild(k))
        edit.setMinimumHeight(30)
        self._search[key] = edit
        lay.addWidget(edit, 1)

        if key in (VMS, CTS):
            chip = QPushButton("Running")
            chip.setObjectName("chip")
            chip.setCheckable(True)
            chip.setToolTip("Show only running guests")
            chip.setFixedHeight(30)
            chip.toggled.connect(lambda _c, k=key: self._rebuild(k))
            self._running_only[key] = chip
            lay.addWidget(chip, 0)

        count = QLabel("")
        count.setObjectName("meta")
        count.setMinimumWidth(38)
        count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._counts[key] = count
        lay.addWidget(count, 0)
        return bar

    # ------------------------------------------------------------------- theme

    def apply_theme(self, theme: str) -> None:
        self.pal = palette_for(theme)
        self.setStyleSheet(qss_for(theme))
        self.btn_refresh.setIcon(icons.icon("refresh", 15, self.pal["text_dim"]))
        self.btn_settings.setIcon(icons.icon("settings", 15, self.pal["text_dim"]))
        self.btn_open.setIcon(icons.icon("external", 15, self.pal["accent_ink"]))
        for edit in self._search.values():
            for act in edit.actions():
                act.setIcon(icons.icon("search", 14, self.pal["text_faint"]))
        self._rebuild_all()

    # -------------------------------------------------------------- public API

    def set_clusters(self, clusters: list) -> None:
        self._clusters = {c.id: c for c in clusters}
        if clusters:
            self.btn_open.setText(f"  Open {clusters[0].name}")
            self.btn_open.setToolTip(clusters[0].base_url)
            self.btn_open.setEnabled(True)
        else:
            self.btn_open.setText("  Open Proxmox")
            self.btn_open.setEnabled(False)

    def set_busy(self, cluster_id: str, vmid: int, is_lxc: bool, action: str | None) -> None:
        key = (cluster_id, vmid, is_lxc)
        if action is None:
            self._busy.pop(key, None)
        else:
            self._busy[key] = action
        self._rebuild_all()

    def clear_busy(self) -> None:
        self._busy.clear()
        self._rebuild_all()

    def show_message(self, text: str, kind: str = "info", duration_ms: int = 4500) -> None:
        icon_name = {"info": "info", "success": "check", "warning": "warn", "error": "error"}.get(
            kind, "info"
        )
        color = {
            "info": self.pal["info"],
            "success": self.pal["ok"],
            "warning": self.pal["warn"],
            "error": self.pal["err"],
        }.get(kind, self.pal["info"])
        self._banner_icon.setPixmap(icons.pixmap(icon_name, 16, color))
        self._banner_label.setText(text)
        self._banner_label.setStyleSheet(f"color: {self.pal['text']}; font-size: 12px;")
        self._banner.setStyleSheet(
            f"QFrame#banner {{ background: {self.pal['surface']};"
            f" border: 1px solid {color}; border-left: 3px solid {color}; border-radius: 8px; }}"
        )
        self._banner.setVisible(True)
        self._banner_timer.start(duration_ms)

    def update_health(self, health: list[ClusterHealth]) -> None:
        self._health = health
        if not health:
            self.lbl_sub.setText("no clusters configured")
            self.lbl_status.setText("Settings then Add Cluster — host, port 8006, API token")
        else:
            online = sum(1 for h in health if h.online)
            nodes = sum(len(h.nodes) for h in health)
            vms = [vm for h in health for vm in h.vms]
            cts = [ct for h in health for ct in h.containers]
            running = sum(1 for g in vms + cts if g.status == "running")
            self.lbl_sub.setText(
                f"{online}/{len(health)} {_plural(len(health), 'cluster')} online  ·  "
                f"{nodes} {_plural(nodes, 'node')}  ·  {running} running"
            )
            self.lbl_status.setText(
                f"{len(vms)} VMs  ·  {len(cts)} containers  ·  "
                f"{sum(len(h.storages) for h in health)} storages"
            )
        self._rebuild_all()

    # ----------------------------------------------------------------- rebuild

    def _on_refresh_clicked(self) -> None:
        self.show_message("Refreshing…", "info", 1500)
        self.refresh_requested.emit()

    def _rebuild_all(self) -> None:
        for key in (OVERVIEW, *LIST_TABS):
            self._rebuild(key)

    def _clear(self, key: str) -> QVBoxLayout:
        pane = self._panes[key]
        lay = pane.layout()
        assert isinstance(lay, QVBoxLayout)
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        lay.addStretch()
        return lay

    def _query(self, key: str) -> str:
        edit = self._search.get(key)
        return edit.text().strip().lower() if edit else ""

    @staticmethod
    def _matches(query: str, *fields: object) -> bool:
        if not query:
            return True
        return any(query in str(f).lower() for f in fields)

    def _rebuild(self, key: str) -> None:
        bar = self._scrolls[key].verticalScrollBar()
        offset = bar.value()
        lay = self._clear(key)
        if not self._health:
            for c in self._counts.values():
                c.setText("")
            self._empty(lay, "No clusters yet — add one in Settings.")
            return
        builder = {
            OVERVIEW: self._fill_overview,
            NODES: self._fill_nodes,
            VMS: self._fill_vms,
            CTS: self._fill_cts,
            STORAGE: self._fill_storage,
        }[key]
        shown, total = builder(lay)
        if key in self._counts:
            self._counts[key].setText(f"{shown}/{total}" if shown != total else str(total))
        if shown == 0:
            q = self._query(key)
            self._empty(lay, f'Nothing matches "{q}".' if q else "Nothing here yet.")
        if offset:
            self._restore_scroll(key, bar, offset)

    def _restore_scroll(self, key: str, bar: QScrollBar, offset: int) -> None:
        """Put a rebuilt list back where the user had scrolled it.

        The fresh cards have no size yet, so the scrollbar range is still 0 when
        this runs. Waiting for the range to be recalculated is the only reliable
        moment to set the value.
        """
        bar.setValue(min(offset, bar.maximum()))
        self._drop_scroll_handler(key, bar)

        def restore(_minimum: int, maximum: int) -> None:
            if maximum <= 0:
                return
            bar.setValue(min(offset, maximum))
            self._drop_scroll_handler(key, bar)

        self._scroll_handlers[key] = restore
        bar.rangeChanged.connect(restore)

    def _drop_scroll_handler(self, key: str, bar: QScrollBar) -> None:
        handler = self._scroll_handlers.pop(key, None)
        if handler is None:
            return
        try:
            bar.rangeChanged.disconnect(handler)
        except (RuntimeError, TypeError):
            pass

    def _empty(self, lay: QVBoxLayout, text: str) -> None:
        lbl = QLabel(text)
        lbl.setObjectName("empty")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lay.insertWidget(lay.count() - 1, lbl)

    # ------------------------------------------------------------ card widgets

    def _card(self, parent: QVBoxLayout, accent: str) -> tuple[QVBoxLayout, QVBoxLayout]:
        """Card with a coloured left rail, a header block and a body block.

        The rail plus the header fill is what separates one guest from the next —
        a flat list of rows was unreadable once more than a couple were on screen.
        """
        card = QFrame()
        card.setObjectName("card")
        outer = QHBoxLayout(card)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        rail = QFrame()
        rail.setObjectName("accent")
        rail.setFixedWidth(3)
        rail.setStyleSheet(f"QFrame#accent {{ background: {accent}; }}")
        outer.addWidget(rail, 0)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        head_frame = QFrame()
        head_frame.setObjectName("cardHead")
        head = QVBoxLayout(head_frame)
        head.setContentsMargins(12, 9, 12, 9)
        head.setSpacing(3)
        col.addWidget(head_frame)

        body_frame = QFrame()
        body_frame.setObjectName("cardBody")
        body = QVBoxLayout(body_frame)
        body.setContentsMargins(12, 10, 12, 11)
        body.setSpacing(7)
        col.addWidget(body_frame)

        outer.addLayout(col, 1)
        parent.insertWidget(parent.count() - 1, card)
        return head, body

    def _dot(self, color: str) -> QLabel:
        d = QLabel()
        d.setFixedSize(9, 9)
        d.setStyleSheet(f"background: {color}; border-radius: 4px;")
        return d

    def _pill(self, text: str, color: str) -> QLabel:
        p = QLabel(text.upper())
        p.setObjectName("pill")
        p.setStyleSheet(
            f"color: {color}; border: 1px solid {color}; border-radius: 6px;"
            " padding: 1px 6px; font-size: 10px; font-weight: 800;"
        )
        return p

    def _title_row(
        self, icon_name: str, text: str, right: list[QWidget] | None = None, dot: str | None = None
    ) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(7)
        if dot:
            row.addWidget(self._dot(dot), 0)
        else:
            row.addWidget(icons.label(icon_name, 15, self.pal["text_dim"]), 0)
        lbl = QLabel(text)
        lbl.setObjectName("cardTitle")
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(lbl, 1)
        for w in right or []:
            row.addWidget(w, 0)
        return row

    def _meta_row(self, parts: list[tuple[str, str]]) -> QHBoxLayout:
        """Small icon plus text pairs on one line, e.g. node, cores, uptime."""
        row = QHBoxLayout()
        row.setSpacing(5)
        for i, (icon_name, text) in enumerate(parts):
            if i:
                dotsep = QLabel("·")
                dotsep.setObjectName("meta")
                row.addWidget(dotsep, 0)
            row.addWidget(icons.label(icon_name, 12, self.pal["text_faint"]), 0)
            lbl = QLabel(text)
            lbl.setObjectName("meta")
            row.addWidget(lbl, 0)
        row.addStretch(1)
        return row

    def _metric(self, kind: str, name: str, pct: float, detail: str = "") -> QWidget:
        pct_i = max(0, min(100, round(pct)))
        w = QWidget()
        w.setObjectName("metricRow")
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(icons.label(kind, 13, self.pal["text_faint"]), 0)

        lbl = QLabel(name)
        lbl.setObjectName("muted")
        lbl.setFixedWidth(34)
        row.addWidget(lbl, 0)

        bar = QProgressBar()
        bar.setTextVisible(False)
        bar.setRange(0, 100)
        bar.setValue(pct_i)
        if pct_i >= 90:
            bar.setObjectName("hot")
        elif kind == "ram":
            bar.setObjectName("ram")
        elif kind == "disk":
            bar.setObjectName("disk")
        bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.addWidget(bar, 1)

        val = QLabel(f"{pct_i}%")
        val.setObjectName("value")
        val.setFixedWidth(32)
        val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(val, 0)

        det = QLabel(detail)
        det.setObjectName("meta")
        det.setFixedWidth(104)
        det.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(det, 0)
        return w

    def _action_button(self, icon_name: str, text: str, tip: str = "") -> QPushButton:
        b = QPushButton(f" {text}")
        b.setIcon(icons.icon(icon_name, 13, self.pal["text_dim"]))
        b.setFixedHeight(28)
        b.setToolTip(tip or text)
        return b

    def _status_color(self, status: str, busy: str | None = None) -> str:
        if busy:
            return self.pal["warn"]
        return {
            "running": self.pal["ok"],
            "online": self.pal["ok"],
            "available": self.pal["ok"],
            "paused": self.pal["warn"],
            "stopped": self.pal["err"],
            "offline": self.pal["err"],
        }.get(status, self.pal["text_faint"])

    # ------------------------------------------------------------- tab fillers

    def _fill_overview(self, lay: QVBoxLayout) -> tuple[int, int]:
        for h in self._health:
            color = self.pal["ok"] if h.online else self.pal["err"]
            head, body = self._card(lay, color)
            head.addLayout(
                self._title_row(
                    "cluster",
                    h.cluster_name,
                    right=[self._pill("online" if h.online else "offline", color)],
                    dot=color,
                )
            )
            head.addLayout(
                self._meta_row(
                    [
                        ("network", h.cluster_id),
                        ("node", f"{len(h.nodes)} {_plural(len(h.nodes), 'node')}"),
                    ]
                )
            )
            if not h.online:
                err = QLabel(h.error or "Cluster unreachable")
                err.setWordWrap(True)
                err.setStyleSheet(f"color: {self.pal['err']}; font-size: 12px;")
                body.addWidget(err)
                continue

            running_vms = sum(1 for vm in h.vms if vm.status == "running")
            running_cts = sum(1 for ct in h.containers if ct.status == "running")
            body.addLayout(
                self._stat_strip(
                    [
                        ("vm", "VMs", f"{running_vms}/{len(h.vms)}"),
                        ("ct", "LXC", f"{running_cts}/{len(h.containers)}"),
                        ("storage", "Storage", str(len(h.storages))),
                    ]
                )
            )
            for n in h.nodes:
                sep = QFrame()
                sep.setObjectName("lineSep")
                sep.setFixedHeight(1)
                body.addWidget(sep)
                body.addLayout(
                    self._meta_row(
                        [
                            ("node", n.node),
                            ("cpu", f"{n.maxcpu} {_plural(n.maxcpu, 'core')}"),
                            ("uptime", fmt_uptime(n.uptime)),
                        ]
                    )
                )
                body.addWidget(self._metric("cpu", "CPU", n.cpu * 100))
                body.addWidget(
                    self._metric(
                        "ram",
                        "RAM",
                        (n.mem / n.maxmem * 100) if n.maxmem else 0,
                        f"{fmt_bytes(n.mem)} / {fmt_bytes(n.maxmem)}",
                    )
                )
                body.addWidget(
                    self._metric(
                        "disk",
                        "Disk",
                        (n.disk / n.maxdisk * 100) if n.maxdisk else 0,
                        f"{fmt_bytes(n.disk)} / {fmt_bytes(n.maxdisk)}",
                    )
                )
        return len(self._health), len(self._health)

    def _stat_strip(self, items: list[tuple[str, str, str]]) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        for icon_name, label_text, value in items:
            tile = QFrame()
            tile.setObjectName("tile")
            tile.setStyleSheet(
                f"QFrame#tile {{ background: {self.pal['surface_hi']};"
                f" border: 1px solid {self.pal['border']}; border-radius: 8px; }}"
            )
            tl = QVBoxLayout(tile)
            tl.setContentsMargins(10, 7, 10, 7)
            tl.setSpacing(2)
            top = QHBoxLayout()
            top.setSpacing(5)
            top.addWidget(icons.label(icon_name, 12, self.pal["text_faint"]), 0)
            cap = QLabel(label_text)
            cap.setObjectName("meta")
            top.addWidget(cap, 1)
            tl.addLayout(top)
            val = QLabel(value)
            val.setStyleSheet(f"color: {self.pal['text']}; font-size: 15px; font-weight: 700;")
            tl.addWidget(val)
            row.addWidget(tile, 1)
        return row

    def _fill_nodes(self, lay: QVBoxLayout) -> tuple[int, int]:
        q = self._query(NODES)
        total = shown = 0
        for h in self._health:
            for n in h.nodes:
                total += 1
                if not self._matches(q, n.node, n.status, h.cluster_name):
                    continue
                shown += 1
                color = self._status_color(n.status)
                head, body = self._card(lay, color)
                head.addLayout(
                    self._title_row("node", n.node, right=[self._pill(n.status, color)], dot=color)
                )
                head.addLayout(
                    self._meta_row(
                        [
                            ("cluster", h.cluster_name),
                            ("cpu", f"{n.maxcpu} {_plural(n.maxcpu, 'core')}"),
                            ("uptime", fmt_uptime(n.uptime)),
                        ]
                    )
                )
                body.addWidget(self._metric("cpu", "CPU", n.cpu * 100))
                body.addWidget(
                    self._metric(
                        "ram",
                        "RAM",
                        (n.mem / n.maxmem * 100) if n.maxmem else 0,
                        f"{fmt_bytes(n.mem)} / {fmt_bytes(n.maxmem)}",
                    )
                )
                body.addWidget(
                    self._metric(
                        "disk",
                        "Disk",
                        (n.disk / n.maxdisk * 100) if n.maxdisk else 0,
                        f"{fmt_bytes(n.disk)} / {fmt_bytes(n.maxdisk)}",
                    )
                )
                row = QHBoxLayout()
                row.setSpacing(6)
                shell = self._action_button("console", "Shell", f"noVNC shell on {n.node}")
                shell.clicked.connect(
                    lambda _=False, cid=h.cluster_id, node=n.node: self.console_requested.emit(
                        cid, node, 0, "shell", False
                    )
                )
                row.addWidget(shell, 1)
                web = self._action_button("external", "Web UI", "Open the Proxmox web UI")
                web.clicked.connect(lambda _=False: self.open_proxmox_requested.emit())
                row.addWidget(web, 1)
                body.addLayout(row)
        return shown, total

    def _guest_card(self, lay: QVBoxLayout, h: ClusterHealth, g, is_lxc: bool) -> None:
        busy = self._busy.get((h.cluster_id, g.vmid, is_lxc))
        status = busy if busy else g.status
        color = self._status_color(g.status, busy)
        head, body = self._card(lay, color)

        vmid_badge = QLabel(f"#{g.vmid}")
        vmid_badge.setObjectName("badge")
        head.addLayout(
            self._title_row(
                "ct" if is_lxc else "vm",
                g.name,
                right=[self._pill(status, color), vmid_badge],
                dot=color,
            )
        )
        meta = [("node", g.node), ("cpu", f"{g.cpus} vCPU")]
        if g.status == "running" and g.uptime:
            meta.append(("uptime", fmt_uptime(g.uptime)))
        if getattr(g, "template", False):
            meta.append(("shield", "template"))
        head.addLayout(self._meta_row(meta))

        if busy:
            prog = QProgressBar()
            prog.setObjectName("busy")
            prog.setRange(0, 0)
            prog.setTextVisible(False)
            body.addWidget(prog)

        running = g.status == "running"
        if running:
            body.addWidget(self._metric("cpu", "CPU", g.cpu * 100))
            body.addWidget(
                self._metric(
                    "ram",
                    "RAM",
                    (g.mem / g.maxmem * 100) if g.maxmem else 0,
                    f"{fmt_bytes(g.mem)} / {fmt_bytes(g.maxmem)}",
                )
            )
            if is_lxc and g.maxdisk:
                body.addWidget(
                    self._metric(
                        "disk",
                        "Disk",
                        g.disk / g.maxdisk * 100,
                        f"{fmt_bytes(g.disk)} / {fmt_bytes(g.maxdisk)}",
                    )
                )
        else:
            idle = QLabel(f"Allocated {fmt_bytes(g.maxmem)} RAM  ·  {g.cpus} vCPU")
            idle.setObjectName("meta")
            body.addWidget(idle)

        power = QHBoxLayout()
        power.setSpacing(6)
        for icon_name, text, act, enabled in (
            ("play", "Start", "start", not running),
            ("stop", "Stop", "stop", running),
            ("restart", "Reboot", "reboot", running),
        ):
            b = self._action_button(icon_name, text)
            b.setEnabled(enabled and not busy)
            b.clicked.connect(
                lambda _=False, a=act, node=g.node, vmid=g.vmid: self.action_requested.emit(
                    h.cluster_id, node, vmid, a, is_lxc
                )
            )
            power.addWidget(b, 1)
        body.addLayout(power)

        console = QHBoxLayout()
        console.setSpacing(6)
        consoles: list[tuple[str, str, str, str]] = [
            ("console", "Console", "novnc", "Open the noVNC web console"),
        ]
        if not is_lxc:
            consoles.append(("monitor", "SPICE", "spice", "Open with remote-viewer over SPICE"))
            consoles.append(("remote", "RDP", "rdp", "RDP to the guest IP, needs the guest agent"))
        for icon_name, text, kind, tip in consoles:
            b = self._action_button(icon_name, text, tip)
            b.setEnabled(running)
            b.clicked.connect(
                lambda _=False, k=kind, node=g.node, vmid=g.vmid: self.console_requested.emit(
                    h.cluster_id, node, vmid, k, is_lxc
                )
            )
            console.addWidget(b, 1)
        body.addLayout(console)

    def _fill_guests(self, lay: QVBoxLayout, key: str, is_lxc: bool) -> tuple[int, int]:
        q = self._query(key)
        only_running = self._running_only[key].isChecked()
        total = shown = 0
        for h in self._health:
            guests = h.containers if is_lxc else h.vms
            ordered = sorted(guests, key=lambda g: (g.status != "running", g.name.lower()))
            for g in ordered:
                total += 1
                if only_running and g.status != "running":
                    continue
                if not self._matches(q, g.name, g.vmid, g.node, g.status, h.cluster_name):
                    continue
                shown += 1
                self._guest_card(lay, h, g, is_lxc)
        return shown, total

    def _fill_vms(self, lay: QVBoxLayout) -> tuple[int, int]:
        return self._fill_guests(lay, VMS, False)

    def _fill_cts(self, lay: QVBoxLayout) -> tuple[int, int]:
        return self._fill_guests(lay, CTS, True)

    def _fill_storage(self, lay: QVBoxLayout) -> tuple[int, int]:
        q = self._query(STORAGE)
        total = shown = 0
        for h in self._health:
            for s in h.storages:
                total += 1
                if not self._matches(q, s.storage, s.type, s.node, s.status):
                    continue
                shown += 1
                pct = (s.used / s.total * 100) if s.total else 0
                color = (
                    self.pal["err"]
                    if pct >= 90 or not s.enabled
                    else self.pal["warn"]
                    if pct >= 75
                    else self._status_color(s.status)
                )
                head, body = self._card(lay, color)
                badge = QLabel(s.type.upper() or "DIR")
                badge.setObjectName("badge")
                # rail warns on how full the store is; the pill still states the API status
                head.addLayout(
                    self._title_row(
                        "storage",
                        s.storage,
                        right=[self._pill(s.status, self._status_color(s.status)), badge],
                        dot=color,
                    )
                )
                head.addLayout(
                    self._meta_row(
                        [
                            ("node", s.node),
                            ("network", "shared" if s.shared else "local"),
                            ("check", "enabled" if s.enabled else "disabled"),
                        ]
                    )
                )
                body.addWidget(
                    self._metric("disk", "Used", pct, f"{fmt_bytes(s.used)} / {fmt_bytes(s.total)}")
                )
                free = QLabel(f"{fmt_bytes(s.avail)} free")
                free.setObjectName("meta")
                body.addWidget(free)
        return shown, total
