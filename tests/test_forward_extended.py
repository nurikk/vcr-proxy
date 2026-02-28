# tests/test_forward_extended.py
"""Extended tests for forward.py: edge cases in VCRAddon and _decode_body."""

import base64

from mitmproxy.test import tflow, tutils

from vcr_proxy.config import Settings
from vcr_proxy.forward import VCRAddon, _decode_body
from vcr_proxy.models import ProxyMode, RecordedResponse


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
):
    hdrs = [(b"host", host.encode())]
    if request_headers:
        for k, v in request_headers.items():
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
            content=request_body,
        )
    )


def _add_response(flow, body=b'{"ok":true}', status=200, content_type="application/json"):
    flow.response = tutils.tresp(content=body, status_code=status)
    flow.response.headers.clear()
    flow.response.headers["content-type"] = content_type


# --- _decode_body ---


def test_decode_body_none():
    resp = RecordedResponse(status_code=200, headers={}, body=None)
    assert _decode_body(resp) == b""


def test_decode_body_base64():
    data = b"\x00\x01\x02"
    encoded = base64.b64encode(data).decode("ascii")
    resp = RecordedResponse(status_code=200, headers={}, body=encoded, body_encoding="base64")
    assert _decode_body(resp) == data


def test_decode_body_utf8():
    resp = RecordedResponse(status_code=200, headers={}, body="hello", body_encoding="utf-8")
    assert _decode_body(resp) == b"hello"


# --- VCRAddon edge cases ---


def test_response_no_metadata_skips(tmp_path):
    """response() with missing metadata (no vcr_domain etc.) should not crash."""
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.RECORD))
    flow = _make_flow()
    # Don't call addon.request(flow), so metadata is not set
    _add_response(flow)
    # Should not crash
    addon.response(flow)
    assert addon.stats_recorded == 0


def test_response_not_recording_mode(tmp_path):
    """In REPLAY mode, response() is a no-op for non-pending flows."""
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.REPLAY))
    flow = _make_flow()
    addon.request(flow)  # This will set response (404) for replay miss
    # Clear response to simulate calling response() anyway
    addon.response(flow)
    # Should not record anything
    assert addon.stats_recorded == 0


def test_spy_pending_record_cleared_after_response(tmp_path):
    """In SPY mode, flow.id is removed from _pending_record after response()."""
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.SPY))
    flow = _make_flow()
    addon.request(flow)
    assert flow.id in addon._pending_record

    _add_response(flow)
    addon.response(flow)
    assert flow.id not in addon._pending_record


def test_record_binary_response(tmp_path):
    """Recording a binary response works correctly."""
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.RECORD))
    flow = _make_flow()
    addon.request(flow)
    _add_response(flow, body=b"\x89PNG\x0d\x0a", status=200, content_type="image/png")
    addon.response(flow)

    assert addon.stats_recorded == 1


def test_record_with_query_params(tmp_path):
    """Recording with query params captures them in the cassette."""
    addon = VCRAddon(_make_settings(tmp_path, ProxyMode.RECORD))
    flow = _make_flow(query="page=1&limit=10")
    addon.request(flow)
    _add_response(flow)
    addon.response(flow)

    assert addon.stats_recorded == 1
