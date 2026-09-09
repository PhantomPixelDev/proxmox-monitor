"""Config persistence via platformdirs + keyring."""

from __future__ import annotations

import json
import pathlib
from typing import Final

import keyring
from loguru import logger
from platformdirs import user_config_dir

from .models import AppSettings, ClusterConfig

APP_NAME: Final = "ProxmoxWidget"
APP_AUTHOR: Final = "ProxmoxWidget"
KEYRING_SERVICE_PREFIX: Final = "proxmox-widget"


def _config_path() -> pathlib.Path:
    d = pathlib.Path(user_config_dir(APP_NAME, APP_AUTHOR))
    d.mkdir(parents=True, exist_ok=True)
    return d / "config.json"


def _keyring_service(cluster_id: str) -> str:
    return f"{KEYRING_SERVICE_PREFIX}/{cluster_id}"


def load_settings() -> AppSettings:
    path = _config_path()
    if not path.exists():
        logger.info("No config at {}, using defaults", path)
        return AppSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return AppSettings.model_validate(data)
    except Exception as e:
        logger.error("Failed to load config {}: {} — using defaults", path, e)
        return AppSettings()


def save_settings(settings: AppSettings) -> None:
    path = _config_path()
    # never persist secrets — ClusterConfig has no token_value
    data = settings.model_dump(mode="json")
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info("Saved config to {}", path)


# -- keyring helpers --


def set_cluster_secret(cluster_id: str, secret: str) -> None:
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
    for key in ("secret", "token"):
        try:
            keyring.delete_password(_keyring_service(cluster_id), key)
        except Exception:
            pass


def delete_cluster_token(cluster_id: str) -> None:
    delete_cluster_secret(cluster_id)


def add_or_update_cluster(
    settings: AppSettings, cluster: ClusterConfig, secret: str | None
) -> AppSettings:
    idx = next((i for i, c in enumerate(settings.clusters) if c.id == cluster.id), None)
    if idx is not None:
        settings.clusters[idx] = cluster
    else:
        settings.clusters.append(cluster)
    if secret:
        set_cluster_secret(cluster.id, secret)
    save_settings(settings)
    return settings


def remove_cluster(settings: AppSettings, cluster_id: str) -> AppSettings:
    settings.clusters = [c for c in settings.clusters if c.id != cluster_id]
    delete_cluster_secret(cluster_id)
    save_settings(settings)
    return settings


__all__ = [
    "APP_NAME",
    "load_settings",
    "save_settings",
    "set_cluster_secret",
    "set_cluster_token",
    "set_cluster_password",
    "get_cluster_secret",
    "get_cluster_token",
    "delete_cluster_secret",
    "delete_cluster_token",
    "add_or_update_cluster",
    "remove_cluster",
]
