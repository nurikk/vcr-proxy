"""Integration tests for the forward proxy addon.

Tests the full record → replay cycle, spy mode workflows,
domain extraction, and admin API compatibility with VCRAddon.
"""

import httpx
from mitmproxy.test import tflow, tutils

from vcr_proxy.admin import create_admin_app
from vcr_proxy.config import Settings
from vcr_proxy.forward import VCRAddon
from vcr_proxy.models import ProxyMode


def _make_settings(tmp_path, mode=ProxyMode.RECORD):
    return Settings(
        mode=mode,
        cassettes_dir=tmp_path / "cassettes",
    )


def _make_flow(host, path, method="GET", body=b"", headers=None, query=""):
    hdrs = [(b"host", host.encode())]
    if headers:
        for k, v in headers.items():
            hdrs.append((k.encode(), v.encode()))
    full_path = f"{path}?{query}" if query else path
    return tflow.tflow(
        req=tutils.treq(
            method=method.encode(),
            host=host,
            port=443,
            scheme=b"https",
            authority=host.encode(),
            path=full_path.encode(),
            headers=hdrs,
            content=body,
        )
    )


def _add_response(flow, body=b'{"ok":true}', status=200, content_type="application/json"):
    flow.response = tutils.tresp(content=body, status_code=status)
    flow.response.headers.clear()
    flow.response.headers["content-type"] = content_type


# --- Record → Replay cycle ---


def test_record_then_replay_cycle(tmp_path):
    """Full cycle: record a request, then replay it from cache."""
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.RECORD))

    # Record
    flow = _make_flow("api.example.com", "/v1/users")
    addon.request(flow)
    _add_response(flow, b'[{"id":1,"name":"Alice"}]')
    addon.response(flow)
    assert addon.stats_recorded == 1

    # Switch to replay
    addon.mode = ProxyMode.REPLAY

    # Replay same request
    replay_flow = _make_flow("api.example.com", "/v1/users")
    addon.request(replay_flow)
    assert replay_flow.response is not None
    assert replay_flow.response.status_code == 200
    assert b"Alice" in replay_flow.response.content
    assert addon.stats_hits == 1


def test_record_then_replay_post_with_body(tmp_path):
    """Record and replay a POST with JSON body."""
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.RECORD))

    flow = _make_flow(
        "api.example.com",
        "/v1/users",
        method="POST",
        body=b'{"name":"Bob"}',
        headers={"content-type": "application/json"},
    )
    addon.request(flow)
    _add_response(flow, b'{"id":2,"name":"Bob"}', status=201)
    addon.response(flow)

    addon.mode = ProxyMode.REPLAY

    replay_flow = _make_flow(
        "api.example.com",
        "/v1/users",
        method="POST",
        body=b'{"name":"Bob"}',
        headers={"content-type": "application/json"},
    )
    addon.request(replay_flow)
    assert replay_flow.response.status_code == 201
    assert b"Bob" in replay_flow.response.content


def test_different_bodies_produce_different_cassettes(tmp_path):
    """Two POSTs with different bodies create separate cassettes."""
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.RECORD))

    for name in ["Alice", "Bob"]:
        flow = _make_flow(
            "api.example.com",
            "/v1/users",
            method="POST",
            body=f'{{"name":"{name}"}}'.encode(),
            headers={"content-type": "application/json"},
        )
        addon.request(flow)
        _add_response(flow, f'{{"id":1,"name":"{name}"}}'.encode(), status=201)
        addon.response(flow)

    assert addon.stats_recorded == 2
    cassette_dir = tmp_path / "cassettes" / "api.example.com"
    assert len(list(cassette_dir.glob("*.json"))) == 2


# --- Spy mode ---


def test_spy_miss_then_hit(tmp_path):
    """Spy mode: miss forwards upstream, hit returns cached."""
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.SPY))

    # First request — miss, passes through
    flow1 = _make_flow("api.example.com", "/v1/health")
    addon.request(flow1)
    assert flow1.response is None  # not short-circuited
    assert addon.stats_misses == 1

    # Simulate upstream response
    _add_response(flow1, b'{"status":"healthy"}')
    addon.response(flow1)
    assert addon.stats_recorded == 1

    # Second request — should hit cache
    flow2 = _make_flow("api.example.com", "/v1/health")
    addon.request(flow2)
    assert flow2.response is not None
    assert flow2.response.status_code == 200
    assert b"healthy" in flow2.response.content
    assert addon.stats_hits == 1


# --- Domain extraction ---


def test_domain_extracted_per_host(tmp_path):
    """Each host gets its own cassette directory."""
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.RECORD))

    for host in ["api.example.com", "auth.example.com"]:
        flow = _make_flow(host, "/health")
        addon.request(flow)
        _add_response(flow)
        addon.response(flow)

    cassettes_root = tmp_path / "cassettes"
    assert (cassettes_root / "api.example.com").exists()
    assert (cassettes_root / "auth.example.com").exists()


def test_query_params_included_in_matching(tmp_path):
    """Different query params produce different cassettes."""
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.RECORD))

    for page in ["1", "2"]:
        flow = _make_flow("api.example.com", "/v1/users", query=f"page={page}")
        addon.request(flow)
        _add_response(flow, f'{{"page":{page}}}'.encode())
        addon.response(flow)

    assert addon.stats_recorded == 2

    # Replay page=1
    addon.mode = ProxyMode.REPLAY
    flow = _make_flow("api.example.com", "/v1/users", query="page=1")
    addon.request(flow)
    assert flow.response is not None
    assert b'"page":1' in flow.response.content


# --- Admin API compatibility ---


async def test_admin_stats_with_addon(tmp_path):
    """Admin API works with VCRAddon handler."""
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.RECORD))

    # Generate some stats
    flow = _make_flow("api.example.com", "/test")
    addon.request(flow)
    _add_response(flow)
    addon.response(flow)

    app = create_admin_app(addon)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["total_requests"] == 1
        assert stats["recorded"] == 1


async def test_admin_mode_switch_with_addon(tmp_path):
    """Admin API can switch modes on VCRAddon."""
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.SPY))

    app = create_admin_app(addon)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/mode")
        assert resp.json()["mode"] == "spy"

        resp = await client.put("/api/mode", json={"mode": "replay"})
        assert resp.json()["mode"] == "replay"
        assert addon.mode == ProxyMode.REPLAY


async def test_admin_list_cassettes_with_addon(tmp_path):
    """Admin API lists cassettes recorded through VCRAddon."""
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.RECORD))

    flow = _make_flow("api.example.com", "/v1/users")
    addon.request(flow)
    _add_response(flow)
    addon.response(flow)

    app = create_admin_app(addon)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/cassettes")
        cassettes = resp.json()
        assert len(cassettes) == 1
        assert cassettes[0]["domain"] == "api.example.com"
