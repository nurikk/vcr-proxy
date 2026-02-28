# tests/test_proxy_extended.py
"""Extended tests for proxy.py: cover error branches, resolve_target, decode_body, etc."""

import base64
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from vcr_proxy.config import Settings
from vcr_proxy.models import (
    Cassette,
    CassetteMeta,
    ProxyMode,
    RecordedRequest,
    RecordedResponse,
)
from vcr_proxy.proxy import (
    ProxyHandler,
    _build_recorded_response,
    _resolve_target,
    forward_request,
)
from vcr_proxy.route_config import RouteConfigManager
from vcr_proxy.storage import CassetteStorage

# --- _resolve_target ---


def test_resolve_target_exact_prefix():
    targets = {"/api": "https://api.example.com"}
    result = _resolve_target("/api", targets)
    assert result is not None
    target_url, domain, remaining = result
    assert target_url == "https://api.example.com"
    assert domain == "api.example.com"
    assert remaining == "/"


def test_resolve_target_with_subpath():
    targets = {"/api": "https://api.example.com"}
    result = _resolve_target("/api/v1/users", targets)
    assert result is not None
    target_url, domain, remaining = result
    assert remaining == "/v1/users"


def test_resolve_target_catch_all():
    targets = {"/": "https://default.example.com"}
    result = _resolve_target("/anything/here", targets)
    assert result is not None
    target_url, domain, remaining = result
    assert remaining == "/anything/here"


def test_resolve_target_no_match():
    targets = {"/api": "https://api.example.com"}
    result = _resolve_target("/other", targets)
    assert result is None


def test_resolve_target_longest_prefix_wins():
    targets = {
        "/api": "https://api.example.com",
        "/api/v2": "https://api-v2.example.com",
    }
    result = _resolve_target("/api/v2/users", targets)
    assert result is not None
    target_url, domain, remaining = result
    assert target_url == "https://api-v2.example.com"
    assert domain == "api-v2.example.com"
    assert remaining == "/users"


# --- _build_recorded_response ---


def test_build_recorded_response_text():
    response = httpx.Response(
        status_code=200,
        headers={"content-type": "application/json"},
        json={"ok": True},
    )
    recorded = _build_recorded_response(response)
    assert recorded.status_code == 200
    assert recorded.body_encoding == "utf-8"
    assert recorded.body is not None


def test_build_recorded_response_binary():
    response = httpx.Response(
        status_code=200,
        headers={"content-type": "application/octet-stream"},
        content=b"\x00\x01\x02",
    )
    recorded = _build_recorded_response(response)
    assert recorded.body_encoding == "base64"
    assert recorded.body == base64.b64encode(b"\x00\x01\x02").decode("ascii")


# --- forward_request ---


async def test_forward_request_builds_correct_url():
    mock_response = httpx.Response(200, json={"ok": True})
    client = AsyncMock(spec=httpx.AsyncClient)
    client.request = AsyncMock(return_value=mock_response)

    result = await forward_request(
        client=client,
        target_url="https://api.example.com",
        method="GET",
        path="/v1/users",
        headers={"host": "proxy.local", "accept": "application/json"},
        body=None,
    )

    assert result.status_code == 200
    client.request.assert_called_once()
    call_kwargs = client.request.call_args
    # host header should be stripped
    assert "host" not in call_kwargs.kwargs.get("headers", {})


# --- ProxyHandler ---


@pytest.fixture
def handler(tmp_path: Path) -> ProxyHandler:
    settings = Settings(
        mode=ProxyMode.RECORD,
        targets={"/api": "https://api.example.com"},
        cassettes_dir=tmp_path / "cassettes",
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


async def test_handle_no_target_returns_502(handler: ProxyHandler):
    status, headers, body = await handler.handle(
        method="GET",
        path="/unknown",
        query_string="",
        headers={},
        body=None,
    )
    assert status == 502
    assert b"no target configured" in body
    assert handler.stats_errors == 1


async def test_handle_record_timeout(handler: ProxyHandler):
    with patch("vcr_proxy.proxy.forward_request", new_callable=AsyncMock) as mock_fwd:
        mock_fwd.side_effect = httpx.TimeoutException("timeout")
        status, headers, body = await handler.handle(
            method="GET",
            path="/api/v1/test",
            query_string="",
            headers={},
            body=None,
        )
    assert status == 504
    assert b"target timeout" in body
    assert handler.stats_errors == 1


async def test_handle_record_connect_error(handler: ProxyHandler):
    with patch("vcr_proxy.proxy.forward_request", new_callable=AsyncMock) as mock_fwd:
        mock_fwd.side_effect = httpx.ConnectError("connection refused")
        status, headers, body = await handler.handle(
            method="GET",
            path="/api/v1/test",
            query_string="",
            headers={},
            body=None,
        )
    assert status == 502
    assert b"target unreachable" in body
    assert handler.stats_errors == 1


async def test_handle_record_success(handler: ProxyHandler):
    mock_response = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        json={"id": 1},
    )
    with patch("vcr_proxy.proxy.forward_request", new_callable=AsyncMock) as mock_fwd:
        mock_fwd.return_value = mock_response
        status, headers, body = await handler.handle(
            method="GET",
            path="/api/v1/users",
            query_string="",
            headers={},
            body=None,
        )
    assert status == 200
    assert handler.stats_recorded == 1


async def test_handle_replay_hit(tmp_path: Path):
    settings = Settings(
        mode=ProxyMode.REPLAY,
        targets={"/api": "https://api.example.com"},
        cassettes_dir=tmp_path / "cassettes",
    )
    storage = CassetteStorage(cassettes_dir=settings.cassettes_dir)
    route_config_mgr = RouteConfigManager(cassettes_dir=settings.cassettes_dir)
    http_client = httpx.AsyncClient()
    handler = ProxyHandler(
        settings=settings,
        storage=storage,
        route_config_manager=route_config_mgr,
        http_client=http_client,
    )

    # Seed a cassette
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
            headers={},
        ),
        response=RecordedResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            body='[{"id": 1}]',
        ),
    )
    from vcr_proxy.matching import compute_matching_key

    key = compute_matching_key(cassette.request, ignore_headers=settings.always_ignore_headers)
    storage.save(cassette=cassette, matching_key=key)

    status, headers, body = await handler.handle(
        method="GET",
        path="/api/v1/users",
        query_string="",
        headers={},
        body=None,
    )
    assert status == 200
    assert handler.stats_hits == 1


async def test_handle_replay_miss(tmp_path: Path):
    settings = Settings(
        mode=ProxyMode.REPLAY,
        targets={"/api": "https://api.example.com"},
        cassettes_dir=tmp_path / "cassettes",
    )
    storage = CassetteStorage(cassettes_dir=settings.cassettes_dir)
    route_config_mgr = RouteConfigManager(cassettes_dir=settings.cassettes_dir)
    http_client = httpx.AsyncClient()
    handler = ProxyHandler(
        settings=settings,
        storage=storage,
        route_config_manager=route_config_mgr,
        http_client=http_client,
    )

    status, headers, body = await handler.handle(
        method="GET",
        path="/api/v1/nonexistent",
        query_string="",
        headers={},
        body=None,
    )
    assert status == 404
    assert b"no matching cassette" in body
    assert handler.stats_misses == 1


async def test_handle_spy_hit(tmp_path: Path):
    settings = Settings(
        mode=ProxyMode.SPY,
        targets={"/api": "https://api.example.com"},
        cassettes_dir=tmp_path / "cassettes",
    )
    storage = CassetteStorage(cassettes_dir=settings.cassettes_dir)
    route_config_mgr = RouteConfigManager(cassettes_dir=settings.cassettes_dir)
    http_client = httpx.AsyncClient()
    handler = ProxyHandler(
        settings=settings,
        storage=storage,
        route_config_manager=route_config_mgr,
        http_client=http_client,
    )

    # Seed a cassette
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
            headers={},
        ),
        response=RecordedResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            body='[{"id": 1}]',
        ),
    )
    from vcr_proxy.matching import compute_matching_key

    key = compute_matching_key(cassette.request, ignore_headers=settings.always_ignore_headers)
    storage.save(cassette=cassette, matching_key=key)

    status, headers, body = await handler.handle(
        method="GET",
        path="/api/v1/users",
        query_string="",
        headers={},
        body=None,
    )
    assert status == 200
    assert handler.stats_hits == 1


async def test_handle_spy_miss_then_records(tmp_path: Path):
    settings = Settings(
        mode=ProxyMode.SPY,
        targets={"/api": "https://api.example.com"},
        cassettes_dir=tmp_path / "cassettes",
    )
    storage = CassetteStorage(cassettes_dir=settings.cassettes_dir)
    route_config_mgr = RouteConfigManager(cassettes_dir=settings.cassettes_dir)
    http_client = httpx.AsyncClient()
    handler = ProxyHandler(
        settings=settings,
        storage=storage,
        route_config_manager=route_config_mgr,
        http_client=http_client,
    )

    mock_response = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        json={"id": 42},
    )
    with patch("vcr_proxy.proxy.forward_request", new_callable=AsyncMock) as mock_fwd:
        mock_fwd.return_value = mock_response
        status, headers, body = await handler.handle(
            method="GET",
            path="/api/v1/new",
            query_string="",
            headers={},
            body=None,
        )
    assert status == 200
    assert handler.stats_misses == 1
    assert handler.stats_recorded == 1


# --- _decode_body ---


def test_decode_body_none():
    resp = RecordedResponse(status_code=200, headers={}, body=None)
    result = ProxyHandler._decode_body(resp)
    assert result == b""


def test_decode_body_base64():
    encoded = base64.b64encode(b"\x00\x01\x02").decode("ascii")
    resp = RecordedResponse(status_code=200, headers={}, body=encoded, body_encoding="base64")
    result = ProxyHandler._decode_body(resp)
    assert result == b"\x00\x01\x02"


def test_decode_body_utf8():
    resp = RecordedResponse(status_code=200, headers={}, body="hello world", body_encoding="utf-8")
    result = ProxyHandler._decode_body(resp)
    assert result == b"hello world"
