# tests/test_admin_api.py
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from vcr_proxy.admin import create_admin_app
from vcr_proxy.config import Settings
from vcr_proxy.models import (
    Cassette,
    CassetteMeta,
    MatchingKey,
    ProxyMode,
    RecordedRequest,
    RecordedResponse,
)
from vcr_proxy.proxy import ProxyHandler
from vcr_proxy.route_config import RouteConfigManager
from vcr_proxy.storage import CassetteStorage


@pytest.fixture
def cassettes_dir(tmp_path: Path) -> Path:
    return tmp_path / "cassettes"


@pytest.fixture
def settings(cassettes_dir: Path) -> Settings:
    return Settings(
        mode=ProxyMode.SPY,
        targets={"/api": "https://api.example.com"},
        cassettes_dir=cassettes_dir,
    )


@pytest.fixture
def handler(settings: Settings) -> ProxyHandler:
    storage = CassetteStorage(cassettes_dir=settings.cassettes_dir)
    route_config_mgr = RouteConfigManager(cassettes_dir=settings.cassettes_dir)
    http_client = httpx.AsyncClient()
    return ProxyHandler(
        settings=settings,
        storage=storage,
        route_config_manager=route_config_mgr,
        http_client=http_client,
    )


@pytest.fixture
async def admin_client(handler: ProxyHandler) -> AsyncIterator[httpx.AsyncClient]:
    app = create_admin_app(handler)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


async def test_get_mode(admin_client: httpx.AsyncClient):
    response = await admin_client.get("/api/mode")
    assert response.status_code == 200
    assert response.json()["mode"] == "spy"


async def test_put_mode(admin_client: httpx.AsyncClient):
    response = await admin_client.put("/api/mode", json={"mode": "replay"})
    assert response.status_code == 200
    assert response.json()["mode"] == "replay"


async def test_put_mode_invalid(admin_client: httpx.AsyncClient):
    response = await admin_client.put("/api/mode", json={"mode": "invalid"})
    assert response.status_code == 422


async def test_get_stats(admin_client: httpx.AsyncClient):
    response = await admin_client.get("/api/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total_requests"] == 0
    assert data["cache_hits"] == 0


async def test_list_cassettes_empty(admin_client: httpx.AsyncClient):
    response = await admin_client.get("/api/cassettes")
    assert response.status_code == 200
    assert response.json() == []


async def test_delete_all_cassettes(admin_client: httpx.AsyncClient, handler: ProxyHandler):
    # Seed a cassette
    storage = handler.storage
    cassette = Cassette(
        meta=CassetteMeta(
            recorded_at=datetime(2025, 1, 1, tzinfo=UTC),
            target="https://api.example.com",
            domain="api.example.com",
            vcr_proxy_version="1.0.0",
        ),
        request=RecordedRequest(
            method="GET",
            path="/api/v1/users",
            query={},
            headers={"accept": "application/json"},
        ),
        response=RecordedResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            body="[]",
        ),
    )
    key = MatchingKey(method="GET", path="/api/v1/users")
    storage.save(cassette=cassette, matching_key=key)

    response = await admin_client.delete("/api/cassettes")
    assert response.status_code == 200
    assert response.json()["deleted"] >= 1
