from proxmox_widget.config.models import ClusterConfig, AppSettings, AuthMode

def test_cluster_url():
    c = ClusterConfig(id="pve", name="PVE", host="192.168.10.2", port=8006, token_id="root@pam!t", auth_mode=AuthMode.TOKEN)
    assert c.base_url == "https://192.168.10.2:8006"
    assert c.api_url.endswith("/api2/json")

def test_password_mode():
    c = ClusterConfig(id="pve", name="PVE", host="192.168.10.2", username="root@pam", auth_mode=AuthMode.PASSWORD)
    assert c.auth_mode == AuthMode.PASSWORD

def test_settings_defaults():
    s = AppSettings()
    assert s.refresh_interval_seconds == 30
