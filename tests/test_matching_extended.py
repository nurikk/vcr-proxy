# tests/test_matching_extended.py
"""Extended tests for matching.py: normalize functions, edge cases."""

from vcr_proxy.matching import (
    _normalize_body,
    _normalize_form_body,
    _normalize_headers,
    _normalize_json_body,
    _normalize_query,
    compute_hash,
    compute_matching_key,
)
from vcr_proxy.models import MatchingKey, RecordedRequest, RouteIgnoreConfig

# --- _normalize_json_body ---


def test_normalize_json_body_sorts_keys():
    result = _normalize_json_body('{"z": 1, "a": 2}')
    assert result == '{"a":2,"z":1}'


def test_normalize_json_body_compact():
    result = _normalize_json_body('{ "name" : "Alice" }')
    assert result == '{"name":"Alice"}'


# --- _normalize_form_body ---


def test_normalize_form_body_sorts_keys():
    result = _normalize_form_body("z=1&a=2")
    assert result.index("a") < result.index("z")


def test_normalize_form_body_preserves_values():
    result = _normalize_form_body("name=Alice")
    assert "name=Alice" in result


# --- _normalize_query ---


def test_normalize_query_empty():
    result = _normalize_query({})
    assert result is None


def test_normalize_query_sorts():
    result = _normalize_query({"z": ["1"], "a": ["2"]})
    assert result is not None
    assert result.index("a") < result.index("z")


def test_normalize_query_multi_values_sorted():
    result = _normalize_query({"key": ["b", "a", "c"]})
    assert result is not None
    # Values should be sorted within each key
    assert "a" in result


# --- _normalize_headers ---


def test_normalize_headers_empty_after_filter():
    result = _normalize_headers(
        {"date": "Mon, 01 Jan 2025"},
        ignore_headers=frozenset({"date"}),
    )
    assert result is None


def test_normalize_headers_lowercase():
    result = _normalize_headers({"Accept": "text/html"})
    assert result is not None
    assert "accept" in result


def test_normalize_headers_sorted():
    result = _normalize_headers({"z-header": "1", "a-header": "2"})
    assert result is not None
    assert result.index("a-header") < result.index("z-header")


def test_normalize_headers_route_ignore():
    result = _normalize_headers(
        {"accept": "text/html", "authorization": "Bearer token"},
        route_ignore=["authorization"],
    )
    assert result is not None
    assert "authorization" not in result
    assert "accept" in result


def test_normalize_headers_both_ignore_sources():
    result = _normalize_headers(
        {"accept": "text/html", "date": "Mon", "x-custom": "val"},
        ignore_headers=frozenset({"date"}),
        route_ignore=["x-custom"],
    )
    assert result is not None
    assert "date" not in result
    assert "x-custom" not in result
    assert "accept" in result


# --- _normalize_body ---


def test_normalize_body_none():
    result = _normalize_body(None, "application/json")
    assert result is None


def test_normalize_body_json():
    result = _normalize_body('{"z": 1, "a": 2}', "application/json")
    assert result == '{"a":2,"z":1}'


def test_normalize_body_json_invalid():
    result = _normalize_body("not json", "application/json")
    assert result == "not json"


def test_normalize_body_form():
    result = _normalize_body("z=1&a=2", "application/x-www-form-urlencoded")
    assert result.index("a") < result.index("z")


def test_normalize_body_plain_text():
    result = _normalize_body("plain text body", "text/plain")
    assert result == "plain text body"


def test_normalize_body_no_content_type():
    result = _normalize_body("some body", None)
    assert result == "some body"


def test_normalize_body_json_with_ignore_fields():
    body = '{"login":"admin","password":"secret","action":"search"}'
    result = _normalize_body(body, "application/json", ignore_body_fields=["login", "password"])
    assert "login" not in result
    assert "password" not in result


# --- compute_matching_key ---


def test_compute_matching_key_with_route_ignore():
    req = RecordedRequest(
        method="GET",
        path="/api/v1/users",
        query={"page": ["1"], "token": ["abc"]},
        headers={"accept": "application/json", "authorization": "Bearer xyz"},
    )
    route_ignore = RouteIgnoreConfig(
        headers=["authorization"],
        query_params=["token"],
    )
    key = compute_matching_key(req, route_ignore=route_ignore)
    assert key.headers is not None
    assert "authorization" not in key.headers
    assert key.query is not None
    assert "token" not in key.query


def test_compute_matching_key_path_root():
    req = RecordedRequest(
        method="GET",
        path="/",
        query={},
        headers={},
    )
    key = compute_matching_key(req)
    assert key.path == "/"


# --- compute_hash ---


def test_compute_hash_length():
    key = MatchingKey(method="GET", path="/test")
    h = compute_hash(key)
    assert len(h) == 8


def test_compute_hash_hex_string():
    key = MatchingKey(method="GET", path="/test")
    h = compute_hash(key)
    int(h, 16)  # Should not raise — valid hex
