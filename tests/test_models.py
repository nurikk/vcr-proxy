# tests/test_models.py
import json
from datetime import UTC, datetime

from vcr_proxy.models import (
    Cassette,
    CassetteMeta,
    MatchingKey,
    RecordedRequest,
    RecordedResponse,
)


def test_recorded_request_defaults():
    req = RecordedRequest(
        method="GET",
        path="/api/v1/users",
        query={},
        headers={"accept": "application/json"},
    )
    assert req.body is None
    assert req.body_encoding == "utf-8"
    assert req.content_type is None


def test_recorded_request_with_body():
    req = RecordedRequest(
        method="POST",
        path="/api/v1/users",
        query={"page": ["1"]},
        headers={"content-type": "application/json"},
        body='{"name": "Alice"}',
        body_encoding="utf-8",
        content_type="application/json",
    )
    assert req.method == "POST"
    assert req.query == {"page": ["1"]}


def test_recorded_response_serialization():
    resp = RecordedResponse(
        status_code=201,
        headers={"content-type": "application/json"},
        body='{"id": 1}',
    )
    data = json.loads(resp.model_dump_json())
    assert data["status_code"] == 201
    assert data["body_encoding"] == "utf-8"


def test_cassette_round_trip():
    cassette = Cassette(
        meta=CassetteMeta(
            recorded_at=datetime(2025, 1, 1, tzinfo=UTC),
            target="https://api.example.com",
            domain="api.example.com",
            vcr_proxy_version="1.0.0",
        ),
        request=RecordedRequest(
            method="GET",
            path="/api/v1/users",
            query={},
            headers={"accept": "application/json"},
        ),
        response=RecordedResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            body='[{"id": 1}]',
        ),
    )
    json_str = cassette.model_dump_json(indent=2)
    restored = Cassette.model_validate_json(json_str)
    assert restored == cassette


def test_matching_key_equality():
    key_a = MatchingKey(method="GET", path="/api/v1/users")
    key_b = MatchingKey(method="GET", path="/api/v1/users")
    assert key_a == key_b


def test_matching_key_inequality():
    key_a = MatchingKey(method="GET", path="/api/v1/users")
    key_b = MatchingKey(method="POST", path="/api/v1/users")
    assert key_a != key_b
