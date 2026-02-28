# tests/test_proxy_record.py
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest


@pytest.fixture
def mock_target_response() -> httpx.Response:
    return httpx.Response(
        status_code=200,
        headers={"content-type": "application/json"},
        json={"id": 1, "name": "Alice"},
    )


async def test_record_mode_proxies_and_saves(
    record_client: httpx.AsyncClient,
    cassettes_dir: Path,
    mock_target_response: httpx.Response,
):
    with patch("vcr_proxy.proxy.forward_request", new_callable=AsyncMock) as mock_forward:
        mock_forward.return_value = mock_target_response
        response = await record_client.get("/api/v1/users")

    assert response.status_code == 200
    domain_dir = cassettes_dir / "api.example.com"
    assert domain_dir.exists()
    cassettes = list(domain_dir.glob("*.json"))
    assert len(cassettes) == 1


async def test_record_mode_post_with_body(
    record_client: httpx.AsyncClient,
    cassettes_dir: Path,
    mock_target_response: httpx.Response,
):
    with patch("vcr_proxy.proxy.forward_request", new_callable=AsyncMock) as mock_forward:
        mock_forward.return_value = mock_target_response
        response = await record_client.post(
            "/api/v1/users",
            json={"name": "Alice"},
        )

    assert response.status_code == 200
    cassettes = list((cassettes_dir / "api.example.com").glob("*.json"))
    assert len(cassettes) == 1
