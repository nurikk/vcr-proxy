# tests/test_route_config.py
from pathlib import Path

import pytest
import yaml

from vcr_proxy.models import RecordedRequest
from vcr_proxy.route_config import RouteConfigManager


@pytest.fixture
def manager(tmp_path: Path) -> RouteConfigManager:
    return RouteConfigManager(cassettes_dir=tmp_path)


def test_auto_generate_creates_yaml(manager: RouteConfigManager):
    request = RecordedRequest(
        method="POST",
        path="/api/v1/events",
        query={"page": ["1"]},
        headers={
            "content-type": "application/json",
            "accept": "application/json",
            "authorization": "Bearer token",
        },
        body='{"action": "click", "user_id": "123"}',
        content_type="application/json",
    )
    manager.auto_generate(domain="api.example.com", request=request)

    config_path = manager._config_path("api.example.com", "POST", "/api/v1/events")
    assert config_path.exists()


def test_auto_generate_content(manager: RouteConfigManager):
    request = RecordedRequest(
        method="POST",
        path="/api/v1/events",
        query={},
        headers={"content-type": "application/json"},
        body='{"action": "click", "user_id": "123"}',
        content_type="application/json",
    )
    manager.auto_generate(domain="api.example.com", request=request)

    override = manager.load(domain="api.example.com", method="POST", path="/api/v1/events")
    assert override is not None
    assert override.route.method == "POST"
    assert override.route.path == "/api/v1/events"
    assert "action" in override.matched.body_fields
    assert "user_id" in override.matched.body_fields


def test_auto_generate_does_not_overwrite(manager: RouteConfigManager):
    request = RecordedRequest(
        method="POST",
        path="/api/v1/events",
        query={},
        headers={"content-type": "application/json"},
        body='{"action": "click"}',
        content_type="application/json",
    )
    manager.auto_generate(domain="api.example.com", request=request)

    # Second call with different body field should NOT overwrite ignore config
    request2 = RecordedRequest(
        method="POST",
        path="/api/v1/events",
        query={},
        headers={"content-type": "application/json"},
        body='{"action": "click", "new_field": "value"}',
        content_type="application/json",
    )
    manager.auto_generate(domain="api.example.com", request=request2)

    override = manager.load(domain="api.example.com", method="POST", path="/api/v1/events")
    assert override is not None
    assert "new_field" in override.matched.body_fields


def test_load_returns_none_when_no_config(manager: RouteConfigManager):
    result = manager.load(domain="api.example.com", method="GET", path="/nonexistent")
    assert result is None


def test_load_with_ignore_config(manager: RouteConfigManager):
    request = RecordedRequest(
        method="POST",
        path="/api/v1/events",
        query={},
        headers={"content-type": "application/json"},
        body='{"action": "click", "request_id": "abc"}',
        content_type="application/json",
    )
    manager.auto_generate(domain="api.example.com", request=request)

    # Manually edit the config to add ignore rules
    config_path = manager._config_path("api.example.com", "POST", "/api/v1/events")
    data = yaml.safe_load(config_path.read_text())
    data["ignore"]["body_fields"] = ["$.request_id"]
    config_path.write_text(yaml.dump(data, default_flow_style=False))

    override = manager.load(domain="api.example.com", method="POST", path="/api/v1/events")
    assert override is not None
    assert "$.request_id" in override.ignore.body_fields
