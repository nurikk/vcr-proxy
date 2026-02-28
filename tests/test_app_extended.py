# tests/test_app_extended.py
"""Tests for app.py: create_app factory, proxy endpoint routing."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI

from vcr_proxy.app import create_app
from vcr_proxy.config import Settings
from vcr_proxy.models import ProxyMode
from vcr_proxy.proxy import ProxyHandler


def test_create_app_returns_fastapi(tmp_path: Path):
    app = create_app(
        cassettes_dir=tmp_path / "cassettes",
        mode="spy",
        targets={"/api": "https://example.com"},
    )
    assert isinstance(app, FastAPI)


def test_create_app_sets_handler(tmp_path: Path):
    app = create_app(
        cassettes_dir=tmp_path / "cassettes",
        mode="record",
        targets={"/api": "https://example.com"},
    )
    assert hasattr(app.state, "handler")
    assert isinstance(app.state.handler, ProxyHandler)


def test_create_app_with_settings(tmp_path: Path):
    settings = Settings(
        mode=ProxyMode.REPLAY,
        targets={"/api": "https://example.com"},
        cassettes_dir=tmp_path / "cassettes",
    )
    app = create_app(settings=settings)
    assert app.state.settings.mode == ProxyMode.REPLAY


def test_create_app_default_settings(tmp_path: Path):
    app = create_app(cassettes_dir=tmp_path / "cassettes")
    assert app.state.settings.mode == ProxyMode.SPY


async def test_proxy_endpoint_routes_request(tmp_path: Path):
    app = create_app(
        cassettes_dir=tmp_path / "cassettes",
        mode="record",
        targets={"/api": "https://api.example.com"},
    )
    mock_response = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        json={"ok": True},
    )
    with patch("vcr_proxy.proxy.forward_request", new_callable=AsyncMock) as mock_fwd:
        mock_fwd.return_value = mock_response
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/v1/users")
    assert resp.status_code == 200


async def test_proxy_endpoint_with_query_string(tmp_path: Path):
    app = create_app(
        cassettes_dir=tmp_path / "cassettes",
        mode="record",
        targets={"/api": "https://api.example.com"},
    )
    mock_response = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        json={"page": 1},
    )
    with patch("vcr_proxy.proxy.forward_request", new_callable=AsyncMock) as mock_fwd:
        mock_fwd.return_value = mock_response
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/v1/users", params={"page": "1"})
    assert resp.status_code == 200


async def test_proxy_endpoint_with_body(tmp_path: Path):
    app = create_app(
        cassettes_dir=tmp_path / "cassettes",
        mode="record",
        targets={"/api": "https://api.example.com"},
    )
    mock_response = httpx.Response(
        201,
        headers={"content-type": "application/json"},
        json={"id": 1},
    )
    with patch("vcr_proxy.proxy.forward_request", new_callable=AsyncMock) as mock_fwd:
        mock_fwd.return_value = mock_response
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/v1/users",
                json={"name": "Alice"},
            )
    assert resp.status_code == 201
