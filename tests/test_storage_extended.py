# tests/test_storage_extended.py
"""Extended tests for storage.py: cover delete methods, edge cases, and list operations."""

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
from vcr_proxy.storage import CassetteStorage, _path_to_slug


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


# --- _path_to_slug ---


def test_path_to_slug_normal():
    assert _path_to_slug("/api/v1/users") == "api_v1_users"


def test_path_to_slug_root():
    assert _path_to_slug("/") == "root"


def test_path_to_slug_empty():
    assert _path_to_slug("") == "root"


def test_path_to_slug_special_chars():
    result = _path_to_slug("/api/v1/users?page=1")
    assert "?" not in result
    assert result == "api_v1_users_page_1"


# --- CassetteStorage methods ---


def test_domain_dir(storage: CassetteStorage):
    result = storage._domain_dir("api.example.com")
    assert result == storage.cassettes_dir / "api.example.com"


def test_cassette_filename(storage: CassetteStorage):
    key = MatchingKey(method="GET", path="/api/v1/users")
    filename = storage._cassette_filename(key)
    assert filename.startswith("GET_")
    assert filename.endswith(".json")


def test_lookup_no_domain_dir(storage: CassetteStorage):
    """Lookup returns None when domain dir doesn't exist."""
    key = MatchingKey(method="GET", path="/api/v1/users")
    result = storage.lookup(domain="nonexistent.com", matching_key=key)
    assert result is None


def test_lookup_no_file(storage: CassetteStorage, sample_cassette: Cassette):
    """Lookup returns None when cassette file doesn't exist."""
    domain_dir = storage._domain_dir("api.example.com")
    domain_dir.mkdir(parents=True, exist_ok=True)
    key = MatchingKey(method="GET", path="/nonexistent")
    result = storage.lookup(domain="api.example.com", matching_key=key)
    assert result is None


def test_list_cassettes_empty_domain(storage: CassetteStorage):
    """list_cassettes returns empty list for nonexistent domain."""
    result = storage.list_cassettes(domain="nonexistent.com")
    assert result == []


def test_list_all_no_dir(tmp_path: Path):
    """list_all returns empty when cassettes_dir doesn't exist."""
    storage = CassetteStorage(cassettes_dir=tmp_path / "nonexistent")
    result = storage.list_all()
    assert result == []


def test_delete_returns_false_nonexistent(storage: CassetteStorage):
    """delete returns False when cassette doesn't exist."""
    result = storage.delete(domain="api.example.com", cassette_id="nonexistent")
    assert result is False


def test_delete_returns_true(storage: CassetteStorage, sample_cassette: Cassette):
    """delete returns True and removes file."""
    key = MatchingKey(method="GET", path="/api/v1/users")
    storage.save(cassette=sample_cassette, matching_key=key)

    cassettes = storage.list_cassettes(domain="api.example.com")
    assert len(cassettes) == 1

    result = storage.delete(domain="api.example.com", cassette_id=cassettes[0].stem)
    assert result is True
    assert storage.list_cassettes(domain="api.example.com") == []


def test_delete_domain_nonexistent(storage: CassetteStorage):
    """delete_domain returns 0 for nonexistent domain."""
    result = storage.delete_domain(domain="nonexistent.com")
    assert result == 0


def test_delete_domain_with_cassettes(storage: CassetteStorage, sample_cassette: Cassette):
    """delete_domain removes all cassettes for a domain."""
    key1 = MatchingKey(method="GET", path="/api/v1/users")
    key2 = MatchingKey(method="POST", path="/api/v1/users")
    storage.save(cassette=sample_cassette, matching_key=key1)
    storage.save(cassette=sample_cassette, matching_key=key2)

    assert len(storage.list_cassettes(domain="api.example.com")) == 2
    result = storage.delete_domain(domain="api.example.com")
    assert result == 2
    assert storage.list_cassettes(domain="api.example.com") == []


def test_delete_all_empty(storage: CassetteStorage):
    """delete_all returns 0 when no cassettes exist."""
    result = storage.delete_all()
    assert result == 0


def test_delete_all_with_cassettes(storage: CassetteStorage, sample_cassette: Cassette):
    """delete_all removes all cassettes across all domains."""
    key = MatchingKey(method="GET", path="/api/v1/users")
    storage.save(cassette=sample_cassette, matching_key=key)

    # Also save for a different domain
    cassette2 = sample_cassette.model_copy(
        update={"meta": sample_cassette.meta.model_copy(update={"domain": "other.com"})}
    )
    storage.save(cassette=cassette2, matching_key=key)

    assert len(storage.list_all()) == 2
    result = storage.delete_all()
    assert result == 2
    assert storage.list_all() == []


def test_save_creates_file(storage: CassetteStorage, sample_cassette: Cassette):
    """save writes cassette JSON to disk."""
    key = MatchingKey(method="GET", path="/api/v1/users")
    filepath = storage.save(cassette=sample_cassette, matching_key=key)
    assert filepath.exists()
    assert filepath.suffix == ".json"
