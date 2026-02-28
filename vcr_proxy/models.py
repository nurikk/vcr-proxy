"""Pydantic models for VCR Proxy."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from pydantic import BaseModel

if TYPE_CHECKING:
    from vcr_proxy.storage import CassetteStorage


class ProxyMode(StrEnum):
    RECORD = "record"
    REPLAY = "replay"
    SPY = "spy"


# --- Cassette models ---


class RecordedRequest(BaseModel):
    method: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    body: str | None = None
    body_encoding: Literal["utf-8", "base64"] = "utf-8"
    content_type: str | None = None


class RecordedResponse(BaseModel):
    status_code: int
    headers: dict[str, str]
    body: str | None = None
    body_encoding: Literal["utf-8", "base64"] = "utf-8"


class CassetteMeta(BaseModel):
    recorded_at: datetime
    target: str
    domain: str
    vcr_proxy_version: str


class Cassette(BaseModel):
    meta: CassetteMeta
    request: RecordedRequest
    response: RecordedResponse


# --- Matching ---


class MatchingKey(BaseModel):
    method: str
    path: str
    query: str | None = None
    body: str | None = None
    headers: str | None = None


# --- Route config models ---


class RouteMatchRule(BaseModel):
    method: str
    path: str | None = None
    path_pattern: str | None = None  # regex


class MatchedFields(BaseModel):
    """Read-only: fields discovered during recording. For developer reference."""

    query_params: list[str] = []
    headers: list[str] = []
    body_fields: list[str] = []


class RouteIgnoreConfig(BaseModel):
    headers: list[str] = []
    body_fields: list[str] = []  # JSONPath expressions
    query_params: list[str] = []


class RouteMatchingOverride(BaseModel):
    route: RouteMatchRule
    matched: MatchedFields = MatchedFields()
    ignore: RouteIgnoreConfig = RouteIgnoreConfig()


# --- Handler protocol ---


@runtime_checkable
class HandlerProtocol(Protocol):
    """Structural type shared by ProxyHandler and VCRAddon."""

    mode: ProxyMode
    storage: CassetteStorage
    stats_total: int
    stats_hits: int
    stats_misses: int
    stats_recorded: int
    stats_errors: int


# --- Stats ---


class ProxyStats(BaseModel):
    total_requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    recorded: int = 0
    errors: int = 0
