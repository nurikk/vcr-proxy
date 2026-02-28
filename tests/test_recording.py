from vcr_proxy.recording import (
    build_recorded_request,
    build_recorded_response_from_raw,
    is_text_content,
)


def test_is_text_content_json():
    assert is_text_content("application/json") is True


def test_is_text_content_text_html():
    assert is_text_content("text/html") is True


def test_is_text_content_binary():
    assert is_text_content("application/octet-stream") is False


def test_is_text_content_none():
    assert is_text_content(None) is True


def test_build_recorded_request_json_body():
    req = build_recorded_request(
        method="POST",
        path="/v1/users",
        query_string="page=1",
        headers={"Content-Type": "application/json"},
        body=b'{"name": "Alice"}',
    )
    assert req.method == "POST"
    assert req.path == "/v1/users"
    assert req.query == {"page": ["1"]}
    assert req.body == '{"name": "Alice"}'
    assert req.body_encoding == "utf-8"
    assert req.headers["content-type"] == "application/json"


def test_build_recorded_request_binary_body():
    req = build_recorded_request(
        method="PUT",
        path="/upload",
        query_string="",
        headers={"content-type": "application/octet-stream"},
        body=b"\x00\x01\x02",
    )
    assert req.body_encoding == "base64"
    assert req.body == "AAEC"  # base64 of \x00\x01\x02


def test_build_recorded_request_no_body():
    req = build_recorded_request(
        method="GET",
        path="/",
        query_string="",
        headers={},
        body=None,
    )
    assert req.body is None
    assert req.body_encoding == "utf-8"


def test_build_recorded_response_from_raw_json():
    resp = build_recorded_response_from_raw(
        status_code=200,
        headers={"content-type": "application/json"},
        body=b'{"ok": true}',
    )
    assert resp.status_code == 200
    assert resp.body == '{"ok": true}'
    assert resp.body_encoding == "utf-8"


def test_build_recorded_response_from_raw_binary():
    resp = build_recorded_response_from_raw(
        status_code=200,
        headers={"content-type": "image/png"},
        body=b"\x89PNG",
    )
    assert resp.body_encoding == "base64"


def test_build_recorded_response_from_raw_no_body():
    resp = build_recorded_response_from_raw(
        status_code=204,
        headers={},
        body=None,
    )
    assert resp.body is None
