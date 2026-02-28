# tests/test_admin_extended.py
"""Extended tests for admin.py: cover domain-specific cassette listing and deletion."""

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
def handler(cassettes_dir: Path) -> ProxyHandler:
    settings = Settings(
        mode=ProxyMode.SPY,
        targets={"/api": "https://api.example.com"},
        cassettes_dir=cassettes_dir,
    )
    storage = CassetteStorage(cassettes_dir=settings.cassettes_dir)
    route_config_mgr = RouteConfigManager(cassettes_dir=settings.cassettes_dir)
    http_client = httpx.AsyncClient()
    return ProxyHandler(
        settings=settings,
        storage=storage,
        route_config_manager=route_config_mgr,
        http_client=http_client,
    )


def _seed_cassette(storage: CassetteStorage, domain: str = "api.example.com") -> str:
    cassette = Cassette(
        meta=CassetteMeta(
            recorded_at=datetime(2025, 1, 1, tzinfo=UTC),
            target=f"https://{domain}",
            domain=domain,
            vcr_proxy_version="1.0.0",
        ),
        request=RecordedRequest(
            method="GET",
            path="/v1/users",
            query={},
            headers={"accept": "application/json"},
        ),
        response=RecordedResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            body='[{"id": 1}]',
        ),
    )
    key = MatchingKey(method="GET", path="/v1/users")
    filepath = storage.save(cassette=cassette, matching_key=key)
    return filepath.stem  # cassette_id


@pytest.fixture
async def admin_client(handler: ProxyHandler) -> AsyncIterator[httpx.AsyncClient]:
    app = create_admin_app(handler)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


async def test_list_domain_cassettes(admin_client: httpx.AsyncClient, handler: ProxyHandler):
    _seed_cassette(handler.storage, "api.example.com")
    response = await admin_client.get("/api/cassettes/api.example.com")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["domain"] == "api.example.com"


async def test_list_domain_cassettes_empty(admin_client: httpx.AsyncClient):
    response = await admin_client.get("/api/cassettes/nonexistent.com")
    assert response.status_code == 200
    assert response.json() == []


async def test_delete_domain_cassettes(admin_client: httpx.AsyncClient, handler: ProxyHandler):
    _seed_cassette(handler.storage, "api.example.com")
    response = await admin_client.delete("/api/cassettes/api.example.com")
    assert response.status_code == 200
    assert response.json()["deleted"] >= 1


async def test_delete_single_cassette(admin_client: httpx.AsyncClient, handler: ProxyHandler):
    cassette_id = _seed_cassette(handler.storage, "api.example.com")
    response = await admin_client.delete(f"/api/cassettes/api.example.com/{cassette_id}")
    assert response.status_code == 200
    assert response.json()["deleted"] == 1


async def test_delete_single_cassette_not_found(admin_client: httpx.AsyncClient):
    response = await admin_client.delete("/api/cassettes/api.example.com/nonexistent")
    assert response.status_code == 200
    assert response.json()["deleted"] == 0
