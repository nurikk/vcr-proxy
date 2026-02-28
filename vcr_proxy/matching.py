"""Request matching: normalization, key computation, and hashing."""

import hashlib
import json
from urllib.parse import parse_qs, urlencode

from vcr_proxy.models import MatchingKey, RecordedRequest, RouteIgnoreConfig


def _normalize_json_body(body: str) -> str:
    """Parse JSON, sort keys recursively, return compact serialization."""
    parsed = json.loads(body)
    return json.dumps(parsed, sort_keys=True, separators=(",", ":"))


def _normalize_form_body(body: str) -> str:
    """Parse form-urlencoded body, sort by key, return normalized string."""
    parsed = parse_qs(body, keep_blank_values=True)
    sorted_params = sorted(parsed.items())
    return urlencode(sorted_params, doseq=True)


def _normalize_query(query: dict[str, list[str]]) -> str | None:
    """Sort query parameters by key, sort multi-values, return string."""
    if not query:
        return None
    sorted_query = sorted((k, sorted(v)) for k, v in query.items())
    return urlencode(sorted_query, doseq=True)


def _normalize_headers(
    headers: dict[str, str],
    ignore_headers: frozenset[str] | None = None,
    route_ignore: list[str] | None = None,
) -> str | None:
    """Lowercase keys, sort, exclude ignored headers, return string."""
    ignored = set()
    if ignore_headers:
        ignored.update(ignore_headers)
    if route_ignore:
        ignored.update(h.lower() for h in route_ignore)

    filtered = {k.lower(): v for k, v in headers.items() if k.lower() not in ignored}
    if not filtered:
        return None
    sorted_headers = sorted(filtered.items())
    return "&".join(f"{k}={v}" for k, v in sorted_headers)


def _normalize_body(
    body: str | None,
    content_type: str | None,
    ignore_body_fields: list[str] | None = None,
) -> str | None:
    """Normalize body based on content type."""
    if body is None:
        return None

    if content_type and "application/json" in content_type:
        try:
            parsed = json.loads(body)
            if ignore_body_fields and isinstance(parsed, dict):
                for field in ignore_body_fields:
                    parsed.pop(field, None)
            return json.dumps(parsed, sort_keys=True, separators=(",", ":"))
        except (json.JSONDecodeError, TypeError):
            return body

    if content_type and "application/x-www-form-urlencoded" in content_type:
        return _normalize_form_body(body)

    return body


def compute_matching_key(
    request: RecordedRequest,
    ignore_headers: frozenset[str] | None = None,
    route_ignore: RouteIgnoreConfig | None = None,
) -> MatchingKey:
    """Compute a normalized matching key for a request."""
    ignore_query = route_ignore.query_params if route_ignore else []
    filtered_query = {k: v for k, v in request.query.items() if k not in ignore_query}

    return MatchingKey(
        method=request.method.upper(),
        path=request.path.lower().rstrip("/") or "/",
        query=_normalize_query(filtered_query),
        headers=_normalize_headers(
            request.headers,
            ignore_headers=ignore_headers,
            route_ignore=route_ignore.headers if route_ignore else None,
        ),
        body=_normalize_body(
            request.body,
            request.content_type,
            ignore_body_fields=route_ignore.body_fields if route_ignore else None,
        ),
    )


def compute_hash(key: MatchingKey) -> str:
    """Compute a short SHA-256 hash from a matching key for filenames."""
    raw = key.model_dump_json()
    full_hash = hashlib.sha256(raw.encode()).hexdigest()
    return full_hash[:8]
