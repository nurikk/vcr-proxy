# tests/conftest.py
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from vcr_proxy.app import create_app


@pytest.fixture
def cassettes_dir(tmp_path: Path) -> Path:
    return tmp_path / "cassettes"


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
