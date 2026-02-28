"""Admin API for runtime management."""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from vcr_proxy.models import HandlerProtocol, ProxyMode, ProxyStats


class ModeRequest(BaseModel):
    mode: ProxyMode


class ModeResponse(BaseModel):
    mode: ProxyMode


class DeleteResponse(BaseModel):
    deleted: int


class CassetteInfo(BaseModel):
    domain: str
    filename: str
    cassette_id: str


def create_admin_app(handler: HandlerProtocol) -> FastAPI:
    """Create the admin API FastAPI app."""
    admin = FastAPI(title="VCR Proxy Admin")

    @admin.get("/api/mode", response_model=ModeResponse)
    async def get_mode() -> ModeResponse:
        return ModeResponse(mode=handler.mode)

    @admin.put("/api/mode", response_model=ModeResponse)
    async def set_mode(req: ModeRequest) -> ModeResponse:
        handler.mode = req.mode
        return ModeResponse(mode=handler.mode)

    @admin.get("/api/stats", response_model=ProxyStats)
    async def get_stats() -> ProxyStats:
        return ProxyStats(
            total_requests=handler.stats_total,
            cache_hits=handler.stats_hits,
            cache_misses=handler.stats_misses,
            recorded=handler.stats_recorded,
            errors=handler.stats_errors,
        )

    @admin.get("/api/cassettes", response_model=list[CassetteInfo])
    async def list_cassettes() -> list[CassetteInfo]:
        files = handler.storage.list_all()
        return [
            CassetteInfo(
                domain=f.parent.name,
                filename=f.name,
                cassette_id=f.stem,
            )
            for f in files
        ]

    @admin.get("/api/cassettes/{domain}", response_model=list[CassetteInfo])
    async def list_domain_cassettes(domain: str) -> list[CassetteInfo]:
        files = handler.storage.list_cassettes(domain=domain)
        return [CassetteInfo(domain=domain, filename=f.name, cassette_id=f.stem) for f in files]

    @admin.delete("/api/cassettes", response_model=DeleteResponse)
    async def delete_all_cassettes() -> DeleteResponse:
        count = handler.storage.delete_all()
        return DeleteResponse(deleted=count)

    @admin.delete("/api/cassettes/{domain}", response_model=DeleteResponse)
    async def delete_domain_cassettes(domain: str) -> DeleteResponse:
        count = handler.storage.delete_domain(domain=domain)
        return DeleteResponse(deleted=count)

    @admin.delete("/api/cassettes/{domain}/{cassette_id}", response_model=DeleteResponse)
    async def delete_cassette(domain: str, cassette_id: str) -> DeleteResponse:
        deleted = handler.storage.delete(domain=domain, cassette_id=cassette_id)
        return DeleteResponse(deleted=1 if deleted else 0)

    return admin
