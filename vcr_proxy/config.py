"""Application configuration via pydantic-settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from vcr_proxy.models import ProxyMode

ALWAYS_IGNORED_HEADERS_DEFAULT: frozenset[str] = frozenset(
    {
        "date",
        "x-request-id",
        "x-trace-id",
        "traceparent",
        "tracestate",
    }
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VCR_")

    mode: ProxyMode = ProxyMode.SPY
    port: int = 8080
    admin_port: int = 8081

    target: str | None = None
    targets: dict[str, str] = Field(default_factory=dict)

    cassettes_dir: Path = Path("cassettes")
    cassettes_overwrite: bool = True

    always_ignore_headers: frozenset[str] = ALWAYS_IGNORED_HEADERS_DEFAULT

    hook_on_start: str = ""
    hook_on_stop: str = ""
    hook_on_cassette_written: str = ""

    log_level: str = "info"
    log_format: str = "json"

    proxy_timeout: float = 30.0
    max_body_size: int = 10 * 1024 * 1024  # 10 MB

    forward_proxy_port: int = 8888
    mitm_confdir: Path | None = None
