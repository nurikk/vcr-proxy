"""pytest plugin providing session-scoped VCR Proxy fixtures."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from vcr_proxy.app import create_app
from vcr_proxy.models import ProxyMode


def _load_pyproject_config() -> dict:
    """Load [tool.vcr-proxy] from pyproject.toml."""
    pyproject = Path("pyproject.toml")
    if not pyproject.exists():
        return {}
    with pyproject.open("rb") as f:
        data = tomllib.load(f)
    return data.get("tool", {}).get("vcr-proxy", {})


@pytest.fixture(scope="session")
def vcr_mode() -> ProxyMode:
    """Proxy mode: VCR_RECORD=1 → spy, otherwise replay."""
    if os.environ.get("VCR_RECORD") == "1":
        return ProxyMode.SPY
    return ProxyMode.REPLAY


@pytest.fixture(scope="session")
def vcr_proxy_app(vcr_mode: ProxyMode) -> FastAPI:
    """Session-scoped VCR Proxy FastAPI app."""
    config = _load_pyproject_config()
    cassettes_dir = Path(config.get("cassettes_dir", "cassettes"))
    targets = config.get("targets", {})
    return create_app(cassettes_dir=cassettes_dir, mode=vcr_mode.value, targets=targets)


@pytest.fixture(scope="session")
def vcr_proxy_transport(vcr_proxy_app: FastAPI) -> httpx.ASGITransport:
    """Session-scoped ASGI transport wrapping the VCR Proxy app."""
    return httpx.ASGITransport(app=vcr_proxy_app)
