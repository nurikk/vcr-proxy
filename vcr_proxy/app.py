"""FastAPI application factory."""

from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response

from vcr_proxy.config import Settings
from vcr_proxy.models import ProxyMode
from vcr_proxy.proxy import ProxyHandler
from vcr_proxy.route_config import RouteConfigManager
from vcr_proxy.storage import CassetteStorage


def create_app(
    cassettes_dir: Path | None = None,
    mode: str = "spy",
    targets: dict[str, str] | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    """Create a FastAPI application for the proxy."""
    if settings is None:
        settings = Settings(
            mode=ProxyMode(mode),
            targets=targets or {},
            cassettes_dir=cassettes_dir or Path("cassettes"),
        )

    app = FastAPI(title="VCR Proxy")
    storage = CassetteStorage(cassettes_dir=settings.cassettes_dir)
    route_config_mgr = RouteConfigManager(cassettes_dir=settings.cassettes_dir)
    http_client = httpx.AsyncClient()

    handler = ProxyHandler(
        settings=settings,
        storage=storage,
        route_config_manager=route_config_mgr,
        http_client=http_client,
    )
    app.state.handler = handler
    app.state.settings = settings
    app.state.storage = storage

    @app.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    )
    async def proxy_endpoint(request: Request, path: str) -> Response:
        method = request.method
        full_path = f"/{path}"
        query_string = str(request.url.query) if request.url.query else ""
        headers = dict(request.headers)
        body = await request.body() or None

        status, resp_headers, resp_body = await handler.handle(
            method=method,
            path=full_path,
            query_string=query_string,
            headers=headers,
            body=body,
        )
        return Response(
            content=resp_body,
            status_code=status,
            headers=resp_headers,
        )

    return app
