from __future__ import annotations

import base64

from PySide6.QtCore import QByteArray, QEvent, QObject, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from proxmox_widget.config.models import ClusterHealth
from proxmox_widget.resources.icons import make_app_icon
from proxmox_widget.ui import icons
from proxmox_widget.ui.themes import DARK, palette_for, qss_for
from proxmox_widget.utils.format import fmt_bytes, fmt_uptime


def _fs(size: int | float) -> int:
    try:
        v = int(size)
        return v if v > 0 else 1
    except Exception:
        return 1


class SparklineWidget(QWidget):
    def __init__(self, points: list[float] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._points: list[float] = list(points or [])
        self.setMinimumSize(60, 20)
        self.setMaximumHeight(20)

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(60, 20)

    def set_points(self, points: list[float]) -> None:
        self._points = list(points)
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        if not self._points:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = self.width()
        h = self.height()
        if w <= 2 or h <= 2:
            return
        pad = 1
        draw_w = w - pad * 2
        draw_h = h - pad * 2
        n = len(self._points)
        lo = min(self._points)
        hi = max(self._points)
        span = hi - lo if hi != lo else 1.0
        pen = QPen(QColor("#7aa5ff"))
        pen.setWidth(1)
        painter.setPen(pen)
        if n == 1:
            y = pad + draw_h - ((self._points[0] - lo) / span * draw_h)
            painter.drawLine(int(pad), int(y), int(pad + draw_w), int(y))
            return
        step = draw_w / (n - 1) if n > 1 else draw_w
        last_x = pad
        last_y = pad + draw_h - ((self._points[0] - lo) / span * draw_h)
        for i in range(1, n):
            x = pad + step * i
            y = pad + draw_h - ((self._points[i] - lo) / span * draw_h)
            painter.drawLine(int(last_x), int(last_y), int(x), int(y))
            last_x, last_y = x, y


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
    # cluster_id, node, vmid, kind ("novnc" | "spice" | "rdp" | "shell" | "ssh" | "lxc_shell"), is_lxc
    console_requested = Signal(str, str, int, str, bool)
    bulk_action_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("root")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setMinimumWidth(468)
        self.setMinimumHeight(620)
        self.setMaximumHeight(900)
        self.resize(468, 700)
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
        self._search_timers: dict[str, QTimer] = {}
        self._search_debounce: dict[str, QTimer] = self._search_timers
        self._debounce: dict[str, QTimer] = self._search_timers
        self._card_cache: dict[str, dict[str, QFrame]] = {}
        # filters / sort — per tab (VMS/CTS etc), persisted via QSettings
        self._type_filter: dict[str, QComboBox] = {}
        self._node_filter: dict[str, QComboBox] = {}
        self._sort_combo: dict[str, QComboBox] = {}
        self._filters_btn: dict[str, QPushButton] = {}
        self._filters_menu: dict[str, QMenu] = {}
        self._qsettings = QSettings("PhantomPixelDev", "ProxmoxWidget")
        # bulk selection model: set of (cluster_id, vmid, is_lxc)
        self._selected: set[tuple[str, int, bool]] = set()
        self._last_selected: tuple[str, int, bool] | None = None
        self._close_to_tray: bool = True
        try:
            import proxmox_widget.ui.font_fix  # noqa: F401  # ensure QFont clamp active
            from proxmox_widget.ui.font_fix import (
                ensure_valid_app_font,
                install_qfont_suppress_filter,
                safe_font,
            )

            install_qfont_suppress_filter()
            ensure_valid_app_font()
            try:
                from PySide6.QtWidgets import QApplication as _QApp

                _app = _QApp.instance()
                if _app is not None:
                    ensure_valid_app_font(_app)
            except Exception:
                pass
            f = self.font()
            if f.pointSize() <= 0 and f.pixelSize() <= 0:
                sf = safe_font()
                if sf.pointSize() <= 0:
                    sf.setPointSize(9)
                self.setFont(sf)
            elif f.pointSize() <= 0 and f.pixelSize() > 0:
                from PySide6.QtGui import QFont as _QFont

                pt = max(1, round(int(f.pixelSize()) * 72 / 96))
                nf = _QFont(f.family() or "Segoe UI", pt)
                try:
                    nf.setPixelSize(int(f.pixelSize()))
                except Exception:
                    pass
                if nf.pointSize() <= 0:
                    nf.setPointSize(pt)
                self.setFont(nf)
            try:
                vf = self.font()
                if vf.pointSize() <= 0 and vf.pixelSize() <= 0:
                    sf2 = safe_font()
                    self.setFont(sf2)
            except Exception:
                pass
        except Exception:
            pass
        self._build()
        self._restore_geometry()
        self._setup_shortcuts()

    def set_close_to_tray(self, value: bool) -> None:
        self._close_to_tray = bool(value)

    def _restore_geometry(self) -> None:
        restored = False
        geo = self._qsettings.value("dashboard/geometry")
        if geo is not None:
            try:
                if isinstance(geo, QByteArray):
                    if not geo.isEmpty():
                        self.restoreGeometry(geo)
                        restored = True
                elif isinstance(geo, str) and geo:
                    try:
                        decoded = base64.b64decode(geo.encode("ascii"))
                        self.restoreGeometry(QByteArray(decoded))
                        restored = True
                    except Exception:
                        pass
                elif isinstance(geo, bytes) and geo:
                    try:
                        decoded = base64.b64decode(geo)
                        self.restoreGeometry(QByteArray(decoded))
                        restored = True
                    except Exception:
                        pass
                else:
                    self.restoreGeometry(geo)  # type: ignore[arg-type]
                    restored = True
            except Exception:
                pass
        if not restored:
            b64 = self._qsettings.value("dashboard/geometry_b64")
            if b64 is not None and isinstance(b64, str) and b64:
                try:
                    decoded = base64.b64decode(b64.encode("ascii"))
                    self.restoreGeometry(QByteArray(decoded))
                    restored = True
                except Exception:
                    pass
            elif b64 is not None and isinstance(b64, QByteArray) and not b64.isEmpty():
                try:
                    decoded = base64.b64decode(bytes(b64))
                    self.restoreGeometry(QByteArray(decoded))
                    restored = True
                except Exception:
                    try:
                        self.restoreGeometry(b64)
                        restored = True
                    except Exception:
                        pass
        size = self._qsettings.value("dashboard/size")
        pos = self._qsettings.value("dashboard/pos")
        if size is not None and pos is not None:
            try:
                if (isinstance(geo, QByteArray) and not geo.isEmpty()) or restored:
                    pass
                elif hasattr(size, "width"):
                    self.resize(size)
                    if hasattr(pos, "x"):
                        self.move(pos)
            except Exception:
                pass

    def save_geometry(self) -> None:
        try:
            geo = self.saveGeometry()
            self._qsettings.setValue("dashboard/geometry", geo)
            try:
                b64 = base64.b64encode(bytes(geo)).decode("ascii")
                self._qsettings.setValue("dashboard/geometry_b64", b64)
            except Exception:
                pass
            self._qsettings.setValue("dashboard/size", self.size())
            self._qsettings.setValue("dashboard/pos", self.pos())
        except Exception:
            pass

    def closeEvent(self, event) -> None:  # type: ignore[override]
        try:
            self.save_geometry()
        except Exception:
            pass
        if getattr(self, "_close_to_tray", False):
            try:
                event.ignore()
                self.hide()
                return
            except Exception:
                pass
        try:
            super().closeEvent(event)
        except Exception:
            pass

    def hideEvent(self, event) -> None:  # type: ignore[override]
        try:
            self.save_geometry()
        except Exception:
            pass
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        try:
            self.save_geometry()
        except Exception:
            pass
        super().resizeEvent(event)

    def moveEvent(self, event) -> None:  # type: ignore[override]
        try:
            self.save_geometry()
        except Exception:
            pass
        super().moveEvent(event)

    def _focus_search(self) -> None:
        try:
            cur = self.tabs.currentIndex()
            keys = [OVERVIEW, NODES, VMS, CTS, STORAGE]
            if 0 <= cur < len(keys):
                k = keys[cur]
                edit = self._search.get(k)
                if edit is not None:
                    edit.setFocus()
                    edit.selectAll()
                    return
            for edit in self._search.values():
                if edit.isVisible():
                    edit.setFocus()
                    edit.selectAll()
                    return
            first = next(iter(self._search.values()), None)
            if first is not None:
                first.setFocus()
                first.selectAll()
        except Exception:
            pass

    def _on_escape_shortcut(self) -> None:
        if self._selected:
            self.clear_selection()
            return
        try:
            self.hide()
            self.save_geometry()
        except Exception:
            pass

    def _setup_shortcuts(self) -> None:
        try:
            from PySide6.QtGui import QKeySequence, QShortcut
            from PySide6.QtWidgets import QApplication as _QApp

            sc = QShortcut(QKeySequence("Ctrl+K"), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(self._focus_search)
            self._sc_ctrl_k = sc
            sc2 = QShortcut(QKeySequence("Ctrl+,"), self)
            sc2.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc2.activated.connect(lambda: self.open_settings.emit())
            self._sc_ctrl_comma = sc2
            sc3 = QShortcut(QKeySequence("F5"), self)
            sc3.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc3.activated.connect(lambda: self.refresh_requested.emit())
            self._sc_f5 = sc3
            sc4 = QShortcut(QKeySequence("Escape"), self)
            sc4.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc4.activated.connect(self._on_escape_shortcut)
            self._sc_escape = sc4
            sc5 = QShortcut(QKeySequence("Ctrl+Q"), self)
            sc5.setContext(Qt.ShortcutContext.WindowShortcut)
            sc5.activated.connect(lambda: _QApp.instance().quit() if _QApp.instance() else None)  # type: ignore[union-attr]
            self._sc_ctrl_q = sc5
        except Exception:
            pass

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        try:
            from PySide6.QtCore import Qt as _Qt

            is_ctrl = bool(event.modifiers() & _Qt.KeyboardModifier.ControlModifier)
            key = event.key()
            if is_ctrl and key == _Qt.Key.Key_A:
                self.select_all()
                event.accept()
                return
            if key == _Qt.Key.Key_Escape:
                if self._selected:
                    self.clear_selection()
                else:
                    self.hide()
                    try:
                        self.save_geometry()
                    except Exception:
                        pass
                event.accept()
                return
        except Exception:
            pass
        super().keyPressEvent(event)

    def toggle_selection(self, cluster_id: str, vmid: int, is_lxc: bool) -> None:
        key = (cluster_id, vmid, is_lxc)
        if key in self._selected:
            self._selected.remove(key)
            if self._last_selected == key:
                self._last_selected = next(iter(self._selected), None) if self._selected else None
        else:
            self._selected.add(key)
            self._last_selected = key
        self._refresh_selection_visuals()

    def toggle(self, cluster_id: str, vmid: int, is_lxc: bool) -> None:
        self.toggle_selection(cluster_id, vmid, is_lxc)

    def clear_selection(self) -> None:
        self._selected.clear()
        self._last_selected = None
        self._refresh_selection_visuals()

    def clear(self) -> None:
        self.clear_selection()

    def select_all(self) -> None:
        ordered = self._ordered_visible_guests()
        for cid, vmid, is_lxc in ordered:
            self._selected.add((cid, vmid, is_lxc))
        if ordered:
            self._last_selected = ordered[-1]
        self._refresh_selection_visuals()

    def is_selected(self, cluster_id: str, vmid: int, is_lxc: bool) -> bool:
        return (cluster_id, vmid, is_lxc) in self._selected

    def _ordered_visible_guests(self) -> list[tuple[str, int, bool]]:
        result: list[tuple[str, int, bool]] = []
        for h in self._health:
            for g in h.vms:
                result.append((h.cluster_id, g.vmid, False))
            for g in h.containers:
                result.append((h.cluster_id, g.vmid, True))
        return result

    def _on_card_clicked(self, cluster_id: str, vmid: int, is_lxc: bool, modifiers, button) -> None:
        from PySide6.QtCore import Qt as _Qt

        is_ctrl = bool(modifiers & _Qt.KeyboardModifier.ControlModifier)
        is_shift = bool(modifiers & _Qt.KeyboardModifier.ShiftModifier)
        is_left = (
            button == _Qt.MouseButton.LeftButton if hasattr(_Qt.MouseButton, "LeftButton") else True
        )
        if not is_left and button is not None:
            try:
                if int(button) != int(_Qt.MouseButton.LeftButton):
                    return
            except Exception:
                pass
        key = (cluster_id, vmid, is_lxc)
        if is_ctrl:
            self.toggle_selection(cluster_id, vmid, is_lxc)
        elif is_shift and self._last_selected is not None:
            ordered = self._ordered_visible_guests()
            try:
                idx_last = ordered.index(self._last_selected)
                idx_cur = ordered.index(key)
            except ValueError:
                self._selected.add(key)
                self._last_selected = key
                self._refresh_selection_visuals()
                return
            lo = min(idx_last, idx_cur)
            hi = max(idx_last, idx_cur)
            for k in ordered[lo : hi + 1]:
                self._selected.add(k)
            self._last_selected = key
            self._refresh_selection_visuals()
        else:
            self._selected.clear()
            self._selected.add(key)
            self._last_selected = key
            self._refresh_selection_visuals()

    def _refresh_selection_visuals(self) -> None:
        for cache in self._card_cache.values():
            for gkey, card in cache.items():
                try:
                    parts = gkey.split(":")
                    if len(parts) >= 3:
                        cid = parts[0]
                        vmid = int(parts[1])
                        is_lxc = parts[2] == "ct"
                        selected = (cid, vmid, is_lxc) in self._selected
                        self._apply_selection_style(card, selected)
                except Exception:
                    pass
        for key in (VMS, CTS):
            cache = self._card_cache.get(key)
            if not cache:
                continue
            for gkey, card in list(cache.items()):
                try:
                    parts = gkey.split(":")
                    if len(parts) >= 3:
                        cid = parts[0]
                        vmid = int(parts[1])
                        is_lxc = parts[2] == "ct"
                        selected = (cid, vmid, is_lxc) in self._selected
                        self._apply_selection_style(card, selected)
                except Exception:
                    pass
        self._update_bulk_bar_visibility()

    def _apply_selection_style(self, card: QFrame, selected: bool) -> None:
        try:
            card.setProperty("selected", selected)
            if selected:
                card.setStyleSheet(card.styleSheet() + "")
            self.style().unpolish(card)
            self.style().polish(card)
            card.update()
        except Exception:
            pass

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

        root.addWidget(self._build_bulk_bar())

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

    def _build_bulk_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("bulkBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._bulk_select_all = QPushButton("Select All")
        self._bulk_select_all.setObjectName("ghost")
        self._bulk_select_all.setToolTip("Select all visible guests (Ctrl+A)")
        self._bulk_select_all.clicked.connect(self.select_all)
        lay.addWidget(self._bulk_select_all, 0)
        self._bulk_clear = QPushButton("Clear")
        self._bulk_clear.setObjectName("ghost")
        self._bulk_clear.setToolTip("Clear selection (Esc)")
        self._bulk_clear.clicked.connect(self.clear_selection)
        lay.addWidget(self._bulk_clear, 0)
        lay.addStretch(1)
        self._bulk_buttons: dict[str, QPushButton] = {}
        for text, action in (
            ("Start", "start"),
            ("Shutdown", "shutdown"),
            ("Reboot", "reboot"),
            ("Stop", "stop"),
        ):
            btn = QPushButton(text)
            btn.setObjectName("chip")
            btn.setToolTip(f"Bulk {text} selected guests")
            btn.clicked.connect(lambda _=False, a=action: self.bulk_action_requested.emit(a))
            lay.addWidget(btn, 0)
            self._bulk_buttons[action] = btn
        self._bulk_bar = bar
        bar.setVisible(False)
        return bar

    def _update_bulk_bar_visibility(self) -> None:
        try:
            if hasattr(self, "_bulk_bar"):
                self._bulk_bar.setVisible(bool(self._selected))
        except Exception:
            pass

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
        edit.textChanged.connect(lambda _t, k=key: self._schedule_rebuild(k))
        edit.setMinimumHeight(30)
        self._search[key] = edit
        lay.addWidget(edit, 1)

        if key in (VMS, CTS):
            chip = QPushButton("Running")
            chip.setObjectName("chip")
            chip.setCheckable(True)
            chip.setToolTip("Show only running guests")
            chip.setFixedHeight(30)
            persisted_chip = self._qsettings.value(f"dashboard/running_{key}", False)
            if isinstance(persisted_chip, str):
                persisted_chip = persisted_chip.lower() in ("true", "1")
            chip.setChecked(bool(persisted_chip))
            chip.toggled.connect(lambda _c, k=key: self._on_chip_toggled(k))
            self._running_only[key] = chip
            lay.addWidget(chip, 0)

        # keep per-tab combo boxes in dicts for persistence + _matches logic,
        # but expose them only inside a single Filters popover
        type_cb = None
        node_cb = None
        sort_cb = None

        if key in (VMS, CTS):
            type_cb = QComboBox()
            type_cb.setObjectName("typeFilter")
            type_cb.addItems(["All", "VM", "CT"])
            type_cb.setFixedHeight(28)
            type_cb.setMinimumWidth(72)
            type_cb.setToolTip("Filter by type")
            saved_type = self._qsettings.value(f"dashboard/type_{key}", "All")
            idx_t = type_cb.findText(str(saved_type))
            if idx_t >= 0:
                type_cb.setCurrentIndex(idx_t)
            type_cb.currentTextChanged.connect(lambda _t, k=key: self._on_filter_changed(k))
            self._type_filter[key] = type_cb

        if key in LIST_TABS:
            node_cb = QComboBox()
            node_cb.setObjectName("nodeFilter")
            node_cb.addItems(["All nodes"])
            node_cb.setFixedHeight(28)
            node_cb.setMinimumWidth(110)
            node_cb.setToolTip("Filter by node")
            saved_node = self._qsettings.value(f"dashboard/node_{key}", "All nodes")
            idx_n = node_cb.findText(str(saved_node))
            if idx_n >= 0:
                node_cb.setCurrentIndex(idx_n)
            node_cb.currentTextChanged.connect(lambda _t, k=key: self._on_filter_changed(k))
            self._node_filter[key] = node_cb

        if key in (VMS, CTS):
            sort_cb = QComboBox()
            sort_cb.setObjectName("sortCombo")
            sort_cb.addItems(["Name", "CPU", "Uptime"])
            sort_cb.setFixedHeight(28)
            sort_cb.setMinimumWidth(92)
            sort_cb.setToolTip("Sort guests")
            saved_sort = self._qsettings.value(f"dashboard/sort_{key}", "Name")
            idx_s = sort_cb.findText(str(saved_sort))
            if idx_s >= 0:
                sort_cb.setCurrentIndex(idx_s)
            sort_cb.currentTextChanged.connect(lambda _t, k=key: self._on_filter_changed(k))
            self._sort_combo[key] = sort_cb

        # single disclosure button — progressive disclosure for filter chrome
        has_filters = (type_cb is not None) or (node_cb is not None) or (sort_cb is not None)
        if has_filters:
            filters_btn = QPushButton("Filters")
            filters_btn.setObjectName("ghost")
            filters_btn.setIcon(icons.icon("filter", 12, self.pal["text_dim"]))
            filters_btn.setFixedHeight(30)
            filters_btn.setToolTip("Filters — type, node, sort")
            menu = QMenu(filters_btn)
            menu.setObjectName("filtersMenu")
            container = QWidget()
            container.setObjectName("filtersContainer")
            form = QFormLayout(container)
            form.setContentsMargins(10, 8, 10, 8)
            form.setSpacing(8)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
            if type_cb is not None:
                lbl = QLabel("Type")
                lbl.setObjectName("meta")
                form.addRow(lbl, type_cb)
            if node_cb is not None:
                lbl = QLabel("Node")
                lbl.setObjectName("meta")
                form.addRow(lbl, node_cb)
            if sort_cb is not None:
                lbl = QLabel("Sort")
                lbl.setObjectName("meta")
                form.addRow(lbl, sort_cb)
            act = QWidgetAction(menu)
            act.setDefaultWidget(container)
            menu.addAction(act)
            filters_btn.setMenu(menu)
            self._filters_btn[key] = filters_btn
            self._filters_menu[key] = menu
            lay.addWidget(filters_btn, 0)

        count = QLabel("")
        count.setObjectName("meta")
        count.setMinimumWidth(38)
        count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._counts[key] = count
        lay.addWidget(count, 0)
        return bar

    def _schedule_rebuild(self, key: str) -> None:
        timer = self._search_timers.get(key)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda k=key: self._rebuild(k))
            self._search_timers[key] = timer
        if timer.isActive():
            timer.stop()
        timer.start(150)

    def _on_chip_toggled(self, key: str) -> None:
        chip = self._running_only.get(key)
        if chip is not None:
            self._qsettings.setValue(f"dashboard/running_{key}", chip.isChecked())
        self._rebuild(key)

    def _on_filter_changed(self, key: str) -> None:
        cb_type = self._type_filter.get(key)
        if cb_type is not None:
            self._qsettings.setValue(f"dashboard/type_{key}", cb_type.currentText())
        cb_node = self._node_filter.get(key)
        if cb_node is not None:
            self._qsettings.setValue(f"dashboard/node_{key}", cb_node.currentText())
        cb_sort = self._sort_combo.get(key)
        if cb_sort is not None:
            self._qsettings.setValue(f"dashboard/sort_{key}", cb_sort.currentText())
        self._rebuild(key)

    def _current_type(self, key: str) -> str:
        cb = self._type_filter.get(key)
        return cb.currentText() if cb is not None else "All"

    def _current_node(self, key: str) -> str:
        cb = self._node_filter.get(key)
        return cb.currentText() if cb is not None else "All nodes"

    def _current_sort(self, key: str) -> str:
        cb = self._sort_combo.get(key)
        return cb.currentText().lower() if cb is not None else "name"

    def _sort_guests(self, guests, key: str):
        mode = self._current_sort(key)
        if mode == "cpu":
            return sorted(guests, key=lambda g: (-float(getattr(g, "cpu", 0) or 0), g.name.lower()))
        if mode == "uptime":
            return sorted(
                guests, key=lambda g: (-int(getattr(g, "uptime", 0) or 0), g.name.lower())
            )
        return sorted(guests, key=lambda g: (g.status != "running", g.name.lower()))

    def _refresh_node_filter(self, key: str) -> None:
        cb = self._node_filter.get(key)
        if cb is None:
            return
        nodes = sorted({n.node for h in self._health for n in h.nodes})
        prev = cb.currentText()
        cb.blockSignals(True)
        cb.clear()
        cb.addItem("All nodes")
        for n in nodes:
            cb.addItem(n)
        idx = cb.findText(prev)
        cb.setCurrentIndex(idx if idx >= 0 else 0)
        cb.blockSignals(False)

    # ------------------------------------------------------------------- theme

    def apply_theme(self, theme: str) -> None:
        try:
            from proxmox_widget.ui.font_fix import ensure_valid_app_font

            ensure_valid_app_font()
            from PySide6.QtWidgets import QApplication as _QApp2

            _a = _QApp2.instance()
            if _a is not None:
                ensure_valid_app_font(_a)
        except Exception:
            pass
        self.pal = palette_for(theme)
        self.setStyleSheet(qss_for(theme))
        self.btn_refresh.setIcon(icons.icon("refresh", 15, self.pal["text_dim"]))
        self.btn_settings.setIcon(icons.icon("settings", 15, self.pal["text_dim"]))
        self.btn_open.setIcon(icons.icon("external", 15, self.pal["accent_ink"]))
        for edit in self._search.values():
            for act in edit.actions():
                act.setIcon(icons.icon("search", 14, self.pal["text_faint"]))
        for btn in getattr(self, "_filters_btn", {}).values():
            try:
                btn.setIcon(icons.icon("filter", 12, self.pal["text_dim"]))
            except Exception:
                pass
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
        self._banner_label.setStyleSheet(f"color: {self.pal['text']}; font-size: {_fs(12)}px;")
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
        offline = [h for h in health if not h.online]
        if offline:
            msgs = "; ".join(f"{h.cluster_name}: {h.error or 'offline'}" for h in offline)
            self.show_message(f"Offline: {msgs}", "error", 6000)

    # ----------------------------------------------------------------- rebuild

    def _on_refresh_clicked(self) -> None:
        self.show_message("Refreshing…", "info", 1500)
        self.refresh_requested.emit()

    def _rebuild_all(self) -> None:
        for key in (OVERVIEW, *LIST_TABS):
            self._rebuild(key)

    def _guest_key(self, cluster_id: str, vmid: int, is_lxc: bool) -> str:
        return f"{cluster_id}:{vmid}:{'ct' if is_lxc else 'vm'}"

    def _clear(self, key: str) -> QVBoxLayout:
        pane = self._panes[key]
        lay = pane.layout()
        assert isinstance(lay, QVBoxLayout)
        self._card_cache.pop(key, None)
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
        if key in self._node_filter:
            self._refresh_node_filter(key)
        if not self._health:
            lay = self._clear(key)
            for c in self._counts.values():
                c.setText("")
            self._empty(lay, "No clusters yet — add one in Settings.")
            return
        if key in (VMS, CTS) and self._rebuild_diff(key, offset):
            return
        pane = self._panes[key]
        pane.setUpdatesEnabled(False)
        lay = self._clear(key)
        builder = {
            OVERVIEW: self._fill_overview,
            NODES: self._fill_nodes,
            VMS: self._fill_vms,
            CTS: self._fill_cts,
            STORAGE: self._fill_storage,
        }[key]
        shown, total = builder(lay)
        pane.setUpdatesEnabled(True)
        if key in (VMS, CTS):
            is_lxc = key == CTS
            cards = [
                lay.itemAt(i).widget()
                for i in range(lay.count())
                if lay.itemAt(i).widget() and lay.itemAt(i).widget().objectName() == "card"  # type: ignore[union-attr]
            ]
            q2 = self._query(key)
            only_running2 = self._running_only[key].isChecked()
            type_f = self._current_type(key)
            node_f = self._current_node(key)
            ordered2: list[tuple] = []
            for h in self._health:
                glist = h.containers if is_lxc else h.vms
                srt = self._sort_guests(glist, key)
                for g in srt:
                    if type_f != "All":
                        want_is_lxc = type_f == "CT"
                        if want_is_lxc != is_lxc:
                            continue
                    if node_f != "All nodes" and str(g.node) != node_f:
                        continue
                    if only_running2 and g.status != "running":
                        continue
                    if not self._matches(q2, g.name, g.vmid, g.node, g.status, h.cluster_name):
                        continue
                    ordered2.append((h, g))
            cache2: dict[str, QFrame] = {}
            for (h, g), wgt in zip(ordered2, cards, strict=False):
                gk = self._guest_key(h.cluster_id, g.vmid, is_lxc)
                if gk not in cache2:
                    cache2[gk] = wgt  # type: ignore[assignment]
            self._card_cache[key] = cache2
        if key in self._counts:
            self._counts[key].setText(f"{shown}/{total}" if shown != total else str(total))
        if shown == 0:
            q = self._query(key)
            self._empty(lay, f'Nothing matches "{q}".' if q else "Nothing here yet.")
        if offset:
            self._restore_scroll(key, bar, offset)

    def _rebuild_diff(self, key: str, offset: int) -> bool:
        is_lxc = key == CTS
        q = self._query(key)
        only_running = self._running_only[key].isChecked()
        type_f = self._current_type(key)
        node_f = self._current_node(key)
        pane = self._panes[key]
        lay = pane.layout()
        assert isinstance(lay, QVBoxLayout)
        bar = self._scrolls[key].verticalScrollBar()
        guests: list[tuple] = []
        for h in self._health:
            glist = h.containers if is_lxc else h.vms
            srt = self._sort_guests(glist, key)
            for g in srt:
                if type_f != "All":
                    want_is_lxc = type_f == "CT"
                    if want_is_lxc != is_lxc:
                        continue
                if node_f != "All nodes" and str(g.node) != node_f:
                    continue
                if only_running and g.status != "running":
                    continue
                if not self._matches(q, g.name, g.vmid, g.node, g.status, h.cluster_name):
                    continue
                guests.append((h, g))
        new_keys = {self._guest_key(h.cluster_id, g.vmid, is_lxc) for h, g in guests}
        old_cache = self._card_cache.get(key)
        if old_cache is None:
            return False
        old_keys = set(old_cache.keys())
        if not old_keys:
            return False
        if new_keys:
            ratio = len(new_keys) / len(old_keys)
            if ratio < 0.5 or ratio > 2:
                self._clear(key)
                return False
        else:
            if old_keys:
                lay2 = self._clear(key)
                shown2 = 0
                total2 = sum(len(h.containers if is_lxc else h.vms) for h in self._health)
                if key in self._counts:
                    self._counts[key].setText(
                        f"{shown2}/{total2}" if shown2 != total2 else str(total2)
                    )
                q2 = self._query(key)
                self._empty(lay2, f'Nothing matches "{q2}".' if q2 else "Nothing here yet.")
                if offset:
                    self._restore_scroll(key, bar, offset)
                return True
        to_remove = old_keys - new_keys
        to_keep = old_keys & new_keys
        to_add = new_keys - old_keys
        for k in to_remove:
            w = old_cache.pop(k)
            lay.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        pane.setUpdatesEnabled(False)
        guest_map = {self._guest_key(h.cluster_id, g.vmid, is_lxc): (h, g) for h, g in guests}
        for k in to_keep:
            h, g = guest_map[k]
            w = old_cache[k]
            try:
                self._update_metrics(w, h, g, is_lxc)
            except Exception:
                pass
        for h, g in guests:
            gk = self._guest_key(h.cluster_id, g.vmid, is_lxc)
            if gk in to_add:
                card = self._guest_card(lay, h, g, is_lxc)
                old_cache[gk] = card
        new_order = [self._guest_key(h.cluster_id, g.vmid, is_lxc) for h, g in guests]
        old_order = list(old_cache.keys()) if not to_add and not to_remove else None
        needs_reorder = bool(
            to_add or to_remove or (old_order is not None and new_order != old_order)
        )
        if needs_reorder:
            for _k, w in list(old_cache.items()):
                if w.parent() is not None:
                    lay.removeWidget(w)
            for h, g in guests:
                gk = self._guest_key(h.cluster_id, g.vmid, is_lxc)
                w = old_cache.get(gk)
                if w is not None:
                    lay.insertWidget(lay.count() - 1, w)
            tmp = {k: old_cache[k] for k in new_order if k in old_cache}
            old_cache.clear()
            old_cache.update(tmp)
        for i in range(lay.count()):
            it = lay.itemAt(i)
            wgt = it.widget() if it else None
            if wgt and wgt.objectName() == "empty":
                lay.removeWidget(wgt)
                wgt.setParent(None)
                wgt.deleteLater()
        shown = len(guests)
        total = sum(len(h.containers if is_lxc else h.vms) for h in self._health)
        if key in self._counts:
            self._counts[key].setText(f"{shown}/{total}" if shown != total else str(total))
        if shown == 0:
            q3 = self._query(key)
            self._empty(lay, f'Nothing matches "{q3}".' if q3 else "Nothing here yet.")
        pane.setUpdatesEnabled(True)
        if offset:
            self._restore_scroll(key, bar, offset)
        return True

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
        if not self._health:
            btn = QPushButton("Add cluster in Settings")
            btn.setObjectName("emptyCta")
            btn.setProperty("cta", True)
            btn.clicked.connect(lambda: self.open_settings.emit())
            lay.insertWidget(lay.count() - 1, btn)

    # ------------------------------------------------------------ card widgets

    def _make_card(
        self, parent: QVBoxLayout | None, accent: str
    ) -> tuple[QFrame, QVBoxLayout, QVBoxLayout]:
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
        if parent is not None:
            parent.insertWidget(parent.count() - 1, card)
        return card, head, body

    def _card(self, parent: QVBoxLayout, accent: str) -> tuple[QVBoxLayout, QVBoxLayout]:
        _card, head, body = self._make_card(parent, accent)
        return head, body

    def _update_metrics(self, card: QFrame, h, g, is_lxc: bool) -> None:
        busy = self._busy.get((h.cluster_id, g.vmid, is_lxc))
        status = busy if busy else g.status
        color = self._status_color(g.status, busy)
        rail = getattr(card, "_cached_rail", None)
        if rail is None:
            rail = card.findChild(QFrame, "accent")
        if rail is not None and color not in rail.styleSheet():
            rail.setStyleSheet(f"QFrame#accent {{ background: {color}; }}")
        pill = getattr(card, "_cached_pill", None)
        if pill is not None:
            if pill.text() != status.upper():
                pill.setText(status.upper())
            needed = f"color: {color}; border: 1px solid {color};"
            if needed not in pill.styleSheet():
                pill.setStyleSheet(
                    f"color: {color}; border: 1px solid {color}; border-radius: 6px;"
                    f" padding: 1px 6px; font-size: {_fs(10)}px; font-weight: 800;"
                )
        dot = getattr(card, "_cached_dot", None)
        if dot is not None and color not in dot.styleSheet():
            dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        bars = getattr(card, "_cached_bars", None)
        if bars is None:
            bars = [b for b in card.findChildren(QProgressBar) if b.objectName() != "busy"]
        running = g.status == "running"
        if running and bars:
            expected: list[int] = []
            expected.append(max(0, min(100, round(g.cpu * 100))))
            if g.maxmem:
                expected.append(max(0, min(100, round(g.mem / g.maxmem * 100))))
            else:
                expected.append(0)
            has_disk = is_lxc and bool(g.maxdisk)
            if has_disk:
                expected.append(max(0, min(100, round(g.disk / g.maxdisk * 100))))
            if len(bars) == len(expected):
                vals = getattr(card, "_cached_vals", None)
                details = getattr(card, "_cached_details", None)
                for idx, (bar, val) in enumerate(zip(bars, expected, strict=False)):
                    if bar.value() == val:
                        continue
                    bar.setValue(val)
                    want = (
                        "hot" if val >= 90 else ("" if idx == 0 else "ram" if idx == 1 else "disk")
                    )
                    if bar.objectName() != want:
                        bar.setObjectName(want)
                    if vals is not None and idx < len(vals) and vals[idx] is not None:
                        txt = f"{val}%"
                        if vals[idx].text() != txt:  # type: ignore[union-attr]
                            vals[idx].setText(txt)  # type: ignore[union-attr]
                    elif vals is None:
                        parent_w = bar.parentWidget()
                        if parent_w is not None:
                            for sib in parent_w.findChildren(QLabel):
                                if sib.objectName() == "value":
                                    sib.setText(f"{val}%")
                                    break
                    if details is not None and idx < len(details) and details[idx] is not None:
                        if idx == 1:
                            txt = f"{fmt_bytes(g.mem)} / {fmt_bytes(g.maxmem)}"
                            if details[idx].text() != txt:  # type: ignore[union-attr]
                                details[idx].setText(txt)  # type: ignore[union-attr]
                        elif has_disk and idx == 2:
                            txt2 = f"{fmt_bytes(g.disk)} / {fmt_bytes(g.maxdisk)}"
                            if details[idx].text() != txt2:  # type: ignore[union-attr]
                                details[idx].setText(txt2)  # type: ignore[union-attr]
                    elif details is None:
                        parent_w = bar.parentWidget()
                        if parent_w is not None:
                            for sib in parent_w.findChildren(QLabel):
                                if sib.objectName() == "meta" and sib.minimumWidth() == 104:
                                    if idx == 1:
                                        sib.setText(f"{fmt_bytes(g.mem)} / {fmt_bytes(g.maxmem)}")
                                    elif has_disk and idx == 2:
                                        sib.setText(f"{fmt_bytes(g.disk)} / {fmt_bytes(g.maxdisk)}")
                                    break

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
            f" padding: 1px 6px; font-size: {_fs(10)}px; font-weight: 800;"
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

    def _menu_button(self, icon_name: str, text: str, tip: str, build_menu) -> QPushButton:
        """A button that shows a QMenu on click instead of firing directly.

        The chevron comes from the stylesheet's menu-indicator, so it re-colors
        with the theme like every other glyph.
        """
        b = self._action_button(icon_name, text, tip)
        b.setObjectName("menuBtn")
        menu = QMenu(b)
        build_menu(menu)
        b.setMenu(menu)
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
                err.setStyleSheet(f"color: {self.pal['err']}; font-size: {_fs(12)}px;")
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
            val.setStyleSheet(f"color: {self.pal['text']}; font-size: {_fs(15)}px; font-weight: 700;")
            tl.addWidget(val)
            row.addWidget(tile, 1)
        return row

    def _fill_nodes(self, lay: QVBoxLayout) -> tuple[int, int]:
        q = self._query(NODES)
        node_f = self._current_node(NODES)
        total = shown = 0
        for h in self._health:
            for n in h.nodes:
                total += 1
                if node_f != "All nodes" and str(n.node) != node_f:
                    continue
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
                shell = self._action_button(
                    "terminal", "SSH", f"SSH to {n.node} in a terminal window"
                )
                shell.clicked.connect(
                    lambda _=False, cid=h.cluster_id, node=n.node: self.console_requested.emit(
                        cid, node, 0, "ssh", False
                    )
                )
                row.addWidget(shell, 1)
                novnc = self._action_button("console", "Shell", f"noVNC shell on {n.node}")
                novnc.clicked.connect(
                    lambda _=False, cid=h.cluster_id, node=n.node: self.console_requested.emit(
                        cid, node, 0, "shell", False
                    )
                )
                row.addWidget(novnc, 1)
                web = self._action_button("external", "Web UI", "Open the Proxmox web UI")
                web.clicked.connect(lambda _=False: self.open_proxmox_requested.emit())
                row.addWidget(web, 1)
                body.addLayout(row)
        return shown, total

    def _guest_card(self, lay: QVBoxLayout, h: ClusterHealth, g, is_lxc: bool) -> QFrame:
        busy = self._busy.get((h.cluster_id, g.vmid, is_lxc))
        status = busy if busy else g.status
        color = self._status_color(g.status, busy)
        card, head, body = self._make_card(lay, color)

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
            spark = SparklineWidget()
            spark.setObjectName("sparkline")
            spark.setVisible(False)
            body.addWidget(spark)
            card._cached_sparkline = spark  # type: ignore[attr-defined]
            try:
                card.setMouseTracking(True)
                card.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

                class _HoverFilter(QObject):  # type: ignore[no-redef]
                    def eventFilter(self, watched, event):  # type: ignore[no-untyped-def]
                        try:
                            t = event.type()
                            if t == QEvent.Type.Enter:
                                spark.setVisible(True)
                            elif t == QEvent.Type.Leave:
                                spark.setVisible(False)
                        except Exception:
                            pass
                        return False

                filt = _HoverFilter(card)
                card.installEventFilter(filt)
                card._hover_filter = filt  # type: ignore[attr-defined]
                orig_enter = card.enterEvent
                orig_leave = card.leaveEvent

                def _enter(e, s=spark, orig=orig_enter):  # type: ignore[no-untyped-def]
                    try:
                        s.setVisible(True)
                    except Exception:
                        pass
                    try:
                        if callable(orig):
                            return orig(e)
                    except Exception:
                        pass

                def _leave(e, s=spark, orig=orig_leave):  # type: ignore[no-untyped-def]
                    try:
                        s.setVisible(False)
                    except Exception:
                        pass
                    try:
                        if callable(orig):
                            return orig(e)
                    except Exception:
                        pass

                card.enterEvent = _enter  # type: ignore[method-assign,assignment]
                card.leaveEvent = _leave  # type: ignore[method-assign,assignment]
            except Exception:
                pass
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
        novnc = self._action_button("console", "Console", "Open the noVNC web console")
        novnc.setEnabled(running)
        novnc.clicked.connect(
            lambda _=False, node=g.node, vmid=g.vmid: self.console_requested.emit(
                h.cluster_id, node, vmid, "novnc", is_lxc
            )
        )
        console.addWidget(novnc, 1)

        def _connect_menu(menu: QMenu) -> None:
            """Every way to get into this guest, native first."""
            acts: list[tuple[str, str, str, str]] = [
                ("terminal", "SSH", "ssh", "SSH into the guest in a terminal window"),
            ]
            if not is_lxc:
                acts.append(("remote", "RDP", "rdp", "RDP to the guest IP, needs the guest agent"))
                acts.append(("monitor", "SPICE", "spice", "Open with remote-viewer over SPICE"))
            else:
                acts.append(
                    ("console", "LXC console", "lxc_shell", "Proxmox console for this container")
                )
            for icon_name, text, kind, tip in acts:
                a = QAction(icons.icon(icon_name, 14, self.pal["text_dim"]), text, menu)
                a.setToolTip(tip)
                a.triggered.connect(
                    lambda _=False, k=kind, node=g.node, vmid=g.vmid: self.console_requested.emit(
                        h.cluster_id, node, vmid, k, is_lxc
                    )
                )
                menu.addAction(a)

        connect = self._menu_button(
            "chevron_down", "Connect", "All ways to reach this guest", _connect_menu
        )
        connect.setEnabled(running)
        console.addWidget(connect, 1)
        body.addLayout(console)
        try:
            bars = [b for b in card.findChildren(QProgressBar) if b.objectName() != "busy"]
            card._cached_bars = bars  # type: ignore[attr-defined]
            vals: list[QLabel] = []
            details: list[QLabel | None] = []
            for b in bars:
                pw = b.parentWidget()
                v = None
                d = None
                if pw is not None:
                    for sib in pw.findChildren(QLabel):
                        if sib.objectName() == "value":
                            v = sib
                        elif sib.objectName() == "meta" and sib.minimumWidth() == 104:
                            d = sib
                vals.append(v)  # type: ignore[arg-type]
                details.append(d)
            card._cached_vals = vals  # type: ignore[attr-defined]
            card._cached_details = details  # type: ignore[attr-defined]
            rail = card.findChild(QFrame, "accent")
            card._cached_rail = rail  # type: ignore[attr-defined]
            pills = [
                lbl
                for lbl in card.findChildren(QLabel)
                if lbl.objectName() == "pill" and not lbl.text().startswith("#")
            ]
            card._cached_pill = pills[0] if pills else None  # type: ignore[attr-defined]
            dots = [
                lbl for lbl in card.findChildren(QLabel) if lbl.width() == 9 and lbl.height() == 9
            ]
            card._cached_dot = dots[0] if dots else None  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            selected = (h.cluster_id, g.vmid, is_lxc) in self._selected
            self._apply_selection_style(card, selected)
            orig_press = card.mousePressEvent

            def _press(e, cid=h.cluster_id, vm=g.vmid, lxc=is_lxc, orig=orig_press):  # type: ignore[no-untyped-def]
                try:
                    self._on_card_clicked(cid, vm, lxc, e.modifiers(), e.button())
                except Exception:
                    pass
                try:
                    if callable(orig):
                        return orig(e)
                except Exception:
                    pass

            card.mousePressEvent = _press  # type: ignore[method-assign,assignment]
        except Exception:
            pass
        return card

    def _fill_guests(self, lay: QVBoxLayout, key: str, is_lxc: bool) -> tuple[int, int]:
        q = self._query(key)
        only_running = self._running_only[key].isChecked()
        type_f = self._current_type(key)
        node_f = self._current_node(key)
        if type_f != "All":
            want_is_lxc = type_f == "CT"
            if want_is_lxc != is_lxc:
                total_all = sum(len(h.containers if is_lxc else h.vms) for h in self._health)
                return 0, total_all
        total = shown = 0
        for h in self._health:
            guests = h.containers if is_lxc else h.vms
            ordered = self._sort_guests(guests, key)
            for g in ordered:
                total += 1
                if node_f != "All nodes" and str(g.node) != node_f:
                    continue
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
        node_f = self._current_node(STORAGE)
        total = shown = 0
        for h in self._health:
            for s in h.storages:
                total += 1
                if node_f != "All nodes" and str(s.node) != node_f:
                    continue
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
