"""Core proxy logic: record, replay, spy modes."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx
import structlog

from vcr_proxy.config import Settings
from vcr_proxy.matching import compute_matching_key
from vcr_proxy.models import (
    Cassette,
    CassetteMeta,
    ProxyMode,
    RecordedRequest,
    RecordedResponse,
)
from vcr_proxy.route_config import RouteConfigManager
from vcr_proxy.storage import CassetteStorage

logger = structlog.get_logger()


def _resolve_target(path: str, targets: dict[str, str]) -> tuple[str, str, str] | None:
    """Resolve a request path to a target URL.

    Returns (target_base_url, domain, remaining_path) or None.
    """
    for prefix, target_url in sorted(targets.items(), key=lambda x: -len(x[0])):
        if path == prefix or path.startswith(prefix + "/") or prefix == "/":
            remaining = path[len(prefix) :] if prefix != "/" else path
            if not remaining:
                remaining = "/"
            domain = target_url.split("://", 1)[-1].rstrip("/")
            return target_url, domain, remaining
    return None


def _is_text_content(content_type: str | None) -> bool:
    if content_type is None:
        return True
    text_types = (
        "application/json",
        "text/",
        "application/xml",
        "application/x-www-form-urlencoded",
    )
    return any(t in content_type for t in text_types)


def _build_recorded_request(
    method: str,
    path: str,
    query_string: str,
    headers: dict[str, str],
    body: bytes | None,
) -> RecordedRequest:
    """Build a RecordedRequest from raw HTTP components."""
    content_type = headers.get("content-type")
    query = parse_qs(query_string, keep_blank_values=True) if query_string else {}

    if body and _is_text_content(content_type):
        body_str = body.decode("utf-8", errors="replace")
        body_encoding = "utf-8"
    elif body:
        body_str = base64.b64encode(body).decode("ascii")
        body_encoding = "base64"
    else:
        body_str = None
        body_encoding = "utf-8"

    return RecordedRequest(
        method=method.upper(),
        path=path,
        query=query,
        headers={k.lower(): v for k, v in headers.items()},
        body=body_str,
        body_encoding=body_encoding,
        content_type=content_type,
    )


def _build_recorded_response(response: httpx.Response) -> RecordedResponse:
    """Build a RecordedResponse from an httpx response."""
    content_type = response.headers.get("content-type")
    if _is_text_content(content_type):
        body_str = response.text
        body_encoding = "utf-8"
    else:
        body_str = base64.b64encode(response.content).decode("ascii")
        body_encoding = "base64"

    return RecordedResponse(
        status_code=response.status_code,
        headers=dict(response.headers),
        body=body_str,
        body_encoding=body_encoding,
    )


async def forward_request(
    client: httpx.AsyncClient,
    target_url: str,
    method: str,
    path: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float = 30.0,
) -> httpx.Response:
    """Forward a request to the target server."""
    url = f"{target_url.rstrip('/')}{path}"
    fwd_headers = {k: v for k, v in headers.items() if k.lower() != "host"}
    return await client.request(
        method=method,
        url=url,
        headers=fwd_headers,
        content=body,
        timeout=timeout,
    )


class ProxyHandler:
    def __init__(
        self,
        settings: Settings,
        storage: CassetteStorage,
        route_config_manager: RouteConfigManager,
        http_client: httpx.AsyncClient,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.route_config_manager = route_config_manager
        self.http_client = http_client
        self.mode = settings.mode
        self.stats_total = 0
        self.stats_hits = 0
        self.stats_misses = 0
        self.stats_recorded = 0
        self.stats_errors = 0

    async def handle(
        self,
        method: str,
        path: str,
        query_string: str,
        headers: dict[str, str],
        body: bytes | None,
    ) -> tuple[int, dict[str, str], bytes]:
        """Handle a proxy request. Returns (status, headers, body)."""
        self.stats_total += 1

        resolved = _resolve_target(path, self.settings.targets)
        if resolved is None:
            self.stats_errors += 1
            return (
                502,
                {"content-type": "application/json"},
                b'{"error": "no target configured for path"}',
            )

        target_url, domain, remaining_path = resolved

        recorded_req = _build_recorded_request(method, remaining_path, query_string, headers, body)
        matching_key = compute_matching_key(
            recorded_req,
            ignore_headers=self.settings.always_ignore_headers,
        )

        if self.mode == ProxyMode.RECORD:
            return await self._handle_record(
                target_url,
                domain,
                method,
                remaining_path,
                headers,
                body,
                recorded_req,
                matching_key,
            )
        elif self.mode == ProxyMode.REPLAY:
            return self._handle_replay(domain, matching_key)
        else:  # SPY
            return await self._handle_spy(
                target_url,
                domain,
                method,
                remaining_path,
                headers,
                body,
                recorded_req,
                matching_key,
            )

    async def _handle_record(
        self,
        target_url,
        domain,
        method,
        path,
        headers,
        body,
        recorded_req,
        matching_key,
    ) -> tuple[int, dict[str, str], bytes]:
        try:
            response = await forward_request(
                self.http_client,
                target_url,
                method,
                path,
                headers,
                body,
                timeout=self.settings.proxy_timeout,
            )
        except httpx.TimeoutException:
            self.stats_errors += 1
            return 504, {"content-type": "application/json"}, b'{"error": "target timeout"}'
        except httpx.ConnectError:
            self.stats_errors += 1
            return (
                502,
                {"content-type": "application/json"},
                b'{"error": "target unreachable"}',
            )

        recorded_resp = _build_recorded_response(response)
        cassette = Cassette(
            meta=CassetteMeta(
                recorded_at=datetime.now(UTC),
                target=target_url,
                domain=domain,
                vcr_proxy_version="1.0.0",
            ),
            request=recorded_req,
            response=recorded_resp,
        )
        self.storage.save(cassette=cassette, matching_key=matching_key)
        self.route_config_manager.auto_generate(domain=domain, request=recorded_req)
        self.stats_recorded += 1

        resp_body = response.content
        resp_headers = dict(response.headers)
        return response.status_code, resp_headers, resp_body

    def _handle_replay(self, domain, matching_key) -> tuple[int, dict[str, str], bytes]:
        cassette = self.storage.lookup(domain=domain, matching_key=matching_key)
        if cassette is None:
            self.stats_misses += 1
            return (
                404,
                {"content-type": "application/json"},
                b'{"error": "no matching cassette found"}',
            )

        self.stats_hits += 1
        body_bytes = self._decode_body(cassette.response)
        return cassette.response.status_code, dict(cassette.response.headers), body_bytes

    async def _handle_spy(
        self,
        target_url,
        domain,
        method,
        path,
        headers,
        body,
        recorded_req,
        matching_key,
    ) -> tuple[int, dict[str, str], bytes]:
        cassette = self.storage.lookup(domain=domain, matching_key=matching_key)
        if cassette is not None:
            self.stats_hits += 1
            body_bytes = self._decode_body(cassette.response)
            return cassette.response.status_code, dict(cassette.response.headers), body_bytes

        self.stats_misses += 1
        return await self._handle_record(
            target_url,
            domain,
            method,
            path,
            headers,
            body,
            recorded_req,
            matching_key,
        )

    @staticmethod
    def _decode_body(response: RecordedResponse) -> bytes:
        if response.body is None:
            return b""
        if response.body_encoding == "base64":
            return base64.b64decode(response.body)
        return response.body.encode("utf-8")
