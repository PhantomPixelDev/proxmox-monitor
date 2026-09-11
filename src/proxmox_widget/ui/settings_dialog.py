from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from proxmox_widget.config.manager import add_or_update_cluster, get_cluster_secret, remove_cluster
from proxmox_widget.config.models import AppSettings, AuthMode, ClusterConfig


def _parse_host_port(raw: str) -> tuple[str, int]:
    raw = raw.strip()
    raw = re.sub(r"^https?://", "", raw)
    raw = raw.strip("/")
    if ":" in raw:
        host, port_s = raw.rsplit(":", 1)
        try:
            return host, int(port_s)
        except ValueError:
            return host, 8006
    return raw, 8006


class SettingsDialog(QDialog):
    settings_saved = Signal(AppSettings)
    test_requested = Signal(ClusterConfig, str)

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ProxmoxWidget — Settings")
        self.setMinimumSize(700, 460)
        self.resize(740, 500)
        self._settings = settings.model_copy(deep=True)
        self._build()

    def _build_remote_access_group(self) -> QGroupBox:
        c = self._current_cluster()
        cur = c if c is not None else (self._settings.clusters[0] if self._settings.clusters else None)
        box = QGroupBox("Remote access  —  per selected cluster")
        f = QFormLayout(box)
        f.setSpacing(8)

        self.ed_ssh_user = QLineEdit()
        self.ed_ssh_user.setPlaceholderText("root")
        self.ed_ssh_user.setText(cur.ssh_user if cur else "root")
        self.spin_ssh_port = QSpinBox()
        self.spin_ssh_port.setRange(1, 65535)
        self.spin_ssh_port.setValue(cur.ssh_port if cur else 22)
        self.ed_rdp_user = QLineEdit()
        self.ed_rdp_user.setPlaceholderText("Administrator — leave empty to prompt")
        self.ed_rdp_user.setText(cur.rdp_user if cur else "")
        self.spin_rdp_port = QSpinBox()
        self.spin_rdp_port.setRange(1, 65535)
        self.spin_rdp_port.setValue(cur.rdp_port if cur else 3389)

        f.addRow("SSH user", self.ed_ssh_user)
        f.addRow("SSH port", self.spin_ssh_port)
        f.addRow("RDP username", self.ed_rdp_user)
        f.addRow("RDP port", self.spin_rdp_port)

        self.lbl_remote_hint = QLabel("")
        self.lbl_remote_hint.setObjectName("meta")
        self.lbl_remote_hint.setWordWrap(True)
        f.addRow(self.lbl_remote_hint)

        hint = QLabel("SSH opens in your own terminal — keys and agent work as usual; only user and port are stored.")
        hint.setObjectName("meta")
        hint.setWordWrap(True)
        f.addRow(hint)
        self._update_remote_hint()
        return box

    def _update_remote_hint(self) -> None:
        if not hasattr(self, "lbl_remote_hint"):
            return
        c = self._current_cluster()
        if c:
            self.lbl_remote_hint.setText(f"Editing: {c.name}  ({c.id})")
        elif self._settings.clusters:
            self.lbl_remote_hint.setText("Select a cluster on the left to edit its remote access.")
        else:
            self.lbl_remote_hint.setText("Add a cluster first — remote access is per cluster.")

    def _current_cluster(self) -> ClusterConfig | None:
        if not hasattr(self, "list"):
            return None
        row = self.list.currentRow()
        if 0 <= row < len(self._settings.clusters):
            return self._settings.clusters[row]
        return None

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._on_select)

        # cluster form widgets — keep names for compatibility
        self.ed_id = QLineEdit()
        self.ed_id.setPlaceholderText("pve-home")
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("Home Lab")
        self.ed_host = QLineEdit()
        self.ed_host.setPlaceholderText("192.168.10.2  or  https://host:8006")
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1, 65535)
        self.spin_port.setValue(8006)
        self.combo_auth = QComboBox()
        self.combo_auth.addItems(["API Token — recommended", "Password"])
        self.combo_auth.currentIndexChanged.connect(self._update_auth_fields)
        self.ed_user = QLineEdit()
        self.ed_user.setPlaceholderText("root@pam")
        self.ed_user.setText("root@pam")
        self.ed_token_id = QLineEdit()
        self.ed_token_id.setPlaceholderText("root@pam!widget")
        self.ed_secret = QLineEdit()
        self.ed_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_secret.setPlaceholderText("paste token secret or password")
        self.chk_verify = QCheckBox("Verify TLS — disable for self-signed certs")
        self.chk_verify.setToolTip("Disable only for self-signed — add CA to trust store otherwise")
        self.btn_save_cluster = QPushButton("Save cluster")
        self.btn_save_cluster.setObjectName("primary")
        self.btn_save_cluster.clicked.connect(self._save_current_cluster)
        self.btn_test = QPushButton("Test")
        self.btn_test.clicked.connect(self._test_current_cluster)
        self.lbl_cluster_hint = QLabel("")
        self.lbl_cluster_hint.setObjectName("meta")
        self.lbl_cluster_hint.setWordWrap(True)
        self.ed_id.textChanged.connect(self._validate_cluster_form)
        self.ed_host.textChanged.connect(self._validate_cluster_form)

        self._remote_widget = self._build_remote_access_group()

        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(5, 3600)
        self.spin_interval.setValue(self._settings.refresh_interval_seconds)
        self.spin_interval.setSuffix(" s")
        self.combo_theme = QComboBox()
        self.combo_theme.addItems(["system", "light", "dark"])
        self.combo_theme.setCurrentText(self._settings.theme.value)
        self.chk_notifs = QCheckBox("Enable desktop notifications")
        self.chk_notifs.setChecked(self._settings.notifications_enabled)
        self.chk_minimized = QCheckBox("Start minimized to tray")
        self.chk_minimized.setChecked(self._settings.start_minimized)
        self.chk_close_tray = QCheckBox("Close to tray instead of quitting")
        self.chk_close_tray.setChecked(getattr(self._settings, "close_to_tray", True))

        tabs = QTabWidget()

        # Clusters tab — 2 columns: list left, form right
        tab_clusters = QWidget()
        h = QHBoxLayout(tab_clusters)
        h.setContentsMargins(8, 8, 8, 8)
        h.setSpacing(10)

        left = QGroupBox("Clusters")
        lv = QVBoxLayout(left)
        lv.setSpacing(8)
        lv.addWidget(self.list, 1)
        br = QHBoxLayout()
        br.setSpacing(6)
        btn_add = QPushButton("+ Add")
        btn_add.clicked.connect(self._add_cluster)
        btn_del = QPushButton("− Remove")
        btn_del.clicked.connect(self._del_cluster)
        br.addWidget(btn_add)
        br.addWidget(btn_del)
        br.addStretch()
        lv.addLayout(br)
        left.setMinimumWidth(200)
        left.setMaximumWidth(250)
        h.addWidget(left, 0)

        form_box = QGroupBox("Cluster details")
        form = QFormLayout(form_box)
        form.setSpacing(8)
        form.addRow("ID", self.ed_id)
        form.addRow("Name", self.ed_name)
        # Host + Port on one row to save vertical space, but keep it simple
        host_port = QWidget()
        hp = QHBoxLayout(host_port)
        hp.setContentsMargins(0, 0, 0, 0)
        hp.setSpacing(8)
        hp.addWidget(self.ed_host, 1)
        hp.addWidget(self.spin_port, 0)
        form.addRow("Host / Port", host_port)
        form.addRow("Auth", self.combo_auth)
        form.addRow("Token ID", self.ed_token_id)
        form.addRow("Username", self.ed_user)
        form.addRow("Secret", self.ed_secret)
        form.addRow("", self.chk_verify)
        save_row = QHBoxLayout()
        save_row.setSpacing(8)
        save_row.addWidget(self.btn_save_cluster)
        save_row.addWidget(self.btn_test)
        save_row.addWidget(self.lbl_cluster_hint, 1)
        form.addRow(save_row)
        h.addWidget(form_box, 1)

        tabs.addTab(tab_clusters, "Clusters")

        # Remote access tab — simple single group
        tab_remote = QWidget()
        rv = QVBoxLayout(tab_remote)
        rv.setContentsMargins(8, 8, 8, 8)
        rv.addWidget(self._remote_widget)
        rv.addStretch()
        tabs.addTab(tab_remote, "Remote Access")

        # General tab — simple prefs
        tab_general = QWidget()
        gv = QVBoxLayout(tab_general)
        gv.setContentsMargins(8, 8, 8, 8)
        pref_box = QGroupBox("Preferences")
        pf = QFormLayout(pref_box)
        pf.setSpacing(10)
        pf.addRow("Refresh interval", self.spin_interval)
        pf.addRow("Theme", self.combo_theme)
        pf.addRow("", self.chk_notifs)
        pf.addRow("", self.chk_minimized)
        pf.addRow("", self.chk_close_tray)
        gv.addWidget(pref_box)
        gv.addStretch()
        tabs.addTab(tab_general, "General")

        lay.addWidget(tabs, 1)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        save_btn = btns.button(QDialogButtonBox.StandardButton.Save)
        if save_btn is not None:
            save_btn.setText("Save")
        btns.accepted.connect(self._on_save_all)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

        self._refresh_list()
        self._update_auth_fields()
        self._update_remote_hint()
        self._validate_cluster_form()

    def _refresh_list(self) -> None:
        self.list.clear()
        for c in self._settings.clusters:
            item = QListWidgetItem(f"{c.name}  —  {c.host}:{c.port}")
            item.setData(Qt.ItemDataRole.UserRole, c.id)
            self.list.addItem(item)
        if self._settings.clusters:
            self.list.setCurrentRow(0)
        else:
            self._update_remote_hint()

    def _on_select(self, row: int) -> None:
        if row < 0 or row >= len(self._settings.clusters):
            return
        c = self._settings.clusters[row]
        self.ed_id.setText(c.id)
        self.ed_name.setText(c.name)
        self.ed_host.setText(c.host)
        self.spin_port.setValue(c.port)
        self.chk_verify.setChecked(c.verify_ssl)
        is_token = c.auth_mode == AuthMode.TOKEN
        self.combo_auth.setCurrentIndex(0 if is_token else 1)
        self.ed_user.setText(c.username if not is_token else "root@pam")
        self.ed_token_id.setText(c.token_id)
        secret = get_cluster_secret(c.id) or ""
        self.ed_secret.setText(secret)
        self._load_remote_fields(c)
        self._update_remote_hint()
        self.lbl_cluster_hint.setText(f"Editing {c.id} — secret from keyring" if secret else f"Editing {c.id}")
        self._validate_cluster_form()

    def _load_remote_fields(self, c: ClusterConfig) -> None:
        self.ed_ssh_user.setText(c.ssh_user)
        self.spin_ssh_port.setValue(c.ssh_port)
        self.ed_rdp_user.setText(c.rdp_user)
        self.spin_rdp_port.setValue(c.rdp_port)
        self._update_remote_hint()

    def _update_auth_fields(self) -> None:
        is_token = self.combo_auth.currentIndex() == 0
        self.ed_token_id.setEnabled(is_token)
        self.ed_user.setEnabled(not is_token)

    def _validate_id_text(self, text: str) -> str | None:
        t = text.strip()
        if not t:
            return "ID required — e.g. pve-home"
        if not re.match(r"^[a-z0-9][a-z0-9_-]{1,31}$", t):
            return "id must match ^[a-z0-9][a-z0-9_-]{1,31}$ (2-32 chars, lower alnum start)"
        return None

    def _validate_host_text(self, text: str) -> str | None:
        t = text.strip()
        if not t:
            return "host must not be empty"
        try:
            ClusterConfig(id="ab", name="t", host=t, port=8006)
            return None
        except Exception as e:
            msg = str(e).split("\n")[0]
            if "host" in msg.lower() or "invalid" in msg.lower():
                return msg
            return "invalid host"

    def _validate_cluster_form(self) -> bool:
        id_err = self._validate_id_text(self.ed_id.text())
        if id_err:
            self.lbl_cluster_hint.setStyleSheet("color: #f87171;")
            self.lbl_cluster_hint.setText(id_err)
            self.btn_save_cluster.setEnabled(False)
            return False
        host_err = self._validate_host_text(self.ed_host.text())
        if host_err:
            self.lbl_cluster_hint.setStyleSheet("color: #f87171;")
            self.lbl_cluster_hint.setText(host_err)
            self.btn_save_cluster.setEnabled(False)
            return False
        self.btn_save_cluster.setEnabled(True)
        cur = self.lbl_cluster_hint.text()
        if cur and ("id must" in cur or "host" in cur.lower() or "invalid" in cur.lower()):
            self.lbl_cluster_hint.setText("")
            self.lbl_cluster_hint.setStyleSheet("")
        return True

    def _add_cluster(self) -> None:
        self.ed_id.setText("")
        self.ed_name.setText("")
        self.ed_host.setText("192.168.10.2")
        self.spin_port.setValue(8006)
        self.ed_token_id.setText("root@pam!widget")
        self.ed_user.setText("root@pam")
        self.ed_secret.setText("")
        self.chk_verify.setChecked(True)
        self.ed_ssh_user.setText("root")
        self.spin_ssh_port.setValue(22)
        self.ed_rdp_user.setText("")
        self.spin_rdp_port.setValue(3389)
        self._update_remote_hint()
        self.list.clearSelection()
        self.lbl_cluster_hint.setText("New cluster — fill ID, host and secret, then Save cluster")
        self._validate_cluster_form()
        self.ed_id.setFocus()

    def _del_cluster(self) -> None:
        row = self.list.currentRow()
        if row < 0:
            return
        item = self.list.item(row)
        if item is None:
            return
        cid = item.data(Qt.ItemDataRole.UserRole)
        self._settings = remove_cluster(self._settings, cid)
        self._refresh_list()
        self._update_remote_hint()
        self.lbl_cluster_hint.setText(f"Removed {cid}")

    def _form_cluster(self) -> tuple[ClusterConfig, str] | None:
        cid = self.ed_id.text().strip()
        host_raw = self.ed_host.text().strip()
        secret = self.ed_secret.text().strip()
        if not cid or not host_raw or not secret:
            return None
        if self._validate_id_text(cid) is not None:
            return None
        if self._validate_host_text(host_raw) is not None:
            return None
        host, port_from_host = _parse_host_port(host_raw)
        port = self.spin_port.value()
        if ":" in host_raw and port == 8006 and port_from_host != 8006:
            port = port_from_host
        is_token = self.combo_auth.currentIndex() == 0
        token_id = self.ed_token_id.text().strip()
        if is_token and not token_id:
            return None
        if is_token and "!" not in token_id:
            return None
        try:
            cfg = ClusterConfig(
                id=cid,
                name=self.ed_name.text().strip() or cid,
                host=host,
                port=port,
                verify_ssl=self.chk_verify.isChecked(),
                auth_mode=AuthMode.TOKEN if is_token else AuthMode.PASSWORD,
                token_id=token_id if is_token else "",
                username=self.ed_user.text().strip() or "root@pam" if not is_token else "root@pam",
            )
        except Exception:
            return None
        return (cfg, secret)

    def _test_current_cluster(self) -> None:
        form = self._form_cluster()
        if form is None:
            QMessageBox.warning(self, "Incomplete", "Fill in ID, host, secret and token ID before testing")
            return
        self.btn_test.setEnabled(False)
        self.lbl_cluster_hint.setText("Testing…")
        self.test_requested.emit(*form)

    def show_test_result(self, text: str, ok: bool) -> None:
        self.btn_test.setEnabled(True)
        self.lbl_cluster_hint.setStyleSheet("color: #4ade80;" if ok else "color: #f87171;")
        self.lbl_cluster_hint.setText(text)

    def _save_current_cluster(self) -> None:
        cid = self.ed_id.text().strip()
        name = self.ed_name.text().strip() or cid
        host_raw = self.ed_host.text().strip()
        secret = self.ed_secret.text().strip()
        id_err = self._validate_id_text(cid)
        if id_err:
            self._validate_cluster_form()
            QMessageBox.warning(self, "Invalid ID", id_err)
            return
        if not cid:
            QMessageBox.warning(self, "Missing ID", "Cluster ID is required (e.g. pve-home)")
            return
        host_err = self._validate_host_text(host_raw) if host_raw else "host must not be empty"
        if host_err:
            self._validate_cluster_form()
            QMessageBox.warning(self, "Invalid host", host_err)
            return
        if not host_raw:
            QMessageBox.warning(self, "Missing host", "Host is required")
            return
        if not secret:
            QMessageBox.warning(self, "Missing secret", "Secret / password is required")
            return
        host, port_from_host = _parse_host_port(host_raw)
        port = self.spin_port.value()
        if ":" in host_raw and port == 8006 and port_from_host != 8006:
            port = port_from_host
        is_token = self.combo_auth.currentIndex() == 0
        token_id = self.ed_token_id.text().strip()
        username = self.ed_user.text().strip() or "root@pam"
        if is_token and not token_id:
            QMessageBox.warning(self, "Missing Token ID", "Token ID like root@pam!widget required for token auth")
            return
        if is_token and "!" not in token_id:
            self.lbl_cluster_hint.setStyleSheet("color: #f87171;")
            self.lbl_cluster_hint.setText('token_id must contain "!"')
            QMessageBox.warning(self, "Invalid Token ID", 'token_id must contain "!" (e.g. user@realm!token)')
            return
        try:
            cfg = ClusterConfig(
                id=cid,
                name=name,
                host=host,
                port=port,
                verify_ssl=self.chk_verify.isChecked(),
                auth_mode=AuthMode.TOKEN if is_token else AuthMode.PASSWORD,
                token_id=token_id if is_token else "",
                username=username if not is_token else "root@pam",
                ssh_user=self.ed_ssh_user.text().strip() or "root",
                ssh_port=self.spin_ssh_port.value(),
                rdp_user=self.ed_rdp_user.text().strip(),
                rdp_port=self.spin_rdp_port.value(),
            )
        except Exception as e:
            self.lbl_cluster_hint.setStyleSheet("color: #f87171;")
            self.lbl_cluster_hint.setText(str(e).split("\n")[0])
            QMessageBox.warning(self, "Invalid cluster", str(e).split("\n")[0])
            return
        self._settings = add_or_update_cluster(self._settings, cfg, secret)
        self._refresh_list()
        for i, c in enumerate(self._settings.clusters):
            if c.id == cid:
                self.list.setCurrentRow(i)
                break
        self.lbl_cluster_hint.setStyleSheet("color: #4ade80;")
        self.lbl_cluster_hint.setText(f"Saved {cid} → keyring ✓")

    def _on_save_all(self) -> None:
        current = self._current_cluster()
        if current is not None:
            current.ssh_user = self.ed_ssh_user.text().strip() or "root"
            current.ssh_port = self.spin_ssh_port.value()
            current.rdp_user = self.ed_rdp_user.text().strip()
            current.rdp_port = self.spin_rdp_port.value()
        self._settings.refresh_interval_seconds = int(self.spin_interval.value())
        from proxmox_widget.config.models import ThemeMode

        self._settings.theme = ThemeMode(self.combo_theme.currentText())
        self._settings.notifications_enabled = self.chk_notifs.isChecked()
        self._settings.start_minimized = self.chk_minimized.isChecked()
        self._settings.close_to_tray = self.chk_close_tray.isChecked()
        from proxmox_widget.config.manager import save_settings

        save_settings(self._settings)
        self.settings_saved.emit(self._settings)
        self.accept()
