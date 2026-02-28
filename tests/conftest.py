# tests/conftest.py
import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from vcr_proxy.app import create_app
from vcr_proxy.models import ProxyMode


@pytest.fixture
def cassettes_dir(tmp_path: Path) -> Path:
    return tmp_path / "cassettes"


# --- Fixtures originally provided by the vcr-proxy pytest plugin ---
# The plugin is disabled at test time (see root conftest.py) so coverage
# can track all vcr_proxy module imports.  We replicate the three public
# fixtures here.


@pytest.fixture(scope="session")
def vcr_mode() -> ProxyMode:
    """Proxy mode: VCR_RECORD=1 -> spy, otherwise replay."""
    if os.environ.get("VCR_RECORD") == "1":
        return ProxyMode.SPY
    return ProxyMode.REPLAY


@pytest.fixture(scope="session")
def vcr_proxy_app(vcr_mode: ProxyMode) -> FastAPI:
    """Session-scoped VCR Proxy FastAPI app."""
    from vcr_proxy.pytest_plugin import _load_pyproject_config

    config = _load_pyproject_config()
    cassettes_dir = Path(config.get("cassettes_dir", "cassettes"))
    targets = config.get("targets", {})
    return create_app(cassettes_dir=cassettes_dir, mode=vcr_mode.value, targets=targets)


@pytest.fixture(scope="session")
def vcr_proxy_transport(vcr_proxy_app: FastAPI) -> httpx.ASGITransport:
    """Session-scoped ASGI transport wrapping the VCR Proxy app."""
    return httpx.ASGITransport(app=vcr_proxy_app)


@pytest.fixture
async def record_client(cassettes_dir: Path) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        cassettes_dir=cassettes_dir,
        mode="record",
        targets={"/api": "https://api.example.com"},
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture
async def replay_client(cassettes_dir: Path) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        cassettes_dir=cassettes_dir,
        mode="replay",
        targets={"/api": "https://api.example.com"},
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture
async def spy_client(cassettes_dir: Path) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        cassettes_dir=cassettes_dir,
        mode="spy",
        targets={"/api": "https://api.example.com"},
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client
