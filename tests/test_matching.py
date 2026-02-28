# tests/test_matching.py
import json

from vcr_proxy.matching import _normalize_body, compute_hash, compute_matching_key
from vcr_proxy.models import RecordedRequest


def _make_request(**overrides) -> RecordedRequest:
    defaults = {
        "method": "GET",
        "path": "/api/v1/users",
        "query": {},
        "headers": {"accept": "application/json"},
    }
    defaults.update(overrides)
    return RecordedRequest(**defaults)


def test_method_normalized_to_uppercase():
    key = compute_matching_key(_make_request(method="get"))
    assert key.method == "GET"


def test_path_normalized_lowercase_no_trailing_slash():
    key = compute_matching_key(_make_request(path="/API/V1/Users/"))
    assert key.path == "/api/v1/users"


def test_query_sorted_by_key():
    req = _make_request(query={"z": ["1"], "a": ["2"]})
    key = compute_matching_key(req)
    assert key.query is not None
    assert key.query.index("a") < key.query.index("z")


def test_json_body_key_order_ignored():
    req_a = _make_request(
        method="POST",
        body='{"name": "Alice", "role": "admin"}',
        content_type="application/json",
        headers={"content-type": "application/json"},
    )
    req_b = _make_request(
        method="POST",
        body='{"role": "admin", "name": "Alice"}',
        content_type="application/json",
        headers={"content-type": "application/json"},
    )
    key_a = compute_matching_key(req_a)
    key_b = compute_matching_key(req_b)
    assert key_a == key_b


def test_different_json_body_different_key():
    req_a = _make_request(
        method="POST",
        body='{"name": "Alice"}',
        content_type="application/json",
        headers={"content-type": "application/json"},
    )
    req_b = _make_request(
        method="POST",
        body='{"name": "Bob"}',
        content_type="application/json",
        headers={"content-type": "application/json"},
    )
    key_a = compute_matching_key(req_a)
    key_b = compute_matching_key(req_b)
    assert key_a != key_b


def test_headers_sorted_lowercase_keys():
    req = _make_request(
        headers={"Content-Type": "application/json", "Accept": "text/html"},
    )
    key = compute_matching_key(req)
    assert key.headers is not None
    assert key.headers.index("accept") < key.headers.index("content-type")


def test_ignored_headers_excluded():
    from vcr_proxy.config import ALWAYS_IGNORED_HEADERS_DEFAULT

    req = _make_request(
        headers={"accept": "application/json", "date": "Mon, 01 Jan 2025 00:00:00 GMT"},
    )
    key = compute_matching_key(req, ignore_headers=ALWAYS_IGNORED_HEADERS_DEFAULT)
    assert key.headers is not None
    assert "date" not in key.headers


def test_form_body_sorted():
    req = _make_request(
        method="POST",
        body="z=1&a=2",
        content_type="application/x-www-form-urlencoded",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    key = compute_matching_key(req)
    assert key.body is not None
    assert key.body.index("a") < key.body.index("z")


def test_hash_deterministic():
    req = _make_request()
    key = compute_matching_key(req)
    hash_a = compute_hash(key)
    hash_b = compute_hash(key)
    assert hash_a == hash_b
    assert len(hash_a) == 8  # short hash for filenames


def test_hash_different_for_different_keys():
    key_a = compute_matching_key(_make_request(path="/a"))
    key_b = compute_matching_key(_make_request(path="/b"))
    assert compute_hash(key_a) != compute_hash(key_b)


def test_normalize_body_ignores_fields():
    """body_fields strips top-level JSON keys before normalization."""
    body = '{"login":"admin","password":"secret","action":"search"}'
    result = _normalize_body(body, "application/json", ignore_body_fields=["login", "password"])
    parsed = json.loads(result)
    assert "login" not in parsed
    assert "password" not in parsed
    assert parsed["action"] == "search"


def test_normalize_body_ignore_empty_list():
    """Empty ignore list doesn't change behavior."""
    body = '{"a":1}'
    assert _normalize_body(body, "application/json", ignore_body_fields=[]) == _normalize_body(
        body, "application/json"
    )


def test_normalize_body_ignore_nonexistent_field():
    """Ignoring a field that doesn't exist is a no-op."""
    body = '{"a":1}'
    result = _normalize_body(body, "application/json", ignore_body_fields=["zzz"])
    assert json.loads(result) == {"a": 1}


def test_normalize_body_ignore_non_json():
    """body_fields ignore is a no-op for non-JSON content."""
    body = "key=val"
    result = _normalize_body(body, "application/x-www-form-urlencoded", ignore_body_fields=["key"])
    assert result == "key=val"


def test_sensitive_headers_excluded_from_matching():
    """Requests with different Authorization values produce the same matching key
    when authorization is in the ignore_headers set (as sensitive_headers would be)."""
    from vcr_proxy.config import SENSITIVE_HEADERS_DEFAULT

    req_a = _make_request(
        headers={"accept": "application/json", "authorization": "Bearer token-A"},
    )
    req_b = _make_request(
        headers={"accept": "application/json", "authorization": "Bearer token-B"},
    )
    key_a = compute_matching_key(req_a, ignore_headers=SENSITIVE_HEADERS_DEFAULT)
    key_b = compute_matching_key(req_b, ignore_headers=SENSITIVE_HEADERS_DEFAULT)
    assert key_a == key_b


def test_sensitive_headers_not_in_matching_key_headers():
    """Sensitive headers should not appear in the matching key headers string."""
    from vcr_proxy.config import SENSITIVE_HEADERS_DEFAULT

    req = _make_request(
        headers={
            "accept": "application/json",
            "authorization": "Bearer secret",
            "x-api-key": "my-key",
        },
    )
    key = compute_matching_key(req, ignore_headers=SENSITIVE_HEADERS_DEFAULT)
    assert key.headers is not None
    assert "authorization" not in key.headers
    assert "x-api-key" not in key.headers
    assert "accept" in key.headers
