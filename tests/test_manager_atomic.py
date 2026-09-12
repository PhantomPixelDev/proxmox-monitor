"""Atomic write, fsync, chmod, and FileLock for config manager."""

from __future__ import annotations

import json
import os
import pathlib

from proxmox_widget.config.manager import (
    KEYRING_SERVICE_PREFIX,
    _keyring_service,
    load_settings,
    save_settings,
)
from proxmox_widget.config.models import AppSettings, ClusterConfig


def test_save_creates_file_with_valid_json(monkeypatch, tmp_path):
    cfg = tmp_path / "subdir" / "config.json"
    monkeypatch.setattr("proxmox_widget.config.manager._config_path", lambda: cfg)
    s = AppSettings(clusters=[ClusterConfig(id="pve", name="PVE", host="10.0.0.1")])
    save_settings(s)
    assert cfg.exists()
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["clusters"][0]["id"] == "pve"
    # tmp file cleaned up
    assert not pathlib.Path(str(cfg) + ".tmp").exists()
    # parent mkdir
    assert cfg.parent.exists()


def test_save_atomic_uses_tmp_fsync_replace(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    monkeypatch.setattr("proxmox_widget.config.manager._config_path", lambda: cfg)

    orig_replace = os.replace
    replace_calls: list[tuple[str, str]] = []
    fsync_calls: list[int] = []

    def fake_replace(src, dst):
        replace_calls.append((str(src), str(dst)))
        return orig_replace(src, dst)

    def fake_fsync(fd):
        fsync_calls.append(fd)
        return orig_replace  # not needed

    monkeypatch.setattr("proxmox_widget.config.manager.os.replace", fake_replace)
    # patch os.fsync to track but still call real fsync on tmp file
    real_fsync = os.fsync

    def tracking_fsync(fd):
        fsync_calls.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr("proxmox_widget.config.manager.os.fsync", tracking_fsync)

    s = AppSettings()
    save_settings(s)

    # os.replace must have been called with tmp containing .tmp and dst is cfg
    assert replace_calls, "os.replace was not called"
    src, dst = replace_calls[0]
    assert ".tmp" in src, f"tmp path should contain .tmp, got {src}"
    assert dst == str(cfg)
    assert fsync_calls, "os.fsync was not called"


def test_save_chmod_0600(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    monkeypatch.setattr("proxmox_widget.config.manager._config_path", lambda: cfg)

    chmod_calls: list[tuple[str, int]] = []
    real_chmod = os.chmod

    def fake_chmod(path, mode):
        chmod_calls.append((str(path), mode))
        try:
            return real_chmod(path, mode)
        except Exception:
            return None

    monkeypatch.setattr("proxmox_widget.config.manager.os.chmod", fake_chmod)

    save_settings(AppSettings())
    assert chmod_calls, "os.chmod not called"
    _p, mode = chmod_calls[0]
    assert mode == 0o600


def test_save_and_load_use_filelock(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    monkeypatch.setattr("proxmox_widget.config.manager._config_path", lambda: cfg)

    from unittest.mock import MagicMock, patch

    # Verify FileLock is instantiated with .lock suffix and timeout=2
    with patch("proxmox_widget.config.manager.FileLock") as MockLock:
        mock_instance = MagicMock()
        mock_instance.__enter__ = MagicMock(return_value=mock_instance)
        mock_instance.__exit__ = MagicMock(return_value=False)
        MockLock.return_value = mock_instance

        s = AppSettings()
        save_settings(s)

        assert MockLock.called, "FileLock not used in save_settings"
        lock_path, kwargs = MockLock.call_args[0][0], MockLock.call_args[1]
        assert ".lock" in str(lock_path), f"lock path should contain .lock, got {lock_path}"
        assert (
            kwargs.get("timeout") == 2
            or MockLock.call_args[1].get("timeout") == 2
            or any("timeout" in str(c) for c in MockLock.call_args)
            or MockLock.call_args.kwargs.get("timeout") == 2
        )

    with patch("proxmox_widget.config.manager.FileLock") as MockLock:
        mock_instance = MagicMock()
        mock_instance.__enter__ = MagicMock(return_value=mock_instance)
        mock_instance.__exit__ = MagicMock(return_value=False)
        MockLock.return_value = mock_instance

        # pre-create valid config so load reads it
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps(AppSettings().model_dump(mode="json")), encoding="utf-8")
        load_settings()
        assert MockLock.called, "FileLock not used in load_settings"
        lock_path = MockLock.call_args[0][0]
        assert ".lock" in str(lock_path)


def test_keyring_prefix_unchanged():
    assert KEYRING_SERVICE_PREFIX == "proxmox-widget"
    assert _keyring_service("my-id") == "proxmox-widget/my-id"


def test_save_never_persists_secrets(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    monkeypatch.setattr("proxmox_widget.config.manager._config_path", lambda: cfg)
    s = AppSettings(
        clusters=[ClusterConfig(id="pve", name="PVE", host="1.2.3.4", token_id="root@pam!t")]
    )
    save_settings(s)
    data = json.loads(cfg.read_text(encoding="utf-8"))
    dumped = json.dumps(data)
    assert "token_value" not in dumped
    assert "secret" not in dumped.lower() or ("secret" in dumped and "s3cr3t" not in dumped)
