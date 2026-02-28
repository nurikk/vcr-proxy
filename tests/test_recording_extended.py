# tests/test_recording_extended.py
"""Extended tests for recording.py: edge cases for build functions."""

from vcr_proxy.recording import (
    build_recorded_request,
    build_recorded_response_from_raw,
    is_text_content,
)


def test_is_text_content_xml():
    assert is_text_content("application/xml") is True


def test_is_text_content_form():
    assert is_text_content("application/x-www-form-urlencoded") is True


def test_is_text_content_text_plain():
    assert is_text_content("text/plain") is True


def test_is_text_content_image():
    assert is_text_content("image/png") is False


def test_build_recorded_request_headers_lowercased():
    req = build_recorded_request(
        method="GET",
        path="/test",
        query_string="",
        headers={"Content-Type": "application/json", "Accept": "text/html"},
        body=None,
    )
    assert "content-type" in req.headers
    assert "accept" in req.headers


def test_build_recorded_request_query_parsed():
    req = build_recorded_request(
        method="GET",
        path="/test",
        query_string="a=1&b=2",
        headers={},
        body=None,
    )
    assert req.query == {"a": ["1"], "b": ["2"]}


def test_build_recorded_request_empty_query():
    req = build_recorded_request(
        method="GET",
        path="/test",
        query_string="",
        headers={},
        body=None,
    )
    assert req.query == {}


def test_build_recorded_request_method_uppercased():
    req = build_recorded_request(
        method="post",
        path="/test",
        query_string="",
        headers={},
        body=b"data",
    )
    assert req.method == "POST"


def test_build_recorded_response_from_raw_headers_preserved():
    resp = build_recorded_response_from_raw(
        status_code=200,
        headers={"content-type": "application/json", "x-custom": "value"},
        body=b'{"ok": true}',
    )
    assert resp.headers["x-custom"] == "value"
