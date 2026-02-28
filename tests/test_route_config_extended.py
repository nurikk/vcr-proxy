# tests/test_route_config_extended.py
"""Extended tests for route_config.py: form body extraction, config path, edge cases."""

from pathlib import Path

import pytest

from vcr_proxy.models import RecordedRequest
from vcr_proxy.route_config import RouteConfigManager, _extract_body_fields

# --- _extract_body_fields ---


def test_extract_body_fields_json():
    result = _extract_body_fields('{"name": "Alice", "role": "admin"}', "application/json")
    assert result == ["name", "role"]


def test_extract_body_fields_json_sorted():
    result = _extract_body_fields('{"z": 1, "a": 2, "m": 3}', "application/json")
    assert result == ["a", "m", "z"]


def test_extract_body_fields_json_array():
    """JSON arrays don't have top-level field names."""
    result = _extract_body_fields("[1, 2, 3]", "application/json")
    assert result == []


def test_extract_body_fields_json_invalid():
    """Invalid JSON returns empty list."""
    result = _extract_body_fields("not json", "application/json")
    assert result == []


def test_extract_body_fields_form():
    result = _extract_body_fields("name=Alice&role=admin", "application/x-www-form-urlencoded")
    assert result == ["name", "role"]


def test_extract_body_fields_form_sorted():
    result = _extract_body_fields("z=1&a=2", "application/x-www-form-urlencoded")
    assert result == ["a", "z"]


def test_extract_body_fields_none_body():
    result = _extract_body_fields(None, "application/json")
    assert result == []


def test_extract_body_fields_none_content_type():
    result = _extract_body_fields("some body", None)
    assert result == []


def test_extract_body_fields_unknown_content_type():
    result = _extract_body_fields("some body", "text/plain")
    assert result == []


# --- RouteConfigManager ---


@pytest.fixture
def manager(tmp_path: Path) -> RouteConfigManager:
    return RouteConfigManager(cassettes_dir=tmp_path)


def test_config_path_format(manager: RouteConfigManager):
    path = manager._config_path("example.com", "GET", "/api/v1/users")
    assert path.name == "GET_api_v1_users.yaml"
    assert "example.com" in str(path)


def test_config_path_root(manager: RouteConfigManager):
    path = manager._config_path("example.com", "GET", "/")
    assert path.name == "GET_root.yaml"


def test_auto_generate_with_form_body(manager: RouteConfigManager):
    request = RecordedRequest(
        method="POST",
        path="/login",
        query={},
        headers={"content-type": "application/x-www-form-urlencoded"},
        body="username=admin&password=secret",
        content_type="application/x-www-form-urlencoded",
    )
    manager.auto_generate(domain="example.com", request=request)
    override = manager.load("example.com", "POST", "/login")
    assert override is not None
    assert "password" in override.matched.body_fields
    assert "username" in override.matched.body_fields


def test_auto_generate_with_query_params(manager: RouteConfigManager):
    request = RecordedRequest(
        method="GET",
        path="/search",
        query={"q": ["test"], "page": ["1"]},
        headers={"accept": "application/json"},
    )
    manager.auto_generate(domain="example.com", request=request)
    override = manager.load("example.com", "GET", "/search")
    assert override is not None
    assert "page" in override.matched.query_params
    assert "q" in override.matched.query_params


def test_auto_generate_updates_existing_merges_fields(manager: RouteConfigManager):
    """When an existing config exists, auto_generate merges new fields."""
    req1 = RecordedRequest(
        method="POST",
        path="/api/events",
        query={"source": ["web"]},
        headers={"content-type": "application/json", "accept": "application/json"},
        body='{"action": "click"}',
        content_type="application/json",
    )
    manager.auto_generate(domain="example.com", request=req1)

    req2 = RecordedRequest(
        method="POST",
        path="/api/events",
        query={"source": ["web"], "extra": ["yes"]},
        headers={
            "content-type": "application/json",
            "accept": "application/json",
            "x-custom": "value",
        },
        body='{"action": "click", "user_id": "123"}',
        content_type="application/json",
    )
    manager.auto_generate(domain="example.com", request=req2)

    override = manager.load("example.com", "POST", "/api/events")
    assert override is not None
    assert "user_id" in override.matched.body_fields
    assert "action" in override.matched.body_fields
    assert "extra" in override.matched.query_params
    assert "source" in override.matched.query_params
    assert "x-custom" in override.matched.headers


def test_load_returns_none_nonexistent(manager: RouteConfigManager):
    result = manager.load("example.com", "GET", "/nonexistent")
    assert result is None
