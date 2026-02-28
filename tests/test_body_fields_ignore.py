"""Integration tests for body_fields ignore in route configs.

Verifies the full pipeline: set up route config with body_fields ignore →
record → replay with different ignored fields → match succeeds.
Also verifies that changing non-ignored fields still produces a miss.

NOTE: The ignore config must exist BEFORE recording. The cassette filename
is derived from the matching key hash — if ignore config is added after
recording, the hash changes and the cassette won't be found. This is by
design: the hash-based storage guarantees deterministic lookup.
"""

from pathlib import Path

import httpx
import pytest
import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from vcr_proxy.app import create_app
from vcr_proxy.proxy import ProxyHandler

# ---------------------------------------------------------------------------
# Fake target API
# ---------------------------------------------------------------------------


def _create_fake_login_api() -> FastAPI:
    target = FastAPI()

    @target.post("/login")
    async def login(request: Request):
        body = await request.json()
        return JSONResponse(
            status_code=200,
            content={"token": "fake-token", "action": body.get("action")},
        )

    return target


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_target() -> FastAPI:
    return _create_fake_login_api()


@pytest.fixture
def cassettes_dir(tmp_path: Path) -> Path:
    return tmp_path / "cassettes"


def _make_proxy_app(cassettes_dir: Path, mode: str, fake_target: FastAPI) -> FastAPI:
    app = create_app(
        cassettes_dir=cassettes_dir,
        mode=mode,
        targets={"/api": "http://fake-target"},
    )
    handler: ProxyHandler = app.state.handler
    handler.http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fake_target),
    )
    return app


def _make_replay_client(cassettes_dir: Path) -> httpx.AsyncClient:
    app = create_app(
        cassettes_dir=cassettes_dir,
        mode="replay",
        targets={"/api": "http://fake-target"},
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://proxy",
    )


def _write_route_config(cassettes_dir: Path, body_fields: list[str]) -> None:
    """Pre-create a route config YAML with body_fields ignore."""
    route_dir = cassettes_dir / "_routes" / "fake-target"
    route_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "route": {"method": "POST", "path": "/login"},
        "matched": {"query_params": [], "headers": [], "body_fields": []},
        "ignore": {"headers": [], "body_fields": body_fields, "query_params": []},
    }
    (route_dir / "POST_login.yaml").write_text(
        yaml.dump(config, default_flow_style=False, sort_keys=False)
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_body_fields_ignore_matches_different_credentials(
    cassettes_dir: Path,
    fake_target: FastAPI,
):
    """Record with ignore config, replay with different credentials — match."""
    # 1. Set up ignore config BEFORE recording
    _write_route_config(cassettes_dir, body_fields=["login", "password"])

    # 2. Record
    record_app = _make_proxy_app(cassettes_dir, "record", fake_target)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=record_app),
        base_url="http://proxy",
    ) as client:
        resp = await client.post(
            "/api/login",
            json={"login": "admin", "password": "secret", "action": "search"},
        )
    assert resp.status_code == 200

    # 3. Replay with different credentials — should still match
    async with _make_replay_client(cassettes_dir) as replay:
        resp2 = await replay.post(
            "/api/login",
            json={"login": "other", "password": "different", "action": "search"},
        )
    assert resp2.status_code == 200
    assert resp2.json()["action"] == "search"


async def test_body_fields_ignore_non_ignored_field_causes_miss(
    cassettes_dir: Path,
    fake_target: FastAPI,
):
    """Changing a non-ignored field should cause a cassette miss."""
    # 1. Set up ignore config
    _write_route_config(cassettes_dir, body_fields=["login", "password"])

    # 2. Record
    record_app = _make_proxy_app(cassettes_dir, "record", fake_target)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=record_app),
        base_url="http://proxy",
    ) as client:
        await client.post(
            "/api/login",
            json={"login": "admin", "password": "secret", "action": "search"},
        )

    # 3. Replay with different action — should miss (404)
    async with _make_replay_client(cassettes_dir) as replay:
        resp = await replay.post(
            "/api/login",
            json={"login": "admin", "password": "secret", "action": "delete"},
        )
    assert resp.status_code == 404


async def test_body_fields_ignore_spy_mode(
    cassettes_dir: Path,
    fake_target: FastAPI,
):
    """Spy mode also respects body_fields ignore for cache lookup."""
    # 1. Set up ignore config
    _write_route_config(cassettes_dir, body_fields=["login", "password"])

    # 2. Record via spy (first request = miss → records)
    spy_app = _make_proxy_app(cassettes_dir, "spy", fake_target)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=spy_app),
        base_url="http://proxy",
    ) as client:
        resp = await client.post(
            "/api/login",
            json={"login": "admin", "password": "secret", "action": "search"},
        )
    assert resp.status_code == 200

    # 3. New spy client with different credentials — should hit cache
    spy_app2 = _make_proxy_app(cassettes_dir, "spy", fake_target)
    handler: ProxyHandler = spy_app2.state.handler
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=spy_app2),
        base_url="http://proxy",
    ) as client:
        resp2 = await client.post(
            "/api/login",
            json={"login": "other", "password": "different", "action": "search"},
        )
    assert resp2.status_code == 200
    assert handler.stats_hits == 1
    assert handler.stats_misses == 0


async def test_body_fields_ignore_no_config_records_full_body(
    cassettes_dir: Path,
    fake_target: FastAPI,
):
    """Without ignore config, different credentials produce different cassettes."""
    record_app = _make_proxy_app(cassettes_dir, "record", fake_target)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=record_app),
        base_url="http://proxy",
    ) as client:
        await client.post(
            "/api/login",
            json={"login": "admin", "password": "secret", "action": "search"},
        )
        await client.post(
            "/api/login",
            json={"login": "other", "password": "different", "action": "search"},
        )

    # Two different cassettes were created (different hashes)
    domain_dir = cassettes_dir / "fake-target"
    cassettes = list(domain_dir.glob("*.json"))
    assert len(cassettes) == 2
