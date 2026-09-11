import pathlib
import tempfile

import pytest
from pydantic import ValidationError

from proxmox_widget.config.models import AppSettings, AuthMode, ClusterConfig


def _valid_kwargs(**overrides):
    base = dict(id="pve-home", name="PVE Home", host="192.168.1.10", token_id="root@pam!widget")
    base.update(overrides)
    return base


# ID regex

def test_id_valid():
    c = ClusterConfig(**_valid_kwargs(id="ab"))
    assert c.id == "ab"
    c2 = ClusterConfig(**_valid_kwargs(id="a1-b_c"))
    assert c2.id == "a1-b_c"


def test_id_bad_with_space_rejects():
    with pytest.raises(ValidationError, match="id"):
        ClusterConfig(**_valid_kwargs(id="bad id"))


def test_id_too_short_rejects():
    with pytest.raises(ValidationError):
        ClusterConfig(**_valid_kwargs(id="a"))


def test_id_uppercase_rejects():
    with pytest.raises(ValidationError):
        ClusterConfig(**_valid_kwargs(id="PVE-Home"))


def test_id_too_long_rejects():
    with pytest.raises(ValidationError):
        ClusterConfig(**_valid_kwargs(id="a" * 33))


def test_id_max_len_passes():
    c = ClusterConfig(**_valid_kwargs(id="a" * 32))
    assert len(c.id) == 32


# host

def test_host_ip_passes_and_lowered():
    c = ClusterConfig(**_valid_kwargs(host="192.168.1.10"))
    assert c.host == "192.168.1.10"


def test_host_hostname_lowered():
    c = ClusterConfig(**_valid_kwargs(host="PVE.example.COM"))
    assert c.host == "pve.example.com"


def test_host_with_scheme_stripped():
    c = ClusterConfig(**_valid_kwargs(host="https://pve.example.com"))
    assert c.host == "pve.example.com"


def test_host_ipv6_passes():
    c = ClusterConfig(**_valid_kwargs(host="fd00::1"))
    assert c.host == "fd00::1"


def test_host_slash_rejects():
    with pytest.raises(ValidationError, match="host"):
        ClusterConfig(**_valid_kwargs(host="evil.com/foo"))


def test_host_whitespace_rejects():
    with pytest.raises(ValidationError, match="host"):
        ClusterConfig(**_valid_kwargs(host="evil.com foo"))


def test_host_empty_rejects():
    with pytest.raises(ValidationError, match="host"):
        ClusterConfig(**_valid_kwargs(host=" https:// "))


def test_host_with_port_scheme_rejects_slash():
    # host raw containing slash after port should reject
    with pytest.raises(ValidationError, match="host"):
        ClusterConfig(**_valid_kwargs(host="https://evil.com:8006/foo"))


# token_id

def test_token_without_bang_rejects_in_token_mode():
    with pytest.raises(ValidationError, match="token_id"):
        ClusterConfig(**_valid_kwargs(token_id="root@pamwidget"))


def test_token_with_bang_passes():
    c = ClusterConfig(**_valid_kwargs(token_id="root@pam!monitor"))
    assert "!" in c.token_id


def test_token_without_bang_passes_in_password_mode():
    c = ClusterConfig(
        **_valid_kwargs(auth_mode=AuthMode.PASSWORD, token_id="whatever", username="root@pam")
    )
    assert c.auth_mode == AuthMode.PASSWORD


# ca_bundle

def test_ca_bundle_none_passes():
    c = ClusterConfig(**_valid_kwargs(ca_bundle=None))
    assert c.ca_bundle is None


def test_ca_bundle_missing_path_rejects():
    with pytest.raises(ValidationError, match="ca_bundle"):
        ClusterConfig(**_valid_kwargs(ca_bundle="/nonexistent/ca.crt"))


def test_ca_bundle_existing_path_passes():
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        p = tf.name
    try:
        c = ClusterConfig(**_valid_kwargs(ca_bundle=p))
        assert c.ca_bundle == p
        # also test pathlib
        assert pathlib.Path(c.ca_bundle).exists()
    finally:
        pathlib.Path(p).unlink(missing_ok=True)


# config_version migration

def test_config_version_default_is_2():
    s = AppSettings()
    assert s.config_version == 2


def test_config_version_migrates_old_json_without_field():
    data = {"clusters": [{"id": "ab", "name": "AB", "host": "10.0.0.1", "token_id": "root@pam!x"}]}
    s = AppSettings.model_validate(data)
    assert s.config_version == 2
    assert s.clusters[0].ca_bundle is None
    assert s.clusters[0].host == "10.0.0.1"


def test_config_version_preserved_if_present():
    data = {"config_version": 5, "clusters": []}
    s = AppSettings.model_validate(data)
    assert s.config_version == 5


def test_clusters_without_ca_bundle_migrated():
    data = {
        "clusters": [
            {"id": "ab", "name": "AB", "host": "10.0.0.1", "token_id": "root@pam!t"},
            {"id": "cd", "name": "CD", "host": "example.com", "token_id": "root@pam!t2"},
        ]
    }
    s = AppSettings.model_validate(data)
    assert all(c.ca_bundle is None for c in s.clusters)


def test_extra_fields_not_forbidden():
    # forward compat: extra fields should not raise
    data = {"clusters": [], "unknown_field": "keep", "config_version": 2}
    s = AppSettings.model_validate(data)
    assert s.config_version == 2
