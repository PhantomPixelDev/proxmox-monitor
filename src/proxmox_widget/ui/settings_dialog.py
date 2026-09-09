from __future__ import annotations

import re

from PySide6.QtCore import Signal, Qt
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
    QVBoxLayout,
    QWidget,
)

from proxmox_widget.config.manager import add_or_update_cluster, get_cluster_secret, remove_cluster
from proxmox_widget.config.models import AppSettings, AuthMode, ClusterConfig


def _parse_host_port(raw: str) -> tuple[str, int]:
    raw = raw.strip()
    # accept https://192.168.10.2:8006/ or 192.168.10.2:8006 or 192.168.10.2
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

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ProxmoxWidget — Settings")
        self.setMinimumWidth(540)
        self._settings = settings.model_copy(deep=True)
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)

        # clusters list
        grp = QGroupBox("Clusters")
        v = QVBoxLayout(grp)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._on_select)
        v.addWidget(self.list)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ Add")
        btn_add.clicked.connect(self._add_cluster)
        btn_del = QPushButton("− Remove")
        btn_del.clicked.connect(self._del_cluster)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_del)
        btn_row.addStretch()
        v.addLayout(btn_row)
        lay.addWidget(grp)

        # cluster form
        self.form_box = QGroupBox("Cluster — select or add one")
        form = QFormLayout(self.form_box)
        self.ed_id = QLineEdit()
        self.ed_id.setPlaceholderText("e.g. pve-home")
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("e.g. Home Lab")
        self.ed_host = QLineEdit()
        self.ed_host.setPlaceholderText("192.168.10.2 or https://192.168.10.2:8006")
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1, 65535)
        self.spin_port.setValue(8006)
        self.combo_auth = QComboBox()
        self.combo_auth.addItems(["API Token (recommended)", "Password (user + password)"])
        self.combo_auth.currentIndexChanged.connect(self._update_auth_fields)
        self.ed_user = QLineEdit()
        self.ed_user.setPlaceholderText("root@pam")
        self.ed_user.setText("root@pam")
        self.ed_token_id = QLineEdit()
        self.ed_token_id.setPlaceholderText("root@pam!widget  or  user@pve!mytoken")
        self.ed_secret = QLineEdit()
        self.ed_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_secret.setPlaceholderText("token secret  or  password")
        self.chk_verify = QCheckBox("Verify TLS (disable for self-signed)")
        form.addRow("ID", self.ed_id)
        form.addRow("Name", self.ed_name)
        form.addRow("Host", self.ed_host)
        form.addRow("Port", self.spin_port)
        form.addRow("Auth", self.combo_auth)
        form.addRow("Username", self.ed_user)
        form.addRow("Token ID", self.ed_token_id)
        form.addRow("Secret / Password", self.ed_secret)
        form.addRow("", self.chk_verify)
        row_save = QHBoxLayout()
        self.btn_save_cluster = QPushButton("Save Cluster")
        self.btn_save_cluster.setObjectName("primary")
        self.btn_save_cluster.clicked.connect(self._save_current_cluster)
        row_save.addWidget(self.btn_save_cluster)
        self.lbl_cluster_hint = QLabel("")
        self.lbl_cluster_hint.setObjectName("muted")
        self.lbl_cluster_hint.setWordWrap(True)
        row_save.addWidget(self.lbl_cluster_hint, 1)
        form.addRow(row_save)
        lay.addWidget(self.form_box)

        # app prefs
        grp2 = QGroupBox("Preferences")
        f2 = QFormLayout(grp2)
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(5, 3600)
        self.spin_interval.setValue(self._settings.refresh_interval_seconds)
        self.spin_interval.setSuffix(" s")
        self.combo_theme = QComboBox()
        self.combo_theme.addItems(["system", "light", "dark"])
        self.combo_theme.setCurrentText(self._settings.theme.value)
        self.chk_notifs = QCheckBox()
        self.chk_notifs.setChecked(self._settings.notifications_enabled)
        self.chk_minimized = QCheckBox()
        self.chk_minimized.setChecked(self._settings.start_minimized)
        f2.addRow("Refresh interval", self.spin_interval)
        f2.addRow("Theme", self.combo_theme)
        f2.addRow("Notifications", self.chk_notifs)
        f2.addRow("Start minimized", self.chk_minimized)
        lay.addWidget(grp2)

        # dialog buttons
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._on_save_all)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

        self._refresh_list()
        self._update_auth_fields()

    def _refresh_list(self) -> None:
        self.list.clear()
        for c in self._settings.clusters:
            item = QListWidgetItem(f"{c.name}  —  {c.host}:{c.port}  ({c.auth_mode.value})")
            item.setData(Qt.ItemDataRole.UserRole, c.id)
            self.list.addItem(item)
        if self._settings.clusters:
            self.list.setCurrentRow(0)

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
        self.lbl_cluster_hint.setText(f"Editing {c.id} — secrets loaded from keyring" if secret else "")

    def _update_auth_fields(self) -> None:
        is_token = self.combo_auth.currentIndex() == 0
        self.ed_token_id.setEnabled(is_token)
        self.ed_user.setEnabled(not is_token)

    def _add_cluster(self) -> None:
        self.ed_id.setText("")
        self.ed_name.setText("")
        self.ed_host.setText("192.168.10.2")
        self.spin_port.setValue(8006)
        self.ed_token_id.setText("root@pam!widget")
        self.ed_user.setText("root@pam")
        self.ed_secret.setText("")
        self.chk_verify.setChecked(False)
        self.list.clearSelection()
        self.ed_id.setFocus()

    def _del_cluster(self) -> None:
        row = self.list.currentRow()
        if row < 0:
            return
        cid = self.list.item(row).data(Qt.ItemDataRole.UserRole)
        self._settings = remove_cluster(self._settings, cid)
        self._refresh_list()
        self.lbl_cluster_hint.setText(f"Removed {cid}")

    def _save_current_cluster(self) -> None:
        cid = self.ed_id.text().strip()
        name = self.ed_name.text().strip() or cid
        host_raw = self.ed_host.text().strip()
        secret = self.ed_secret.text().strip()
        if not cid:
            QMessageBox.warning(self, "Missing ID", "Cluster ID is required (e.g. pve-home)")
            return
        if not host_raw:
            QMessageBox.warning(self, "Missing host", "Host is required")
            return
        if not secret:
            QMessageBox.warning(self, "Missing secret", "Secret / password is required")
            return
        host, port_from_host = _parse_host_port(host_raw)
        port = self.spin_port.value()
        # if host string contained explicit port and spin is still 8006, use parsed
        if ":" in host_raw and port == 8006 and port_from_host != 8006:
            port = port_from_host
        is_token = self.combo_auth.currentIndex() == 0
        token_id = self.ed_token_id.text().strip()
        username = self.ed_user.text().strip() or "root@pam"
        if is_token and not token_id:
            QMessageBox.warning(self, "Missing Token ID", "Token ID like root@pam!widget required for token auth")
            return
        cfg = ClusterConfig(
            id=cid,
            name=name,
            host=host,
            port=port,
            verify_ssl=self.chk_verify.isChecked(),
            auth_mode=AuthMode.TOKEN if is_token else AuthMode.PASSWORD,
            token_id=token_id if is_token else "",
            username=username if not is_token else "root@pam",
        )
        self._settings = add_or_update_cluster(self._settings, cfg, secret)
        self._refresh_list()
        # select saved
        for i, c in enumerate(self._settings.clusters):
            if c.id == cid:
                self.list.setCurrentRow(i)
                break
        self.lbl_cluster_hint.setText(f"Saved {cid} → keyring ✓")

    def _on_save_all(self) -> None:
        # ensure current cluster saved if user edited but didn't hit Save Cluster and secret present
        # don't auto-save empty
        self._settings.refresh_interval_seconds = int(self.spin_interval.value())
        from proxmox_widget.config.models import ThemeMode

        self._settings.theme = ThemeMode(self.combo_theme.currentText())
        self._settings.notifications_enabled = self.chk_notifs.isChecked()
        self._settings.start_minimized = self.chk_minimized.isChecked()
        from proxmox_widget.config.manager import save_settings

        save_settings(self._settings)
        self.settings_saved.emit(self._settings)
        self.accept()
