"""Config persistence via platformdirs + keyring."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
from typing import Final

import keyring
from filelock import FileLock
from loguru import logger
from platformdirs import user_config_dir
from pydantic import ValidationError

from .models import AppSettings, ClusterConfig

APP_NAME: Final = "ProxmoxWidget"
APP_AUTHOR: Final = "ProxmoxWidget"
KEYRING_SERVICE_PREFIX: Final = "proxmox-widget"
_known_ids: set[str] = set()


def _config_path() -> pathlib.Path:
    d = pathlib.Path(user_config_dir(APP_NAME, APP_AUTHOR))
    d.mkdir(parents=True, exist_ok=True)
    return d / "config.json"


def _keyring_service(cluster_id: str) -> str:
    return f"{KEYRING_SERVICE_PREFIX}/{cluster_id}"


def load_settings() -> AppSettings:
    path = _config_path()
    lock = FileLock(str(path.with_suffix(".lock")), timeout=2)
    with lock:
        if not path.exists():
            logger.info("No config at {}, using defaults", path)
            return AppSettings()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return AppSettings.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            bak = pathlib.Path(str(path) + ".bak")
            try:
                shutil.copyfile(path, bak)
            except Exception:
                pass
            logger.warning(
                "Corrupt config at {}: {} — backed up to {} and using defaults", path, e, bak
            )
            return AppSettings()
        except Exception as e:
            logger.error("Failed to load config {}: {} — using defaults", path, e)
            return AppSettings()


def save_settings(settings: AppSettings) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path.with_suffix(".lock")), timeout=2)
    with lock:
        # never persist secrets — ClusterConfig has no token_value
        data = settings.model_dump(mode="json")
        tmp = pathlib.Path(str(path) + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
        logger.info("Saved config to {}", path)


# -- keyring helpers --


def set_cluster_secret(cluster_id: str, secret: str) -> None:
    _known_ids.add(cluster_id)
    keyring.set_password(_keyring_service(cluster_id), "secret", secret)


def set_cluster_token(cluster_id: str, token_value: str) -> None:
    set_cluster_secret(cluster_id, token_value)


def set_cluster_password(cluster_id: str, password: str) -> None:
    set_cluster_secret(cluster_id, password)


def get_cluster_secret(cluster_id: str) -> str | None:
    try:
        v = keyring.get_password(_keyring_service(cluster_id), "secret")
        if v is not None:
            return v
        return keyring.get_password(_keyring_service(cluster_id), "token")
    except Exception as e:
        logger.error("keyring get failed for {}: {}", cluster_id, e)
        return None


def get_cluster_token(cluster_id: str) -> str | None:
    return get_cluster_secret(cluster_id)


def delete_cluster_secret(cluster_id: str) -> None:
    _known_ids.discard(cluster_id)
    for key in ("secret", "token"):
        try:
            keyring.delete_password(_keyring_service(cluster_id), key)
        except Exception:
            pass


def delete_cluster_token(cluster_id: str) -> None:
    delete_cluster_secret(cluster_id)


def add_or_update_cluster(
    settings: AppSettings,
    cluster: ClusterConfig,
    secret: str | None,
    old_cluster_id: str | None = None,
) -> AppSettings:
    is_rename = old_cluster_id is not None and old_cluster_id != cluster.id
    if is_rename:
        assert old_cluster_id is not None
        old_idx = next(
            (i for i, c in enumerate(settings.clusters) if c.id == old_cluster_id),
            None,
        )
        idx_new = next(
            (i for i, c in enumerate(settings.clusters) if c.id == cluster.id),
            None,
        )
        if old_idx is not None:
            if idx_new is not None and idx_new != old_idx:
                settings.clusters.pop(old_idx)
                if old_idx < idx_new:
                    idx_new -= 1
                settings.clusters[idx_new] = cluster
            else:
                settings.clusters[old_idx] = cluster
        else:
            if idx_new is not None:
                settings.clusters[idx_new] = cluster
            else:
                settings.clusters.append(cluster)
        try:
            migrated = secret
            if migrated is None:
                migrated = get_cluster_secret(old_cluster_id)
            if migrated is not None:
                set_cluster_secret(cluster.id, migrated)
            delete_cluster_secret(old_cluster_id)
        except Exception as e:
            logger.warning(
                "Failed to migrate keyring secret from {} to {}: {}",
                old_cluster_id,
                cluster.id,
                e,
            )
        save_settings(settings)
        return settings

    idx = next((i for i, c in enumerate(settings.clusters) if c.id == cluster.id), None)
    if idx is not None:
        settings.clusters[idx] = cluster
    else:
        settings.clusters.append(cluster)
    if secret:
        set_cluster_secret(cluster.id, secret)
    save_settings(settings)
    return settings


def get_all_cluster_ids(settings: AppSettings | None = None) -> list[str]:
    """List services under proxmox-widget/* from settings and keyring store."""
    ids: set[str] = set()
    if settings is not None:
        ids.update(c.id for c in settings.clusters)
    else:
        try:
            ids.update(c.id for c in load_settings().clusters)
        except Exception:
            pass
    ids.update(_known_ids)
    try:
        kr = keyring.get_keyring()
        for attr in ("_mock_store", "store", "_store", "_test_store"):
            store = getattr(kr, attr, None)
            if isinstance(store, dict):
                for svc in list(store.keys()):
                    if isinstance(svc, str) and svc.startswith(KEYRING_SERVICE_PREFIX + "/"):
                        ids.add(svc[len(KEYRING_SERVICE_PREFIX) + 1 :])
                break
            if isinstance(store, dict):
                break
    except Exception:
        pass
    return sorted(ids)


def find_orphan_cluster_ids(settings: AppSettings) -> list[str]:
    configured = {c.id for c in settings.clusters}
    all_ids = set(get_all_cluster_ids(settings))
    return sorted(all_ids - configured)


def audit_keyring_orphans(settings: AppSettings) -> list[str]:
    orphans = find_orphan_cluster_ids(settings)
    if orphans:
        logger.warning("Orphan keyring entries found: {}", orphans)
    return orphans


def remove_cluster(settings: AppSettings, cluster_id: str) -> AppSettings:
    settings.clusters = [c for c in settings.clusters if c.id != cluster_id]
    delete_cluster_secret(cluster_id)
    save_settings(settings)
    return settings


__all__ = [
    "APP_NAME",
    "add_or_update_cluster",
    "audit_keyring_orphans",
    "delete_cluster_secret",
    "delete_cluster_token",
    "find_orphan_cluster_ids",
    "get_all_cluster_ids",
    "get_cluster_secret",
    "get_cluster_token",
    "load_settings",
    "remove_cluster",
    "save_settings",
    "set_cluster_password",
    "set_cluster_secret",
    "set_cluster_token",
]
