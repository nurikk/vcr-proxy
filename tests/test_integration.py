"""Integration tests: full end-to-end flows without mocks.

Uses a fake target API (FastAPI app) served via httpx.ASGITransport
so the entire proxy pipeline is exercised: request → normalize → match →
forward/lookup → store/return.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from vcr_proxy.admin import create_admin_app
from vcr_proxy.app import create_app
from vcr_proxy.proxy import ProxyHandler

# ---------------------------------------------------------------------------
# Fake target API — a simple echo/counter service for the proxy to hit
# ---------------------------------------------------------------------------


def _create_fake_target() -> FastAPI:
    target = FastAPI()
    call_count: dict[str, int] = {}

    @target.get("/v1/users")
    async def list_users():
        call_count["list_users"] = call_count.get("list_users", 0) + 1
        return {"users": [{"id": 1, "name": "Alice"}], "call_count": call_count["list_users"]}

    @target.get("/v1/users/{user_id}")
    async def get_user(user_id: int):
        return {"id": user_id, "name": f"User {user_id}"}

    @target.post("/v1/users")
    async def create_user(request: Request):
        body = await request.json()
        return JSONResponse(
            status_code=201,
            content={"id": 42, **body},
        )

    @target.put("/v1/users/{user_id}")
    async def update_user(user_id: int, request: Request):
        body = await request.json()
        return {"id": user_id, **body}

    @target.delete("/v1/users/{user_id}")
    async def delete_user(user_id: int):
        return {"deleted": True, "id": user_id}

    @target.get("/v1/health")
    async def health():
        return {"status": "ok"}

    @target.post("/v1/search")
    async def search(request: Request):
        body = await request.json()
        query = body.get("query", "")
        return {"results": [f"result for '{query}'"], "query": query}

    return target


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_target() -> FastAPI:
    return _create_fake_target()


@pytest.fixture
def cassettes_dir(tmp_path: Path) -> Path:
    return tmp_path / "cassettes"


def _make_proxy_app(
    cassettes_dir: Path,
    mode: str,
    fake_target: FastAPI,
) -> FastAPI:
    """Create a VCR Proxy app wired to a fake target via ASGI transport."""
    app = create_app(
        cassettes_dir=cassettes_dir,
        mode=mode,
        targets={"/api": "http://fake-target"},
    )
    # Replace the handler's http_client with one that routes to the fake target
    handler: ProxyHandler = app.state.handler
    handler.http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fake_target),
    )
    return app


@pytest.fixture
def record_app(cassettes_dir: Path, fake_target: FastAPI) -> FastAPI:
    return _make_proxy_app(cassettes_dir, "record", fake_target)


@pytest.fixture
def spy_app(cassettes_dir: Path, fake_target: FastAPI) -> FastAPI:
    return _make_proxy_app(cassettes_dir, "spy", fake_target)


@pytest.fixture
async def record_client(record_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=record_app),
        base_url="http://proxy",
    ) as client:
        yield client


@pytest.fixture
async def spy_client(spy_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=spy_app),
        base_url="http://proxy",
    ) as client:
        yield client


def _make_replay_client(cassettes_dir: Path) -> httpx.AsyncClient:
    """Create a replay-mode client (uses same cassettes dir, no target needed)."""
    app = create_app(
        cassettes_dir=cassettes_dir,
        mode="replay",
        targets={"/api": "http://fake-target"},
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://proxy",
    )


# ---------------------------------------------------------------------------
# Record → Replay full cycle
# ---------------------------------------------------------------------------


async def test_record_then_replay_get(
    record_client: httpx.AsyncClient,
    cassettes_dir: Path,
):
    """Record a GET, then replay it — response matches."""
    # Record
    resp = await record_client.get("/api/v1/users")
    assert resp.status_code == 200
    recorded_body = resp.json()
    assert recorded_body["users"][0]["name"] == "Alice"

    # Replay from same cassettes dir
    async with _make_replay_client(cassettes_dir) as replay:
        resp2 = await replay.get("/api/v1/users")
    assert resp2.status_code == 200
    assert resp2.json()["users"] == recorded_body["users"]


async def test_record_then_replay_post(
    record_client: httpx.AsyncClient,
    cassettes_dir: Path,
):
    """Record a POST with JSON body, then replay — response matches."""
    resp = await record_client.post("/api/v1/users", json={"name": "Bob", "role": "user"})
    assert resp.status_code == 201
    recorded_body = resp.json()
    assert recorded_body["name"] == "Bob"
    assert recorded_body["id"] == 42

    async with _make_replay_client(cassettes_dir) as replay:
        resp2 = await replay.post("/api/v1/users", json={"name": "Bob", "role": "user"})
    assert resp2.status_code == 201
    assert resp2.json() == recorded_body


async def test_different_post_bodies_produce_different_cassettes(
    record_client: httpx.AsyncClient,
    cassettes_dir: Path,
):
    """The core value prop: different JSON bodies → different cassettes."""
    resp_a = await record_client.post("/api/v1/search", json={"query": "alice"})
    resp_b = await record_client.post("/api/v1/search", json={"query": "bob"})
    assert resp_a.json()["query"] == "alice"
    assert resp_b.json()["query"] == "bob"

    # Both cassettes exist
    domain_dir = cassettes_dir / "fake-target"
    cassettes = list(domain_dir.glob("*.json"))
    assert len(cassettes) == 2

    # Replay returns the correct one for each body
    async with _make_replay_client(cassettes_dir) as replay:
        r_a = await replay.post("/api/v1/search", json={"query": "alice"})
        r_b = await replay.post("/api/v1/search", json={"query": "bob"})
    assert r_a.json()["query"] == "alice"
    assert r_b.json()["query"] == "bob"


async def test_replay_404_on_unrecorded_request(cassettes_dir: Path):
    """Replay mode returns 404 for requests that were never recorded."""
    async with _make_replay_client(cassettes_dir) as replay:
        resp = await replay.get("/api/v1/nonexistent")
    assert resp.status_code == 404
    assert "no matching cassette" in resp.json()["error"]


# ---------------------------------------------------------------------------
# Spy mode
# ---------------------------------------------------------------------------


async def test_spy_miss_then_hit(
    spy_client: httpx.AsyncClient,
    cassettes_dir: Path,
):
    """Spy mode: first call is a miss (forwards), second is a hit (cached)."""
    # First call — cache miss, hits real target
    resp1 = await spy_client.get("/api/v1/users")
    assert resp1.status_code == 200
    assert resp1.json()["call_count"] == 1

    # Second call — cache hit, returns recorded response (call_count stays 1)
    resp2 = await spy_client.get("/api/v1/users")
    assert resp2.status_code == 200
    assert resp2.json()["call_count"] == 1  # same recorded response


async def test_spy_records_on_miss(
    spy_client: httpx.AsyncClient,
    cassettes_dir: Path,
):
    """Spy mode: missed request is recorded as a cassette."""
    await spy_client.get("/api/v1/health")
    cassettes = list(cassettes_dir.rglob("*.json"))
    assert len(cassettes) == 1


# ---------------------------------------------------------------------------
# Multiple HTTP methods
# ---------------------------------------------------------------------------


async def test_record_put_method(
    record_client: httpx.AsyncClient,
    cassettes_dir: Path,
):
    """PUT requests are recorded and replayed correctly."""
    resp = await record_client.put("/api/v1/users/5", json={"name": "Updated"})
    assert resp.status_code == 200
    assert resp.json()["id"] == 5

    async with _make_replay_client(cassettes_dir) as replay:
        resp2 = await replay.put("/api/v1/users/5", json={"name": "Updated"})
    assert resp2.status_code == 200
    assert resp2.json() == resp.json()


async def test_record_delete_method(
    record_client: httpx.AsyncClient,
    cassettes_dir: Path,
):
    """DELETE requests are recorded and replayed correctly."""
    resp = await record_client.delete("/api/v1/users/99")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True

    async with _make_replay_client(cassettes_dir) as replay:
        resp2 = await replay.delete("/api/v1/users/99")
    assert resp2.status_code == 200
    assert resp2.json()["deleted"] is True


# ---------------------------------------------------------------------------
# Query string handling
# ---------------------------------------------------------------------------


async def test_query_params_recorded_and_matched(
    record_client: httpx.AsyncClient,
    cassettes_dir: Path,
):
    """Query parameters are part of the matching key."""
    resp = await record_client.get("/api/v1/users", params={"page": "1", "limit": "10"})
    assert resp.status_code == 200

    async with _make_replay_client(cassettes_dir) as replay:
        # Same params → hit
        hit = await replay.get("/api/v1/users", params={"page": "1", "limit": "10"})
        assert hit.status_code == 200

        # Different params → miss (404)
        miss = await replay.get("/api/v1/users", params={"page": "2", "limit": "10"})
        assert miss.status_code == 404


async def test_query_param_order_does_not_matter(
    record_client: httpx.AsyncClient,
    cassettes_dir: Path,
):
    """Query params are normalized (sorted), so order doesn't affect matching."""
    await record_client.get("/api/v1/users", params={"z": "1", "a": "2"})

    async with _make_replay_client(cassettes_dir) as replay:
        # Reversed order — should still match
        resp = await replay.get("/api/v1/users", params={"a": "2", "z": "1"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# JSON body key order
# ---------------------------------------------------------------------------


async def test_json_key_order_does_not_matter(
    record_client: httpx.AsyncClient,
    cassettes_dir: Path,
):
    """JSON body with different key order matches the same cassette."""
    await record_client.post(
        "/api/v1/users",
        content='{"name": "Alice", "role": "admin"}',
        headers={"content-type": "application/json"},
    )

    async with _make_replay_client(cassettes_dir) as replay:
        resp = await replay.post(
            "/api/v1/users",
            content='{"role": "admin", "name": "Alice"}',
            headers={"content-type": "application/json"},
        )
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Route config auto-generation
# ---------------------------------------------------------------------------


async def test_route_config_generated_on_record(
    record_client: httpx.AsyncClient,
    cassettes_dir: Path,
):
    """Recording a request auto-generates a route config YAML."""
    await record_client.post(
        "/api/v1/users",
        json={"name": "Alice"},
    )

    routes_dir = cassettes_dir / "_routes" / "fake-target"
    assert routes_dir.exists()
    yamls = list(routes_dir.glob("*.yaml"))
    assert len(yamls) == 1


# ---------------------------------------------------------------------------
# Stats tracking
# ---------------------------------------------------------------------------


async def test_stats_accumulate(
    spy_app: FastAPI,
    spy_client: httpx.AsyncClient,
):
    """Stats counters track hits, misses, and recordings."""
    handler: ProxyHandler = spy_app.state.handler

    # First request — miss → record
    await spy_client.get("/api/v1/health")
    assert handler.stats_total == 1
    assert handler.stats_misses == 1
    assert handler.stats_recorded == 1
    assert handler.stats_hits == 0

    # Second request — hit from cache
    await spy_client.get("/api/v1/health")
    assert handler.stats_total == 2
    assert handler.stats_hits == 1
    assert handler.stats_misses == 1
    assert handler.stats_recorded == 1


# ---------------------------------------------------------------------------
# Mode switching via admin API
# ---------------------------------------------------------------------------


async def test_mode_switch_record_to_replay(
    cassettes_dir: Path,
    fake_target: FastAPI,
):
    """Switch from record to replay at runtime via the admin API."""
    app = _make_proxy_app(cassettes_dir, "record", fake_target)
    handler: ProxyHandler = app.state.handler
    admin_app = create_admin_app(handler)

    async with (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://proxy"
        ) as proxy,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=admin_app), base_url="http://admin"
        ) as admin,
    ):
        # Record a request
        resp = await proxy.get("/api/v1/health")
        assert resp.status_code == 200

        # Switch to replay
        switch = await admin.put("/api/mode", json={"mode": "replay"})
        assert switch.json()["mode"] == "replay"

        # Replay returns the recorded response
        resp2 = await proxy.get("/api/v1/health")
        assert resp2.status_code == 200

        # Unrecorded request → 404 in replay mode
        resp3 = await proxy.get("/api/v1/nonexistent")
        assert resp3.status_code == 404


# ---------------------------------------------------------------------------
# Admin API cassette management (integration)
# ---------------------------------------------------------------------------


async def test_admin_list_and_delete_cassettes(
    cassettes_dir: Path,
    fake_target: FastAPI,
):
    """Admin API lists and deletes recorded cassettes."""
    app = _make_proxy_app(cassettes_dir, "record", fake_target)
    handler: ProxyHandler = app.state.handler
    admin_app = create_admin_app(handler)

    async with (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://proxy"
        ) as proxy,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=admin_app), base_url="http://admin"
        ) as admin,
    ):
        # Record two requests
        await proxy.get("/api/v1/users")
        await proxy.get("/api/v1/health")

        # Admin lists them
        listing = await admin.get("/api/cassettes")
        assert listing.status_code == 200
        assert len(listing.json()) == 2

        # Delete all
        delete = await admin.delete("/api/cassettes")
        assert delete.json()["deleted"] == 2

        # Now empty
        listing2 = await admin.get("/api/cassettes")
        assert listing2.json() == []


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


async def test_no_target_configured_returns_502(cassettes_dir: Path):
    """Request to an unconfigured path prefix returns 502."""
    app = create_app(
        cassettes_dir=cassettes_dir,
        mode="record",
        targets={"/api": "http://fake-target"},
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://proxy"
    ) as client:
        resp = await client.get("/unknown/path")
    assert resp.status_code == 502
    assert "no target configured" in resp.json()["error"]


async def test_target_unreachable_returns_502(cassettes_dir: Path):
    """Connection error to target returns 502."""
    app = create_app(
        cassettes_dir=cassettes_dir,
        mode="record",
        targets={"/api": "http://unreachable.invalid:9999"},
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://proxy"
    ) as client:
        resp = await client.get("/api/v1/test")
    assert resp.status_code == 502


# ---------------------------------------------------------------------------
# Cassette file structure
# ---------------------------------------------------------------------------


async def test_cassette_file_contains_request_and_response(
    record_client: httpx.AsyncClient,
    cassettes_dir: Path,
):
    """Cassette JSON has meta, request, and response fields."""
    import json

    await record_client.post("/api/v1/users", json={"name": "Charlie"})

    cassettes = list(cassettes_dir.rglob("*.json"))
    assert len(cassettes) == 1

    data = json.loads(cassettes[0].read_text())
    assert "meta" in data
    assert "request" in data
    assert "response" in data
    assert data["meta"]["domain"] == "fake-target"
    assert data["request"]["method"] == "POST"
    assert data["response"]["status_code"] == 201
