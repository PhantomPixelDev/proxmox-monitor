import json
from unittest.mock import MagicMock

import pytest

import proxmox_widget.core.actions as actions
from proxmox_widget.config.manager import (
    _config_path,
    add_or_update_cluster,
    audit_keyring_orphans,
    delete_cluster_secret,
    delete_cluster_token,
    find_orphan_cluster_ids,
    get_all_cluster_ids,
    get_cluster_secret,
    get_cluster_token,
    load_settings,
    remove_cluster,
    save_settings,
    set_cluster_password,
    set_cluster_secret,
    set_cluster_token,
)
from proxmox_widget.config.models import AppSettings, AuthMode, ClusterConfig, ClusterHealth
from proxmox_widget.ui.dashboard import Dashboard
from proxmox_widget.ui.settings_dialog import SettingsDialog, _parse_host_port
from proxmox_widget.utils.format import bar


def _cfg(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    monkeypatch.setattr("proxmox_widget.config.manager._config_path", lambda: p)
    return p


def _mock_keyring(monkeypatch):
    store: dict[tuple[str, str], str] = {}

    def set_pw(svc, user, pw):
        store[(svc, user)] = pw

    def get_pw(svc, user):
        return store.get((svc, user))

    def del_pw(svc, user):
        if (svc, user) in store:
            del store[(svc, user)]
        else:
            raise KeyError

    monkeypatch.setattr("proxmox_widget.config.manager.keyring.set_password", set_pw)
    monkeypatch.setattr("proxmox_widget.config.manager.keyring.get_password", get_pw)
    monkeypatch.setattr("proxmox_widget.config.manager.keyring.delete_password", del_pw)
    monkeypatch.setattr("proxmox_widget.config.manager._known_ids", set(), raising=False)
    return store


def test_manager_round_trip_platformdirs_keyring_mock(monkeypatch, tmp_path):
    cfg = _cfg(tmp_path, monkeypatch)
    _mock_keyring(monkeypatch)
    s = AppSettings(clusters=[ClusterConfig(id="pve", name="PVE", host="10.0.0.1")])
    set_cluster_secret("pve", "s3cr3t")
    assert get_cluster_secret("pve") == "s3cr3t"
    assert get_cluster_token("pve") == "s3cr3t"
    save_settings(s)
    assert cfg.exists()
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["clusters"][0]["id"] == "pve"
    assert "secret" not in json.dumps(data).lower()
    loaded = load_settings()
    assert loaded.clusters[0].id == "pve"
    assert loaded.refresh_interval_seconds == 30


def test_manager_config_path_mkdir(monkeypatch, tmp_path):
    base = tmp_path / "a" / "b"
    monkeypatch.setattr("proxmox_widget.config.manager.user_config_dir", lambda *_a, **_k: str(base))
    p = _config_path()
    assert p == base / "config.json"
    assert base.exists()


def test_manager_keyring_helpers(monkeypatch, tmp_path):
    _cfg(tmp_path, monkeypatch)
    store = _mock_keyring(monkeypatch)
    set_cluster_token("tok1", "val1")
    assert get_cluster_token("tok1") == "val1"
    set_cluster_password("pwd1", "pass1")
    assert get_cluster_secret("pwd1") == "pass1"
    store[("proxmox-widget/legacy", "token")] = "legacy-val"
    assert get_cluster_secret("legacy") == "legacy-val"
    assert get_cluster_secret("nonexistent") is None
    delete_cluster_token("tok1")
    assert get_cluster_secret("tok1") is None
    set_cluster_secret("del1", "x")
    delete_cluster_secret("del1")
    assert get_cluster_secret("del1") is None
    delete_cluster_secret("del1")


def test_manager_get_secret_handles_exception(monkeypatch, tmp_path):
    _cfg(tmp_path, monkeypatch)
    _mock_keyring(monkeypatch)

    def bad_get(*a, **k):
        raise RuntimeError("keyring down")

    monkeypatch.setattr("proxmox_widget.config.manager.keyring.get_password", bad_get)
    assert get_cluster_secret("any") is None


def test_manager_save_chmod_exception(monkeypatch, tmp_path):
    cfg = _cfg(tmp_path, monkeypatch)
    _mock_keyring(monkeypatch)

    def bad_chmod(*a, **k):
        raise OSError("chmod fail")

    monkeypatch.setattr("proxmox_widget.config.manager.os.chmod", bad_chmod)
    save_settings(AppSettings())
    assert cfg.exists()


def test_manager_load_copyfile_exception(monkeypatch, tmp_path, caplog):
    cfg = _cfg(tmp_path, monkeypatch)
    _mock_keyring(monkeypatch)
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("{ bad json", encoding="utf-8")

    def bad_copy(*a, **k):
        raise OSError("copy fail")

    monkeypatch.setattr("proxmox_widget.config.manager.shutil.copyfile", bad_copy)
    s = load_settings()
    assert isinstance(s, AppSettings)


def test_manager_add_or_update_rename_edge_cases(monkeypatch, tmp_path):
    _cfg(tmp_path, monkeypatch)
    _mock_keyring(monkeypatch)
    s = AppSettings(clusters=[
        ClusterConfig(id="aa", name="AA", host="1.1.1.1"),
        ClusterConfig(id="bb", name="BB", host="2.2.2.2"),
        ClusterConfig(id="cc", name="CC", host="3.3.3.3"),
    ])
    set_cluster_secret("aa", "secret-aa")
    new = ClusterConfig(id="bb", name="BB-new", host="2.2.2.2")
    add_or_update_cluster(s, new, secret=None, old_cluster_id="aa")
    assert not any(c.id == "aa" for c in s.clusters)
    assert any(c.id == "bb" and c.name == "BB-new" for c in s.clusters)
    assert get_cluster_secret("bb") == "secret-aa"

    _mock_keyring(monkeypatch)
    s2 = AppSettings(clusters=[ClusterConfig(id="xx", name="XX", host="1.1.1.1")])
    set_cluster_secret("oldx", "keep")
    add_or_update_cluster(s2, ClusterConfig(id="yy", name="YY", host="1.1.1.1"), secret=None, old_cluster_id="oldx")
    assert get_cluster_secret("yy") == "keep"

    s3 = AppSettings(clusters=[ClusterConfig(id="keep", name="keep", host="1.1.1.1")])
    add_or_update_cluster(s3, ClusterConfig(id="keep", name="keep2", host="1.1.1.1"), secret=None)
    assert s3.clusters[0].name == "keep2"

    s4 = AppSettings()
    add_or_update_cluster(s4, ClusterConfig(id="newid", name="New", host="1.1.1.1"), secret="")
    assert any(c.id == "newid" for c in s4.clusters)
    assert get_cluster_secret("newid") is None


def test_manager_get_all_orphan_and_remove(monkeypatch, tmp_path):
    cfg = _cfg(tmp_path, monkeypatch)
    store = _mock_keyring(monkeypatch)
    s = AppSettings(clusters=[ClusterConfig(id="keep", name="keep", host="1.1.1.1")])
    save_settings(s)
    set_cluster_secret("orph", "orph-secret")
    ids = get_all_cluster_ids(s)
    assert "keep" in ids
    assert "orph" in ids
    orphans = find_orphan_cluster_ids(s)
    assert "orph" in orphans
    audited = audit_keyring_orphans(s)
    assert "orph" in audited
    s.clusters.append(ClusterConfig(id="orph", name="orph", host="2.2.2.2"))
    assert find_orphan_cluster_ids(s) == []
    remove_cluster(s, "orph")
    assert not any(c.id == "orph" for c in s.clusters)
    assert get_cluster_secret("orph") is None

    monkeypatch.setattr("proxmox_widget.config.manager.keyring.get_keyring", lambda: MagicMock(_mock_store={"proxmox-widget/extra": "x"}))
    ids2 = get_all_cluster_ids(s)
    assert "extra" in ids2 or "keep" in ids2


def test_format_bar():
    assert bar(0.0, 10) == "░" * 10
    assert bar(1.0, 10) == "█" * 10
    assert bar(0.5, 10) == "█" * 5 + "░" * 5
    assert bar(0.0, 0) == ""
    assert bar(1.5, 10) == "█" * 10
    assert bar(-0.5, 10) == "░" * 10
    assert bar(0.25, 4) == "█" * 1 + "░" * 3
    assert bar("bad", 5) == "░" * 5
    assert bar(0.5, -1) == ""
    assert len(bar(0.33, 10)) == 10


def test_settings_validation_helpers(qapp, monkeypatch):
    monkeypatch.setattr("proxmox_widget.ui.settings_dialog.get_cluster_secret", lambda _id: "secret")
    dlg = SettingsDialog(AppSettings(clusters=[ClusterConfig(id="ab", name="AB", host="10.0.0.1", token_id="root@pam!t")]))
    dlg.show()
    qapp.processEvents()
    assert dlg._validate_id_text("ab") is None
    assert "required" in dlg._validate_id_text("").lower()
    assert dlg._validate_id_text("A") is not None
    assert dlg._validate_id_text("a") is not None
    assert dlg._validate_id_text("ab-") is None
    assert dlg._validate_host_text("") is not None
    assert dlg._validate_host_text("10.0.0.1") is None
    assert dlg._validate_host_text("evil.com/foo") is not None
    h, p = _parse_host_port("https://1.2.3.4:8007/")
    assert h == "1.2.3.4" and p == 8007
    h2, p2 = _parse_host_port("example.com")
    assert h2 == "example.com" and p2 == 8006
    _h3, p3 = _parse_host_port("example.com:notaport")
    assert p3 == 8006
    dlg.close()


def test_settings_dialog_token_bang_validation(qapp, monkeypatch):
    monkeypatch.setattr("proxmox_widget.ui.settings_dialog.get_cluster_secret", lambda _id: "secret")
    monkeypatch.setattr("proxmox_widget.ui.settings_dialog.QMessageBox.warning", lambda *a, **k: None)
    s = AppSettings(clusters=[ClusterConfig(id="ab", name="AB", host="10.0.0.1", token_id="root@pam!t")])
    dlg = SettingsDialog(s)
    dlg.show()
    qapp.processEvents()
    dlg.ed_id.setText("ab")
    dlg.ed_host.setText("10.0.0.1")
    dlg.ed_secret.setText("s3cr3t")
    dlg.combo_auth.setCurrentIndex(0)
    dlg.ed_token_id.setText("badtoken")
    qapp.processEvents()
    assert dlg._form_cluster() is None
    dlg.ed_token_id.setText("root@pam!good")
    assert dlg._form_cluster() is not None
    dlg.close()


@pytest.mark.asyncio
async def test_actions_wait_until(monkeypatch):
    from proxmox_widget.config.models import ClusterConfig

    cfg = ClusterConfig(id="pve", name="PVE", host="1.2.3.4", token_id="root@pam!t", auth_mode=AuthMode.TOKEN)

    called = {}

    class FakeClient:
        def __init__(self, cluster):
            self.cluster = cluster

        async def wait_for_guest(self, node, vmid, want, is_lxc=False, timeout=45):
            called["args"] = (node, vmid, want, is_lxc, timeout)
            return True

        async def vm_action(self, node, vmid, action, is_lxc=False):
            called["action"] = (node, vmid, action, is_lxc)
            return "UPID:123"

    monkeypatch.setattr(actions, "ProxmoxClient", FakeClient)
    res = await actions.wait_until(cfg, "pve", 100, "running", is_lxc=False, timeout=10)
    assert res is True
    assert called["args"][0] == "pve"
    assert called["args"][2] == "running"

    upid = await actions.do_action(cfg, "pve", 100, "start", is_lxc=False)
    assert upid == "UPID:123"


def test_actions_wait_until_sync(monkeypatch):
    from proxmox_widget.config.models import ClusterConfig

    cfg = ClusterConfig(id="pve", name="PVE", host="1.2.3.4", token_id="root@pam!t", auth_mode=AuthMode.TOKEN)

    class FakeClient:
        def __init__(self, cluster):
            pass

        async def wait_for_guest(self, node, vmid, want, is_lxc=False, timeout=45):
            return True

        async def vm_action(self, node, vmid, action, is_lxc=False):
            return "UPID:123"

    monkeypatch.setattr(actions, "ProxmoxClient", FakeClient)
    assert actions.wait_until_sync(cfg, "pve", 101, "stopped", is_lxc=True, timeout=5) is True
    assert actions.do_action_sync(cfg, "pve", 100, "stop", is_lxc=True) == "UPID:123"


@pytest.mark.asyncio
async def test_actions_wait_until_timeout(monkeypatch):
    from proxmox_widget.config.models import ClusterConfig

    cfg = ClusterConfig(id="pve", name="PVE", host="1.2.3.4")

    class FakeClient:
        def __init__(self, cluster):
            pass

        async def wait_for_guest(self, *a, **k):
            return False

        async def vm_action(self, *a, **k):
            return "UPID:999"

    monkeypatch.setattr(actions, "ProxmoxClient", FakeClient)
    res = await actions.wait_until(cfg, "pve", 100, "running")
    assert res is False


def test_dashboard_offline_banner(qapp, monkeypatch):
    monkeypatch.setattr("proxmox_widget.ui.settings_dialog.get_cluster_secret", lambda _id: "secret")
    d = Dashboard()
    d.show()
    qapp.processEvents()

    healthy = ClusterHealth(cluster_id="pve", cluster_name="PVE", online=True, nodes=[], vms=[], containers=[], storages=[])
    d.update_health([healthy])
    qapp.processEvents()
    assert d._banner.isVisible() is False or "Offline" not in d._banner_label.text()

    offline = ClusterHealth(cluster_id="pve", cluster_name="PVE", online=False, error="timeout", nodes=[], vms=[], containers=[], storages=[])
    d.update_health([offline])
    qapp.processEvents()
    assert d._banner.isVisible() is True
    assert "Offline" in d._banner_label.text()
    assert "timeout" in d._banner_label.text() or "PVE" in d._banner_label.text()
    assert d.lbl_sub.text() != ""
    d.close()

    d2 = Dashboard()
    d2.show()
    qapp.processEvents()
    d2.update_health([])
    qapp.processEvents()
    assert "no clusters" in d2.lbl_sub.text().lower()
    d2.close()


def test_dashboard_offline_banner_multiple(qapp):
    d = Dashboard()
    d.show()
    h1 = ClusterHealth(cluster_id="pve1", cluster_name="PVE1", online=False, error="down1")
    h2 = ClusterHealth(cluster_id="pve2", cluster_name="PVE2", online=False, error="down2")
    d.update_health([h1, h2])
    assert d._banner.isVisible() is True
    assert "PVE1" in d._banner_label.text()
    assert "PVE2" in d._banner_label.text()
    d.close()
