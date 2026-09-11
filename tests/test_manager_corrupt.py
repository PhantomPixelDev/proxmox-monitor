"""Corrupt config handling: only backup on JSONDecodeError/ValidationError."""

from __future__ import annotations

import json
import pathlib

from proxmox_widget.config.manager import load_settings
from proxmox_widget.config.models import AppSettings


def test_load_missing_returns_defaults(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    monkeypatch.setattr("proxmox_widget.config.manager._config_path", lambda: cfg)
    s = load_settings()
    assert isinstance(s, AppSettings)
    assert s.clusters == []


def test_load_valid_json_returns_settings(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    monkeypatch.setattr("proxmox_widget.config.manager._config_path", lambda: cfg)
    cfg.parent.mkdir(parents=True, exist_ok=True)
    s0 = AppSettings(refresh_interval_seconds=60)
    cfg.write_text(json.dumps(s0.model_dump(mode="json")), encoding="utf-8")
    s = load_settings()
    assert s.refresh_interval_seconds == 60


def test_load_corrupt_json_creates_bak_and_warns(monkeypatch, tmp_path, caplog):
    cfg = tmp_path / "config.json"
    monkeypatch.setattr("proxmox_widget.config.manager._config_path", lambda: cfg)
    cfg.parent.mkdir(parents=True, exist_ok=True)
    corrupt = "{ not valid json ["
    cfg.write_text(corrupt, encoding="utf-8")

    s = load_settings()
    assert isinstance(s, AppSettings)
    bak = pathlib.Path(str(cfg) + ".bak")
    assert bak.exists(), "backup .bak should exist on JSONDecodeError"
    assert bak.read_text(encoding="utf-8") == corrupt
    # warning surfaced
    assert s.clusters == []


def test_load_validation_error_creates_bak(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    monkeypatch.setattr("proxmox_widget.config.manager._config_path", lambda: cfg)
    cfg.parent.mkdir(parents=True, exist_ok=True)
    # port out of range triggers ValidationError
    bad = json.dumps({"clusters": [{"id": "pve", "name": "PVE", "host": "1.2.3.4", "port": 99999}]})
    cfg.write_text(bad, encoding="utf-8")

    s = load_settings()
    assert isinstance(s, AppSettings)
    bak = pathlib.Path(str(cfg) + ".bak")
    assert bak.exists(), "backup .bak should exist on ValidationError"
    assert json.loads(bak.read_text(encoding="utf-8"))["clusters"][0]["port"] == 99999


def test_load_generic_exception_no_bak(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    monkeypatch.setattr("proxmox_widget.config.manager._config_path", lambda: cfg)
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps(AppSettings().model_dump(mode="json")), encoding="utf-8")

    # Simulate generic exception (e.g., OSError) on read_text
    def raise_os_error(*a, **kw):
        raise OSError("disk read failed")

    monkeypatch.setattr(pathlib.Path, "read_text", raise_os_error)

    s = load_settings()
    assert isinstance(s, AppSettings)
    bak = pathlib.Path(str(cfg) + ".bak")
    assert not bak.exists(), "backup should NOT be created on generic Exception"


def test_corrupt_backup_uses_copyfile(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    monkeypatch.setattr("proxmox_widget.config.manager._config_path", lambda: cfg)
    cfg.parent.mkdir(parents=True, exist_ok=True)
    corrupt = "not json"
    cfg.write_text(corrupt, encoding="utf-8")

    import shutil

    calls: list[tuple[str, str]] = []
    orig = shutil.copyfile

    def fake_copyfile(src, dst):
        calls.append((str(src), str(dst)))
        return orig(src, dst)

    monkeypatch.setattr("proxmox_widget.config.manager.shutil.copyfile", fake_copyfile)
    load_settings()
    assert calls, "shutil.copyfile should be called on corrupt config"
    src, dst = calls[0]
    assert src == str(cfg)
    assert dst == str(pathlib.Path(str(cfg) + ".bak"))


def test_load_corrupt_does_not_raise(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    monkeypatch.setattr("proxmox_widget.config.manager._config_path", lambda: cfg)
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("{{{{", encoding="utf-8")
    # should not raise
    s = load_settings()
    assert isinstance(s, AppSettings)
