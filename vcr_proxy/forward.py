"""Forward proxy addon for mitmproxy — record/replay/spy modes."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from urllib.parse import urlparse

import structlog
from mitmproxy import http

from vcr_proxy.config import Settings
from vcr_proxy.matching import compute_matching_key
from vcr_proxy.models import (
    Cassette,
    CassetteMeta,
    ProxyMode,
    RecordedResponse,
)
from vcr_proxy.recording import build_recorded_request, build_recorded_response_from_raw
from vcr_proxy.route_config import RouteConfigManager
from vcr_proxy.storage import CassetteStorage

logger = structlog.get_logger()


class VCRAddon:
    """mitmproxy addon implementing VCR record/replay/spy."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.storage = CassetteStorage(cassettes_dir=settings.cassettes_dir)
        self.route_config_manager = RouteConfigManager(cassettes_dir=settings.cassettes_dir)
        self.mode = settings.mode
        self.stats_total = 0
        self.stats_hits = 0
        self.stats_misses = 0
        self.stats_recorded = 0
        self.stats_errors = 0
        self._pending_record: set[str] = set()

    def request(self, flow: http.HTTPFlow) -> None:
        """Called when a request is received. For replay/spy, may short-circuit."""
        self.stats_total += 1

        parsed = urlparse(flow.request.pretty_url)
        domain = parsed.hostname or "unknown"
        path = parsed.path or "/"
        query_string = parsed.query or ""
        headers = dict(flow.request.headers)
        body = flow.request.content

        recorded_req = build_recorded_request(
            method=flow.request.method,
            path=path,
            query_string=query_string,
            headers=headers,
            body=body,
        )
        matching_key = compute_matching_key(
            recorded_req,
            ignore_headers=self.settings.always_ignore_headers,
        )

        if self.mode == ProxyMode.RECORD:
            flow.metadata["vcr_domain"] = domain
            flow.metadata["vcr_matching_key"] = matching_key
            flow.metadata["vcr_recorded_req"] = recorded_req
            return

        # REPLAY or SPY: try cache lookup
        cassette = self.storage.lookup(domain=domain, matching_key=matching_key)

        if cassette is not None:
            self.stats_hits += 1
            body_bytes = _decode_body(cassette.response)
            flow.response = http.Response.make(
                status_code=cassette.response.status_code,
                content=body_bytes,
                headers=dict(cassette.response.headers),
            )
            return

        if self.mode == ProxyMode.REPLAY:
            self.stats_misses += 1
            flow.response = http.Response.make(
                404,
                b'{"error": "no matching cassette found"}',
                {"content-type": "application/json"},
            )
            return

        # SPY mode, cache miss — let it through, mark for recording
        self.stats_misses += 1
        flow.metadata["vcr_domain"] = domain
        flow.metadata["vcr_matching_key"] = matching_key
        flow.metadata["vcr_recorded_req"] = recorded_req
        self._pending_record.add(flow.id)

    def response(self, flow: http.HTTPFlow) -> None:
        """Called when a response is received. Record if needed."""
        should_record = self.mode == ProxyMode.RECORD or (
            self.mode == ProxyMode.SPY and flow.id in self._pending_record
        )

        if not should_record:
            return

        self._pending_record.discard(flow.id)

        domain = flow.metadata.get("vcr_domain")
        matching_key = flow.metadata.get("vcr_matching_key")
        recorded_req = flow.metadata.get("vcr_recorded_req")

        if not all([domain, matching_key, recorded_req]):
            return

        recorded_resp = build_recorded_response_from_raw(
            status_code=flow.response.status_code,
            headers=dict(flow.response.headers),
            body=flow.response.content,
        )

        target_url = f"{flow.request.scheme}://{domain}"
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


def _decode_body(response: RecordedResponse) -> bytes:
    if response.body is None:
        return b""
    if response.body_encoding == "base64":
        return base64.b64decode(response.body)
    return response.body.encode("utf-8")
