from proxmox_widget.config.models import AppSettings, AuthMode, ClusterConfig


def test_cluster_url():
    c = ClusterConfig(
        id="pve",
        name="PVE",
        host="192.168.10.2",
        port=8006,
        token_id="root@pam!t",
        auth_mode=AuthMode.TOKEN,
    )
    assert c.base_url == "https://192.168.10.2:8006"
    assert c.api_url.endswith("/api2/json")


def test_password_mode():
    c = ClusterConfig(
        id="pve", name="PVE", host="192.168.10.2", username="root@pam", auth_mode=AuthMode.PASSWORD
    )
    assert c.auth_mode == AuthMode.PASSWORD


def test_settings_defaults():
    s = AppSettings()
    assert s.refresh_interval_seconds == 30


def test_tls_verification_is_on_by_default():
    """A token must not cross an unverified connection unless asked."""
    from proxmox_widget.config.models import ClusterConfig

    assert (
        ClusterConfig(id="ab", name="ab", host="h", auth_mode=AuthMode.PASSWORD).verify_ssl is True
    )


def test_settings_validation_host_and_id():
    import pytest
    from pydantic import ValidationError

    from proxmox_widget.config.models import ClusterConfig

    with pytest.raises(ValidationError):
        ClusterConfig(id="Bad", name="x", host="10.0.0.1")
    with pytest.raises(ValidationError):
        ClusterConfig(id="a", name="x", host="10.0.0.1")
    with pytest.raises(ValidationError):
        ClusterConfig(id="ab", name="x", host="evil.com/foo")
    c = ClusterConfig(id="ab", name="x", host=" https://10.0.0.1:8006/ ")
    assert c.host == "10.0.0.1"
    assert c.port == 8006


def test_token_bang_validation():
    import pytest
    from pydantic import ValidationError

    from proxmox_widget.config.models import ClusterConfig

    with pytest.raises(ValidationError):
        ClusterConfig(id="ab", name="x", host="h", auth_mode=AuthMode.TOKEN, token_id="badtoken")
    c = ClusterConfig(id="ab", name="x", host="h", auth_mode=AuthMode.TOKEN, token_id="root@pam!t")
    assert "!" in c.token_id
