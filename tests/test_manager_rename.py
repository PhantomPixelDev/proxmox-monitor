from __future__ import annotations

import os

from proxmox_widget.config.manager import (
    add_or_update_cluster,
    audit_keyring_orphans,
    find_orphan_cluster_ids,
    get_all_cluster_ids,
    get_cluster_secret,
)
from proxmox_widget.config.models import AppSettings, ClusterConfig


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


def test_rename_migrates_secret(monkeypatch, tmp_path):
    cfg = _cfg(tmp_path, monkeypatch)
    store = _mock_keyring(monkeypatch)
    s = AppSettings()
    c_old = ClusterConfig(id="pve-old", name="old", host="10.0.0.1")
    add_or_update_cluster(s, c_old, secret="s3cr3t")
    assert get_cluster_secret("pve-old") == "s3cr3t"
    c_new = ClusterConfig(id="pve-new", name="new", host="10.0.0.1")
    add_or_update_cluster(s, c_new, secret=None, old_cluster_id="pve-old")
    assert get_cluster_secret("pve-new") == "s3cr3t"
    assert get_cluster_secret("pve-old") is None
    assert any(c.id == "pve-new" for c in s.clusters)
    assert not any(c.id == "pve-old" for c in s.clusters)
    assert cfg.exists()


def test_rename_with_new_secret_overwrites(monkeypatch, tmp_path):
    _cfg(tmp_path, monkeypatch)
    _mock_keyring(monkeypatch)
    s = AppSettings()
    add_or_update_cluster(s, ClusterConfig(id="pve-old", name="old", host="10.0.0.1"), secret="oldsecret")
    add_or_update_cluster(
        s, ClusterConfig(id="pve-new", name="new", host="10.0.0.2"), secret="newsecret", old_cluster_id="pve-old"
    )
    assert get_cluster_secret("pve-new") == "newsecret"
    assert get_cluster_secret("pve-old") is None


def test_rename_deletes_both_keys(monkeypatch, tmp_path):
    _cfg(tmp_path, monkeypatch)
    store = _mock_keyring(monkeypatch)
    s = AppSettings()
    add_or_update_cluster(s, ClusterConfig(id="pve-old", name="old", host="10.0.0.1"), secret="tok")
    store[("proxmox-widget/pve-old", "token")] = "legacy-token"
    add_or_update_cluster(s, ClusterConfig(id="pve-new", name="new", host="10.0.0.1"), secret=None, old_cluster_id="pve-old")
    assert ("proxmox-widget/pve-old", "secret") not in store
    assert ("proxmox-widget/pve-old", "token") not in store


def test_rename_failure_does_not_crash(monkeypatch, tmp_path, caplog):
    cfg = _cfg(tmp_path, monkeypatch)
    store = _mock_keyring(monkeypatch)
    s = AppSettings()
    add_or_update_cluster(s, ClusterConfig(id="pve-old", name="old", host="10.0.0.1"), secret="keepme")

    def failing_set(svc, user, pw):
        raise RuntimeError("keyring down")

    monkeypatch.setattr("proxmox_widget.config.manager.keyring.set_password", failing_set)
    c_new = ClusterConfig(id="pve-new", name="new", host="10.0.0.1")
    add_or_update_cluster(s, c_new, secret=None, old_cluster_id="pve-old")
    assert cfg.exists()
    assert any(c.id == "pve-new" for c in s.clusters)


def test_get_all_cluster_ids_lists_services(monkeypatch, tmp_path):
    _cfg(tmp_path, monkeypatch)
    _mock_keyring(monkeypatch)
    s = AppSettings(clusters=[ClusterConfig(id="ab", name="AB", host="1.1.1.1")])
    ids = get_all_cluster_ids(s)
    assert "ab" in ids
    add_or_update_cluster(s, ClusterConfig(id="cd", name="CD", host="2.2.2.2"), secret="x")
    ids2 = get_all_cluster_ids(s)
    assert "cd" in ids2
    assert "ab" in ids2


def test_find_orphan_and_audit(monkeypatch, tmp_path):
    _cfg(tmp_path, monkeypatch)
    _mock_keyring(monkeypatch)
    s = AppSettings(clusters=[ClusterConfig(id="keep", name="keep", host="1.1.1.1")])
    add_or_update_cluster(s, ClusterConfig(id="orph", name="orph", host="2.2.2.2"), secret="orph-secret")
    s.clusters = [c for c in s.clusters if c.id != "orph"]
    orphans = find_orphan_cluster_ids(s)
    assert "orph" in orphans
    audited = audit_keyring_orphans(s)
    assert "orph" in audited


def test_chmod_0600_on_save(monkeypatch, tmp_path):
    cfg = _cfg(tmp_path, monkeypatch)
    _mock_keyring(monkeypatch)
    chmod_calls: list[tuple[str, int]] = []
    real_chmod = os.chmod

    def fake_chmod(path, mode):
        chmod_calls.append((str(path), mode))
        try:
            return real_chmod(path, mode)
        except Exception:
            return None

    monkeypatch.setattr("proxmox_widget.config.manager.os.chmod", fake_chmod)
    add_or_update_cluster(AppSettings(), ClusterConfig(id="ab", name="AB", host="1.1.1.1"), secret="x")
    assert chmod_calls
    assert chmod_calls[0][1] == 0o600
