# tests/test_proxy_record.py
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from vcr_proxy.recording import REDACTED


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


async def test_record_redacts_sensitive_headers_in_cassette(
    record_client: httpx.AsyncClient,
    cassettes_dir: Path,
):
    """Sensitive headers (e.g. Authorization) are redacted in the stored cassette
    but the real response is returned to the caller unmodified."""
    mock_resp = httpx.Response(
        status_code=200,
        headers={"content-type": "application/json", "set-cookie": "session=abc123"},
        json={"ok": True},
    )
    with patch("vcr_proxy.proxy.forward_request", new_callable=AsyncMock) as mock_forward:
        mock_forward.return_value = mock_resp
        response = await record_client.get(
            "/api/v1/users",
            headers={"Authorization": "Bearer secret-token"},
        )

    # The live response returned to the client must NOT be redacted
    assert response.status_code == 200

    # The cassette file on disk must contain redacted values
    domain_dir = cassettes_dir / "api.example.com"
    cassette_files = list(domain_dir.glob("*.json"))
    assert len(cassette_files) == 1
    cassette = json.loads(cassette_files[0].read_text())

    # Request authorization header is redacted
    assert cassette["request"]["headers"]["authorization"] == REDACTED

    # Response set-cookie header is redacted
    assert cassette["response"]["headers"]["set-cookie"] == REDACTED
