"""Tests for the VCR forward proxy addon."""

from mitmproxy.test import tflow, tutils

from vcr_proxy.config import Settings
from vcr_proxy.forward import VCRAddon
from vcr_proxy.models import ProxyMode


def _make_settings(tmp_path, mode=ProxyMode.RECORD):
    return Settings(
        mode=mode,
        cassettes_dir=tmp_path / "cassettes",
    )


def _make_flow(
    method="GET",
    host="api.example.com",
    path="/v1/users",
    query="",
    request_body=b"",
    request_headers=None,
    response_status=200,
    response_body=b'{"ok":true}',
    response_headers=None,
    with_response=False,
):
    """Create a mitmproxy flow for testing."""
    hdrs = [(b"host", host.encode())]
    if request_headers:
        for k, v in request_headers.items():
            hdrs.append((k.encode(), v.encode()))

    full_path = f"{path}?{query}" if query else path

    f = tflow.tflow(
        req=tutils.treq(
            method=method.encode(),
            host=host,
            port=443,
            scheme=b"https",
            authority=host.encode(),
            path=full_path.encode(),
            headers=hdrs,
            content=request_body,
        )
    )

    if with_response:
        resp_hdrs = response_headers or {"content-type": "application/json"}
        f.response = tutils.tresp(content=response_body, status_code=response_status)
        f.response.headers.clear()
        for k, v in resp_hdrs.items():
            f.response.headers[k] = v

    return f


# --- Record mode ---


def test_record_request_passes_through(tmp_path):
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.RECORD))
    flow = _make_flow()
    addon.request(flow)

    # In record mode, request() should NOT set flow.response (let it pass through)
    assert flow.response is None
    assert flow.metadata["vcr_domain"] == "api.example.com"
    assert addon.stats_total == 1


def test_record_response_saves_cassette(tmp_path):
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.RECORD))
    flow = _make_flow()
    addon.request(flow)

    # Simulate mitmproxy calling response() after upstream responds
    flow.response = tutils.tresp(content=b'{"users":[]}', status_code=200)
    flow.response.headers.clear()
    flow.response.headers["content-type"] = "application/json"
    addon.response(flow)

    assert addon.stats_recorded == 1
    cassette_dir = tmp_path / "cassettes" / "api.example.com"
    cassettes = list(cassette_dir.glob("*.json"))
    assert len(cassettes) == 1


def test_record_extracts_domain_from_url(tmp_path):
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.RECORD))
    flow = _make_flow(host="other-api.io", path="/health")
    addon.request(flow)

    assert flow.metadata["vcr_domain"] == "other-api.io"


# --- Replay mode ---


def test_replay_hit_returns_cached(tmp_path):
    # First record a cassette
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.RECORD))
    flow = _make_flow()
    addon.request(flow)
    flow.response = tutils.tresp(content=b'{"users":[]}', status_code=200)
    flow.response.headers.clear()
    flow.response.headers["content-type"] = "application/json"
    addon.response(flow)

    # Now switch to replay
    addon.mode = ProxyMode.REPLAY
    replay_flow = _make_flow()
    addon.request(replay_flow)

    assert replay_flow.response is not None
    assert replay_flow.response.status_code == 200
    assert b"users" in replay_flow.response.content
    assert addon.stats_hits == 1


def test_replay_miss_returns_404(tmp_path):
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.REPLAY))
    flow = _make_flow()
    addon.request(flow)

    assert flow.response is not None
    assert flow.response.status_code == 404
    assert addon.stats_misses == 1


# --- Spy mode ---


def test_spy_hit_returns_cached(tmp_path):
    # Record first
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.RECORD))
    flow = _make_flow()
    addon.request(flow)
    flow.response = tutils.tresp(content=b'{"cached":true}', status_code=200)
    flow.response.headers.clear()
    flow.response.headers["content-type"] = "application/json"
    addon.response(flow)

    # Switch to spy
    addon.mode = ProxyMode.SPY
    spy_flow = _make_flow()
    addon.request(spy_flow)

    assert spy_flow.response is not None
    assert spy_flow.response.status_code == 200
    assert addon.stats_hits == 1


def test_spy_miss_passes_through(tmp_path):
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.SPY))
    flow = _make_flow()
    addon.request(flow)

    # Miss should NOT set response (let request go upstream)
    assert flow.response is None
    assert addon.stats_misses == 1
    assert flow.id in addon._pending_record


def test_spy_miss_then_response_records(tmp_path):
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.SPY))
    flow = _make_flow()
    addon.request(flow)

    # Simulate upstream response
    flow.response = tutils.tresp(content=b'{"new":true}', status_code=201)
    flow.response.headers.clear()
    flow.response.headers["content-type"] = "application/json"
    addon.response(flow)

    assert addon.stats_recorded == 1
    assert flow.id not in addon._pending_record


# --- Stats ---


def test_stats_accumulate(tmp_path):
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.REPLAY))

    for _ in range(3):
        flow = _make_flow()
        addon.request(flow)

    assert addon.stats_total == 3
    assert addon.stats_misses == 3


# --- Route config ---


def test_route_config_generated_on_record(tmp_path):
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.RECORD))
    flow = _make_flow(
        method="POST",
        request_headers={"content-type": "application/json"},
        request_body=b'{"name":"Alice"}',
    )
    addon.request(flow)

    flow.response = tutils.tresp(content=b'{"id":1}', status_code=201)
    flow.response.headers.clear()
    flow.response.headers["content-type"] = "application/json"
    addon.response(flow)

    routes_dir = tmp_path / "cassettes" / "_routes" / "api.example.com"
    assert routes_dir.exists()
    route_files = list(routes_dir.glob("*.yaml"))
    assert len(route_files) == 1
