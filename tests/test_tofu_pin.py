import hashlib
import json

import pytest

from proxmox_widget.api import client as client_mod
from proxmox_widget.api.client import ProxmoxClient
from proxmox_widget.config.models import AuthMode, ClusterConfig


def _fp(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


@pytest.fixture(autouse=True)
def _isolate_trust(tmp_path, monkeypatch):
    monkeypatch.setattr(client_mod, "user_config_dir", lambda *_a, **_k: str(tmp_path))
    import platformdirs

    monkeypatch.setattr(platformdirs, "user_config_dir", lambda *_a, **_k: str(tmp_path))
    yield
    # ensure clean
    p = tmp_path / "trust.json"
    if p.exists():
        p.unlink()


@pytest.mark.asyncio
async def test_first_connect_stores(tmp_path, monkeypatch):
    fp1 = _fp("cert1")
    monkeypatch.setattr(client_mod, "_fetch_fingerprint", lambda h, p: fp1)
    c = ClusterConfig(
        id="pve-tofu", name="PVE", host="127.0.0.1", port=8006, verify_ssl=False, auth_mode=AuthMode.TOKEN, token_id="root@pam!t"
    )
    cl = ProxmoxClient(c, secret="s")
    await cl._ensure_tofu()
    data = json.loads((tmp_path / "trust.json").read_text(encoding="utf-8"))
    assert data["pve-tofu"] == fp1


@pytest.mark.asyncio
async def test_second_same_passes(tmp_path, monkeypatch):
    fp1 = _fp("cert1")
    monkeypatch.setattr(client_mod, "_fetch_fingerprint", lambda h, p: fp1)
    c = ClusterConfig(
        id="pve-tofu2", name="PVE", host="127.0.0.1", verify_ssl=False, auth_mode=AuthMode.TOKEN, token_id="root@pam!t"
    )
    cl = ProxmoxClient(c, secret="s")
    await cl._ensure_tofu()
    await cl._ensure_tofu()
    data = json.loads((tmp_path / "trust.json").read_text(encoding="utf-8"))
    assert data["pve-tofu2"] == fp1


@pytest.mark.asyncio
async def test_changed_raises(tmp_path, monkeypatch):
    fp1 = _fp("cert1")
    fp2 = _fp("cert2")
    monkeypatch.setattr(client_mod, "_fetch_fingerprint", lambda h, p: fp1)
    c = ClusterConfig(
        id="pve-mismatch", name="PVE", host="127.0.0.1", verify_ssl=False, auth_mode=AuthMode.TOKEN, token_id="root@pam!t"
    )
    cl = ProxmoxClient(c, secret="s")
    await cl._ensure_tofu()
    monkeypatch.setattr(client_mod, "_fetch_fingerprint", lambda h, p: fp2)
    with pytest.raises(Exception, match="certificate fingerprint mismatch"):
        await cl._ensure_tofu()


@pytest.mark.asyncio
async def test_public_pki_bypasses_pin(tmp_path, monkeypatch):
    called = {}

    def _fail(h, p):
        called["hit"] = True
        return _fp("x")

    monkeypatch.setattr(client_mod, "_fetch_fingerprint", _fail)
    c = ClusterConfig(
        id="pve-public", name="PVE", host="127.0.0.1", verify_ssl=True, auth_mode=AuthMode.TOKEN, token_id="root@pam!t"
    )
    cl = ProxmoxClient(c, secret="s")
    await cl._ensure_tofu()
    assert "hit" not in called
    assert not (tmp_path / "trust.json").exists() or "pve-public" not in json.loads((tmp_path / "trust.json").read_text(encoding="utf-8")) if (tmp_path / "trust.json").exists() else True


@pytest.mark.asyncio
async def test_ca_bundle_pins_and_verify_wins(tmp_path, monkeypatch):
    ca = tmp_path / "ca.crt"
    ca.write_text("fake", encoding="utf-8")
    fp1 = _fp("ca-cert")
    monkeypatch.setattr(client_mod, "_fetch_fingerprint", lambda h, p: fp1)
    c = ClusterConfig(
        id="pve-ca", name="PVE", host="127.0.0.1", verify_ssl=True, ca_bundle=str(ca), auth_mode=AuthMode.TOKEN, token_id="root@pam!t"
    )
    cl = ProxmoxClient(c, secret="s")
    assert cl._verify() == str(ca)
    assert cl._needs_tofu() is True
    await cl._ensure_tofu()
    data = json.loads((tmp_path / "trust.json").read_text(encoding="utf-8"))
    assert data["pve-ca"] == fp1
    c2 = ClusterConfig(
        id="pve-verify-true", name="PVE", host="127.0.0.1", verify_ssl=True, auth_mode=AuthMode.TOKEN, token_id="root@pam!t"
    )
    cl2 = ProxmoxClient(c2, secret="s")
    assert cl2._verify() is True
    assert cl2._needs_tofu() is False
    c3 = ClusterConfig(
        id="pve-verify-false", name="PVE", host="127.0.0.1", verify_ssl=False, auth_mode=AuthMode.TOKEN, token_id="root@pam!t"
    )
    cl3 = ProxmoxClient(c3, secret="s")
    assert cl3._verify() is False
    assert cl3._needs_tofu() is True
