# tests/test_proxy_replay.py
from datetime import UTC, datetime
from pathlib import Path

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


def _seed_cassette(cassettes_dir: Path) -> None:
    """Pre-seed a cassette for replay tests."""
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
            headers={
                "host": "test",
                "accept-encoding": "gzip, deflate",
                "connection": "keep-alive",
                "user-agent": "python-httpx/0.28.1",
                "accept": "application/json",
            },
        ),
        response=RecordedResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            body='[{"id": 1}]',
        ),
    )
    key = compute_matching_key(cassette.request, ignore_headers=ALWAYS_IGNORED_HEADERS_DEFAULT)
    storage.save(cassette=cassette, matching_key=key)


async def test_replay_mode_returns_cached(
    replay_client: httpx.AsyncClient,
    cassettes_dir: Path,
):
    _seed_cassette(cassettes_dir)
    response = await replay_client.get(
        "/api/v1/users",
        headers={"accept": "application/json"},
    )
    assert response.status_code == 200
    assert response.json() == [{"id": 1}]


async def test_replay_mode_404_on_miss(
    replay_client: httpx.AsyncClient,
    cassettes_dir: Path,
):
    response = await replay_client.get("/api/v1/nonexistent")
    assert response.status_code == 404
