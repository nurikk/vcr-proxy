# tests/test_proxy_spy.py
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from vcr_proxy.config import ALWAYS_IGNORED_HEADERS_DEFAULT
from vcr_proxy.matching import compute_matching_key
from vcr_proxy.models import (
    Cassette,
    CassetteMeta,
    RecordedRequest,
    RecordedResponse,
)
from vcr_proxy.storage import CassetteStorage


def _default_httpx_headers() -> dict[str, str]:
    """Get the default headers httpx sends (varies by installed codecs)."""
    client = httpx.Client(base_url="http://test")
    req = client.build_request("GET", "/api/v1/users", headers={"accept": "application/json"})
    return {k: v for k, v in req.headers.items()}


def _seed_cassette(cassettes_dir: Path) -> None:
    storage = CassetteStorage(cassettes_dir=cassettes_dir)
    cassette = Cassette(
        meta=CassetteMeta(
            recorded_at=datetime(2025, 1, 1, tzinfo=UTC),
            target="https://api.example.com",
            domain="api.example.com",
            vcr_proxy_version="1.0.0",
        ),
        request=RecordedRequest(
            method="GET",
            path="/v1/users",
            query={},
            headers=_default_httpx_headers(),
        ),
        response=RecordedResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            body='[{"id": 1}]',
        ),
    )
    key = compute_matching_key(cassette.request, ignore_headers=ALWAYS_IGNORED_HEADERS_DEFAULT)
    storage.save(cassette=cassette, matching_key=key)


async def test_spy_mode_returns_cached_on_hit(
    spy_client: httpx.AsyncClient,
    cassettes_dir: Path,
):
    _seed_cassette(cassettes_dir)
    response = await spy_client.get(
        "/api/v1/users",
        headers={"accept": "application/json"},
    )
    assert response.status_code == 200
    assert response.json() == [{"id": 1}]


async def test_spy_mode_proxies_on_miss(
    spy_client: httpx.AsyncClient,
    cassettes_dir: Path,
):
    mock_resp = httpx.Response(
        status_code=200,
        headers={"content-type": "application/json"},
        json={"id": 42},
    )
    with patch("vcr_proxy.proxy.forward_request", new_callable=AsyncMock) as mock_forward:
        mock_forward.return_value = mock_resp
        response = await spy_client.get("/api/v1/new-endpoint")

    assert response.status_code == 200
    # Cassette should have been recorded
    cassettes = list(cassettes_dir.rglob("*.json"))
    assert len(cassettes) == 1
