import asyncio
import inspect
import time

import pytest

from proxmox_widget.api.client import ProxmoxClient
from proxmox_widget.api.exceptions import AuthError, ProxmoxError
from proxmox_widget.config.models import AuthMode, ClusterConfig, ProxmoxNode


class FakeResp:
    def __init__(self, status_code: int, data: object = None, text: str = "") -> None:
        self.status_code = status_code
        self._data = data if data is not None else {}
        self.text = text

    def json(self) -> object:
        if isinstance(self._data, dict) and "data" not in self._data:
            return {"data": self._data}
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            req = httpx.Request("GET", "https://example/api")
            resp = httpx.Response(self.status_code, request=req)
            raise httpx.HTTPStatusError(f"HTTP {self.status_code}", request=req, response=resp)


class FakeClient:
    def __init__(self, responses: list[FakeResp]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def get(self, _path: str) -> FakeResp:
        resp = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return resp

    async def post(self, _path: str, data=None) -> FakeResp:  # type: ignore[no-untyped-def]
        return await self.get(_path)

    async def aclose(self) -> None:
        pass


def _make_cluster(auth_mode: AuthMode = AuthMode.TOKEN) -> ClusterConfig:
    if auth_mode == AuthMode.TOKEN:
        return ClusterConfig(
            id="pve",
            name="PVE",
            host="1.2.3.4",
            token_id="root@pam!t",
            auth_mode=AuthMode.TOKEN,
        )
    return ClusterConfig(
        id="pve",
        name="PVE",
        host="1.2.3.4",
        auth_mode=AuthMode.PASSWORD,
        username="root@pam",
    )


def test_proxmox_error_typed() -> None:
    e = ProxmoxError(500, "boom")
    assert e.status == 500
    assert "boom" in str(e)
    e2 = ProxmoxError("plain message")
    assert e2.status is None
    assert e2.message == "plain message"
    e3 = AuthError(401, "unauthorized")
    assert e3.status == 401
    assert isinstance(e3, ProxmoxError)


def test_semaphore_exists() -> None:
    c = ProxmoxClient(_make_cluster(), secret="s")
    assert hasattr(c, "_semaphore")
    assert isinstance(c._semaphore, asyncio.Semaphore)
    assert c._semaphore._value == 5


@pytest.mark.asyncio
async def test_semaphore_limits_concurrency() -> None:
    c = ProxmoxClient(_make_cluster(), secret="s")
    nodes = [ProxmoxNode(node=f"pve-{i}", status="online") for i in range(20)]
    conc = 0
    peak = 0
    lock = asyncio.Lock()

    async def fake_fetch(node: str):  # type: ignore[no-untyped-def]
        nonlocal conc, peak
        async with lock:
            conc += 1
            peak = max(peak, conc)
        await asyncio.sleep(0.05)
        async with lock:
            conc -= 1
        return []

    async def fake_nodes():  # type: ignore[no-untyped-def]
        return nodes

    c.fetch_nodes = fake_nodes  # type: ignore[assignment]
    c.fetch_qemu = fake_fetch  # type: ignore[assignment]
    c.fetch_lxc = fake_fetch  # type: ignore[assignment]
    c.fetch_storage = fake_fetch  # type: ignore[assignment]

    start = time.perf_counter()
    health = await c.fetch_health()
    elapsed = time.perf_counter() - start

    assert len(health.nodes) == 20
    assert peak <= 5
    assert peak >= 2
    assert elapsed < 0.9
    assert elapsed >= 0.15


@pytest.mark.asyncio
async def test_401_retry_once_for_password(monkeypatch: pytest.MonkeyPatch) -> None:
    c = ProxmoxClient(_make_cluster(AuthMode.PASSWORD), secret="s")
    c._ticket = "old"
    fake = FakeClient([FakeResp(401), FakeResp(200, {"ok": 1})])
    monkeypatch.setattr(c, "_require_client", lambda: fake)

    called = {"n": 0}

    async def fake_login() -> None:
        called["n"] += 1
        c._ticket = "new"

    monkeypatch.setattr(c, "_login_ticket", fake_login)

    orig_mk = c._mk_client

    def fake_mk(extra_headers=None):  # type: ignore[no-untyped-def]
        return fake

    monkeypatch.setattr(c, "_mk_client", fake_mk)

    data = await c._get("/nodes")
    assert data == {"ok": 1}
    assert called["n"] == 1
    assert fake.calls == 2


@pytest.mark.asyncio
async def test_401_no_retry_for_token(monkeypatch: pytest.MonkeyPatch) -> None:
    c = ProxmoxClient(_make_cluster(AuthMode.TOKEN), secret="s")
    fake = FakeClient([FakeResp(401)])
    monkeypatch.setattr(c, "_require_client", lambda: fake)
    monkeypatch.setattr(c, "_mk_client", lambda extra_headers=None: fake)

    async def fail_login() -> None:
        raise AssertionError("should not login for TOKEN")

    monkeypatch.setattr(c, "_login_ticket", fail_login)

    with pytest.raises(AuthError) as exc:
        await c._get("/nodes")
    assert exc.value.status == 401


@pytest.mark.asyncio
async def test_post_401_retry_once(monkeypatch: pytest.MonkeyPatch) -> None:
    c = ProxmoxClient(_make_cluster(AuthMode.PASSWORD), secret="s")
    c._ticket = "old"
    fake = FakeClient([FakeResp(401), FakeResp(200, {"data": "upid"})])
    monkeypatch.setattr(c, "_require_client", lambda: fake)
    called = {"n": 0}

    async def fake_login() -> None:
        called["n"] += 1
        c._ticket = "new"

    monkeypatch.setattr(c, "_login_ticket", fake_login)
    monkeypatch.setattr(c, "_mk_client", lambda extra_headers=None: fake)

    data = await c._post("/nodes/pve/qemu/100/status/start")
    assert data == "upid"
    assert called["n"] == 1


def test_wait_for_guest_uses_monotonic() -> None:
    src = inspect.getsource(ProxmoxClient.wait_for_guest)
    assert "get_running_loop().time()" in src
    assert "get_event_loop().time()" not in src


def test_fetch_health_uses_semaphore() -> None:
    src = inspect.getsource(ProxmoxClient.fetch_health)
    assert "_semaphore" in src
    assert "async with" in src


def test_no_string_500_check() -> None:
    src = inspect.getsource(ProxmoxClient.fetch_health)
    assert '"500" in msg' not in src
    assert "'500' in msg" not in src
    assert "status" in src.lower()


def test_httpx_timeout_unchanged() -> None:
    src = inspect.getsource(ProxmoxClient._mk_client)
    assert "httpx.Timeout(10.0, connect=5.0)" in src
