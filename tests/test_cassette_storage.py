# tests/test_cassette_storage.py
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vcr_proxy.models import (
    Cassette,
    CassetteMeta,
    MatchingKey,
    RecordedRequest,
    RecordedResponse,
)
from vcr_proxy.storage import CassetteStorage


@pytest.fixture
def storage(tmp_path: Path) -> CassetteStorage:
    return CassetteStorage(cassettes_dir=tmp_path)


@pytest.fixture
def sample_cassette() -> Cassette:
    return Cassette(
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


def test_save_creates_domain_directory(
    storage: CassetteStorage, sample_cassette: Cassette
):
    key = MatchingKey(method="GET", path="/api/v1/users")
    storage.save(cassette=sample_cassette, matching_key=key)

    domain_dir = storage.cassettes_dir / "api.example.com"
    assert domain_dir.is_dir()
    assert len(list(domain_dir.glob("*.json"))) == 1


def test_save_and_lookup_round_trip(
    storage: CassetteStorage, sample_cassette: Cassette
):
    key = MatchingKey(method="GET", path="/api/v1/users")
    storage.save(cassette=sample_cassette, matching_key=key)

    found = storage.lookup(domain="api.example.com", matching_key=key)
    assert found is not None
    assert found.response.status_code == 200


def test_lookup_returns_none_on_miss(storage: CassetteStorage):
    key = MatchingKey(method="GET", path="/nonexistent")
    found = storage.lookup(domain="api.example.com", matching_key=key)
    assert found is None


def test_filename_format(storage: CassetteStorage, sample_cassette: Cassette):
    key = MatchingKey(method="POST", path="/api/v1/users")
    storage.save(cassette=sample_cassette, matching_key=key)

    domain_dir = storage.cassettes_dir / "api.example.com"
    files = list(domain_dir.glob("*.json"))
    assert len(files) == 1
    assert files[0].name.startswith("POST_")


def test_list_cassettes_for_domain(
    storage: CassetteStorage, sample_cassette: Cassette
):
    key = MatchingKey(method="GET", path="/api/v1/users")
    storage.save(cassette=sample_cassette, matching_key=key)

    cassettes = storage.list_cassettes(domain="api.example.com")
    assert len(cassettes) == 1


def test_list_all_cassettes(storage: CassetteStorage, sample_cassette: Cassette):
    key = MatchingKey(method="GET", path="/api/v1/users")
    storage.save(cassette=sample_cassette, matching_key=key)

    all_cassettes = storage.list_all()
    assert len(all_cassettes) == 1


def test_delete_cassette(storage: CassetteStorage, sample_cassette: Cassette):
    key = MatchingKey(method="GET", path="/api/v1/users")
    storage.save(cassette=sample_cassette, matching_key=key)

    cassettes = storage.list_cassettes(domain="api.example.com")
    assert len(cassettes) == 1

    storage.delete(domain="api.example.com", cassette_id=cassettes[0].stem)
    assert storage.list_cassettes(domain="api.example.com") == []
