"""Route config auto-generation and loading."""

import json
from pathlib import Path

import yaml

from vcr_proxy.models import (
    MatchedFields,
    RecordedRequest,
    RouteIgnoreConfig,
    RouteMatchingOverride,
    RouteMatchRule,
)


def _extract_body_fields(body: str | None, content_type: str | None) -> list[str]:
    """Extract top-level field names from a request body."""
    if body is None or content_type is None:
        return []

    if "application/json" in content_type:
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                return sorted(parsed.keys())
        except (json.JSONDecodeError, TypeError):
            pass

    if "application/x-www-form-urlencoded" in content_type:
        from urllib.parse import parse_qs

        parsed = parse_qs(body, keep_blank_values=True)
        return sorted(parsed.keys())

    return []


class RouteConfigManager:
    def __init__(self, cassettes_dir: Path) -> None:
        self.routes_dir = cassettes_dir / "_routes"

    def _config_path(self, domain: str, method: str, path: str) -> Path:
        slug = path.strip("/").replace("/", "_") or "root"
        filename = f"{method.upper()}_{slug}.yaml"
        return self.routes_dir / domain / filename

    def auto_generate(self, domain: str, request: RecordedRequest) -> Path:
        """Auto-generate or update a route config from a recorded request."""
        config_path = self._config_path(domain, request.method, request.path)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        body_fields = _extract_body_fields(request.body, request.content_type)
        query_params = sorted(request.query.keys())
        headers = sorted(k.lower() for k in request.headers)

        if config_path.exists():
            # Update matched fields only, don't touch ignore
            existing = self.load(domain, request.method, request.path)
            if existing:
                new_body = sorted(set(existing.matched.body_fields) | set(body_fields))
                new_query = sorted(set(existing.matched.query_params) | set(query_params))
                new_headers = sorted(set(existing.matched.headers) | set(headers))
                existing.matched.body_fields = new_body
                existing.matched.query_params = new_query
                existing.matched.headers = new_headers
                data = existing.model_dump()
                config_path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
                return config_path

        override = RouteMatchingOverride(
            route=RouteMatchRule(method=request.method.upper(), path=request.path),
            matched=MatchedFields(
                query_params=query_params,
                headers=headers,
                body_fields=body_fields,
            ),
            ignore=RouteIgnoreConfig(),
        )
        data = override.model_dump()
        config_path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
        return config_path

    def load(self, domain: str, method: str, path: str) -> RouteMatchingOverride | None:
        """Load a route config, if it exists."""
        config_path = self._config_path(domain, method, path)
        if not config_path.exists():
            return None
        data = yaml.safe_load(config_path.read_text())
        return RouteMatchingOverride.model_validate(data)
