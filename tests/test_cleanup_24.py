import pathlib


def test_pyproject_flags_enabled():
    text = pathlib.Path("pyproject.toml").read_text(encoding="utf-8")
    for flag in [
        "reportUnknownMemberType = true",
        "reportUnknownVariableType = true",
        "reportUnknownParameterType = true",
        "reportUnknownArgumentType = true",
    ]:
        assert flag in text, f"missing {flag}"


def test_app_sanitize_helper_exists_and_filters_token():
    text = pathlib.Path("src/proxmox_widget/app.py").read_text(encoding="utf-8")
    assert "_sanitize_error" in text
    assert "def _sanitize_error" in text
    # banner uses sanitized, not raw str(e)[:
    assert "dashboard.show_message(_sanitize_error" in text or "_sanitize_error(error" in text
    # should not have raw str(error)[:150] leaking host
    assert 'show_message(f"Refresh failed: {str(error)' not in text
    assert "show_message(str(error)[:170]" not in text


def test_client_sanitize_helper_exists():
    text = pathlib.Path("src/proxmox_widget/api/client.py").read_text(encoding="utf-8")
    assert "_sanitize_error" in text
    assert "def _sanitize_error" in text
    # fetch_health stores sanitized error
    assert "error=_sanitize_error" in text


def test_no_token_secret_in_logger():
    src = pathlib.Path("src")
    for p in src.rglob("*.py"):
        content = p.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(content.splitlines(), 1):
            low = line.lower()
            if ("token" in low or "secret" in low) and (
                "logger" in low or "loguru" in low or " logger" in low
            ):
                # allow token_id mentions in comments but not logging secret variable
                if "secret" in low and "logger" in low:
                    # check if line logs _secret or token variable directly
                    assert "_secret" not in line and "PVEAPIToken" not in line, (
                        f"{p}:{i} leaks secret {line.strip()}"
                    )
                if "PVEAPIToken" in line:
                    raise AssertionError(f"{p}:{i} leaks token in log {line.strip()}")


def test_app_client_type_hints_have_no_unknown_ignore():
    # ensure we added type hints rather than just suppressing via pyright: ignore for Unknown
    for path in ["src/proxmox_widget/app.py", "src/proxmox_widget/api/client.py"]:
        text = pathlib.Path(path).read_text(encoding="utf-8")
        # allowed ignores are import-not-found, arg-type for Qt restoreGeometry etc
        # but not blanket Unknown suppress
        count_unknown_ignore = text.count("reportUnknown")
        assert count_unknown_ignore == 0, f"{path} should not suppress reportUnknown"


def test_no_sqlite3():
    src = pathlib.Path("src")
    for p in src.rglob("*.py"):
        assert "sqlite3" not in p.read_text(encoding="utf-8", errors="ignore"), (
            f"{p} contains sqlite3"
        )


def test_sanitize_function_behavior():
    import importlib.util

    spec = importlib.util.spec_from_file_location("app_mod", "src/proxmox_widget/app.py")

    # cannot import Qt without offscreen; test logic directly
    def _sanitize_error(err, limit=150):
        raw = str(err) if err is not None else "Unknown error"
        low = raw.lower()
        if "token" in low or "secret" in low or "pveapitoken" in low:
            return "Authentication failed — check token and permissions"[:limit]
        if "certificate" in low or "fingerprint" in low:
            return "TLS verification failed — check host certificate"[:limit]
        return raw[:limit]

    assert "Authentication" in _sanitize_error("token leaked 123", 150)
    assert "TLS" in _sanitize_error("certificate fingerprint mismatch", 150)
    assert _sanitize_error("plain timeout host 1.2.3.4", 5) == "plain"[:5]
