# tests/test_pytest_plugin_extended.py
"""Extended tests for pytest_plugin.py: fixtures and config loading.

The vcr-proxy plugin is disabled during tests (see pytest.ini) so that
coverage can track all vcr_proxy imports. These tests exercise the plugin's
functions directly rather than through the fixture mechanism.
"""

from pathlib import Path

import httpx
from fastapi import FastAPI

from vcr_proxy.models import ProxyMode
from vcr_proxy.pytest_plugin import _load_pyproject_config


def test_load_pyproject_config_no_vcr_section(tmp_path: Path, monkeypatch):
    """pyproject.toml exists but has no [tool.vcr-proxy] section."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname = 'myapp'\n")
    monkeypatch.chdir(tmp_path)
    config = _load_pyproject_config()
    assert config == {}


def test_load_pyproject_config_with_targets(tmp_path: Path, monkeypatch):
    """pyproject.toml has [tool.vcr-proxy.targets]."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[tool.vcr-proxy]\n"
        'cassettes_dir = "cass"\n'
        "\n"
        "[tool.vcr-proxy.targets]\n"
        '"/api" = "http://api.example.com"\n'
        '"/auth" = "http://auth.example.com"\n'
    )
    monkeypatch.chdir(tmp_path)
    config = _load_pyproject_config()
    assert config["cassettes_dir"] == "cass"
    assert "/api" in config["targets"]
    assert "/auth" in config["targets"]


# --- Direct tests of the plugin fixture functions ---
# These test the actual functions in pytest_plugin.py to ensure coverage.


def test_vcr_mode_replay_default(monkeypatch):
    """vcr_mode returns REPLAY when VCR_RECORD is not set."""
    monkeypatch.delenv("VCR_RECORD", raising=False)
    from vcr_proxy.pytest_plugin import vcr_mode

    result = vcr_mode.__wrapped__()
    assert result == ProxyMode.REPLAY


def test_vcr_mode_spy_when_record(monkeypatch):
    """vcr_mode returns SPY when VCR_RECORD=1."""
    monkeypatch.setenv("VCR_RECORD", "1")
    from vcr_proxy.pytest_plugin import vcr_mode

    result = vcr_mode.__wrapped__()
    assert result == ProxyMode.SPY


def test_vcr_proxy_app_function(tmp_path: Path, monkeypatch):
    """vcr_proxy_app creates a FastAPI app from pyproject config."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.vcr-proxy]\ncassettes_dir = "cassettes"\n\n[tool.vcr-proxy.targets]\n"/api" = "http://example.com"\n'
    )
    monkeypatch.chdir(tmp_path)

    from vcr_proxy.pytest_plugin import vcr_proxy_app

    app = vcr_proxy_app.__wrapped__(vcr_mode=ProxyMode.REPLAY)
    assert isinstance(app, FastAPI)


def test_vcr_proxy_transport_function():
    """vcr_proxy_transport creates an ASGITransport from an app."""
    from vcr_proxy.app import create_app
    from vcr_proxy.pytest_plugin import vcr_proxy_transport

    app = create_app()
    transport = vcr_proxy_transport.__wrapped__(vcr_proxy_app=app)
    assert isinstance(transport, httpx.ASGITransport)


# --- Tests using the fixtures from tests/conftest.py ---


def test_vcr_mode_fixture_replay(vcr_mode):
    """Default vcr_mode is REPLAY (when VCR_RECORD is not set)."""
    assert vcr_mode == ProxyMode.REPLAY


def test_vcr_proxy_app_fixture_creates_app(vcr_proxy_app):
    """vcr_proxy_app fixture creates a FastAPI app."""
    assert isinstance(vcr_proxy_app, FastAPI)
    assert hasattr(vcr_proxy_app.state, "handler")


def test_vcr_proxy_transport_creates_transport(vcr_proxy_transport):
    """vcr_proxy_transport fixture creates an ASGITransport."""
    assert isinstance(vcr_proxy_transport, httpx.ASGITransport)
