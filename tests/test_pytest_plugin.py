# tests/test_pytest_plugin.py
import httpx
from fastapi import FastAPI

from vcr_proxy.models import ProxyMode
from vcr_proxy.pytest_plugin import _load_pyproject_config


def test_load_config_from_pyproject(tmp_path, monkeypatch):
    """Plugin reads [tool.vcr-proxy] from pyproject.toml."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.vcr-proxy]\ncassettes_dir = "my_cassettes"\n\n[tool.vcr-proxy.targets]\n"/api" = "http://example.com"\n'
    )
    monkeypatch.chdir(tmp_path)
    config = _load_pyproject_config()
    assert config["cassettes_dir"] == "my_cassettes"
    assert config["targets"]["/api"] == "http://example.com"


def test_load_config_missing_pyproject(tmp_path, monkeypatch):
    """Plugin returns empty dict when pyproject.toml doesn't exist."""
    monkeypatch.chdir(tmp_path)
    config = _load_pyproject_config()
    assert config == {}


def test_mode_from_env_var_record(monkeypatch):
    """VCR_RECORD=1 → spy mode."""
    monkeypatch.setenv("VCR_RECORD", "1")
    import os

    mode = ProxyMode.SPY if os.environ.get("VCR_RECORD") == "1" else ProxyMode.REPLAY
    assert mode == ProxyMode.SPY


def test_mode_from_env_var_replay(monkeypatch):
    """VCR_RECORD unset → replay mode."""
    monkeypatch.delenv("VCR_RECORD", raising=False)
    import os

    mode = ProxyMode.SPY if os.environ.get("VCR_RECORD") == "1" else ProxyMode.REPLAY
    assert mode == ProxyMode.REPLAY


def test_vcr_proxy_app_fixture(vcr_proxy_app):
    """vcr_proxy_app fixture returns a FastAPI app."""
    assert isinstance(vcr_proxy_app, FastAPI)


def test_vcr_proxy_transport_fixture(vcr_proxy_transport):
    """vcr_proxy_transport fixture returns httpx.ASGITransport."""
    assert isinstance(vcr_proxy_transport, httpx.ASGITransport)
