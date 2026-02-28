"""Shared recording utilities for building cassette data from raw HTTP."""

import base64
from urllib.parse import parse_qs

from vcr_proxy.models import RecordedRequest, RecordedResponse


def is_text_content(content_type: str | None) -> bool:
    if content_type is None:
        return True
    text_types = (
        "application/json",
        "text/",
        "application/xml",
        "application/x-www-form-urlencoded",
    )
    return any(t in content_type for t in text_types)


def build_recorded_request(
    method: str,
    path: str,
    query_string: str,
    headers: dict[str, str],
    body: bytes | None,
) -> RecordedRequest:
    """Build a RecordedRequest from raw HTTP components."""
    content_type = headers.get("content-type")
    query = parse_qs(query_string, keep_blank_values=True) if query_string else {}

    if body and is_text_content(content_type):
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


def build_recorded_response_from_raw(
    status_code: int,
    headers: dict[str, str],
    body: bytes | None,
) -> RecordedResponse:
    """Build a RecordedResponse from raw HTTP components (no httpx dependency)."""
    content_type = headers.get("content-type")
    if body and is_text_content(content_type):
        body_str = body.decode("utf-8", errors="replace")
        body_encoding = "utf-8"
    elif body:
        body_str = base64.b64encode(body).decode("ascii")
        body_encoding = "base64"
    else:
        body_str = None
        body_encoding = "utf-8"

    return RecordedResponse(
        status_code=status_code,
        headers=headers,
        body=body_str,
        body_encoding=body_encoding,
    )
