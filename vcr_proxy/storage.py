"""Cassette storage: save, load, list, and delete cassettes on disk."""

from __future__ import annotations

import re
from pathlib import Path

from vcr_proxy.matching import compute_hash
from vcr_proxy.models import Cassette, MatchingKey


def _path_to_slug(path: str) -> str:
    """Convert URL path to a safe filename slug."""
    slug = path.strip("/").replace("/", "_")
    slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", slug)
    return slug or "root"


class CassetteStorage:
    def __init__(self, cassettes_dir: Path) -> None:
        self.cassettes_dir = cassettes_dir

    def _domain_dir(self, domain: str) -> Path:
        return self.cassettes_dir / domain

    def _cassette_filename(self, matching_key: MatchingKey) -> str:
        slug = _path_to_slug(matching_key.path)
        hash_val = compute_hash(matching_key)
        return f"{matching_key.method}_{slug}_{hash_val}.json"

    def save(self, cassette: Cassette, matching_key: MatchingKey) -> Path:
        """Save a cassette to disk. Returns the file path."""
        domain = cassette.meta.domain
        domain_dir = self._domain_dir(domain)
        domain_dir.mkdir(parents=True, exist_ok=True)

        filename = self._cassette_filename(matching_key)
        filepath = domain_dir / filename
        filepath.write_text(cassette.model_dump_json(indent=2))
        return filepath

    def lookup(
        self, domain: str, matching_key: MatchingKey
    ) -> Cassette | None:
        """Look up a cassette by domain and matching key."""
        domain_dir = self._domain_dir(domain)
        if not domain_dir.exists():
            return None

        filename = self._cassette_filename(matching_key)
        filepath = domain_dir / filename
        if not filepath.exists():
            return None

        return Cassette.model_validate_json(filepath.read_text())

    def list_cassettes(self, domain: str) -> list[Path]:
        """List all cassette files for a domain."""
        domain_dir = self._domain_dir(domain)
        if not domain_dir.exists():
            return []
        return sorted(domain_dir.glob("*.json"))

    def list_all(self) -> list[Path]:
        """List all cassette files across all domains."""
        if not self.cassettes_dir.exists():
            return []
        return sorted(self.cassettes_dir.rglob("*.json"))

    def delete(self, domain: str, cassette_id: str) -> bool:
        """Delete a cassette by domain and ID (filename without extension)."""
        filepath = self._domain_dir(domain) / f"{cassette_id}.json"
        if filepath.exists():
            filepath.unlink()
            return True
        return False

    def delete_domain(self, domain: str) -> int:
        """Delete all cassettes for a domain. Returns count deleted."""
        domain_dir = self._domain_dir(domain)
        if not domain_dir.exists():
            return 0
        files = list(domain_dir.glob("*.json"))
        for f in files:
            f.unlink()
        return len(files)

    def delete_all(self) -> int:
        """Delete all cassettes. Returns count deleted."""
        files = self.list_all()
        for f in files:
            f.unlink()
        return len(files)
