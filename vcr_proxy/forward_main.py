"""Entrypoint for the mitmproxy-based forward proxy."""

from __future__ import annotations

import asyncio
import contextlib
import threading

import uvicorn
from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster

from vcr_proxy.admin import create_admin_app
from vcr_proxy.config import Settings
from vcr_proxy.forward import VCRAddon
from vcr_proxy.logging import setup_logging


async def _run(settings: Settings) -> None:
    addon = VCRAddon(settings)
    admin_app = create_admin_app(addon)

    opts = Options(
        listen_port=settings.forward_proxy_port,
        ssl_insecure=True,
    )

    if settings.mitm_confdir:
        opts.update(confdir=str(settings.mitm_confdir))

    master = DumpMaster(opts)
    master.addons.add(addon)

    def run_admin() -> None:
        uvicorn.run(admin_app, host="0.0.0.0", port=settings.admin_port)

    admin_thread = threading.Thread(target=run_admin, daemon=True)
    admin_thread.start()

    await master.run()


def main() -> None:
    settings = Settings()
    setup_logging(level=settings.log_level, fmt=settings.log_format)

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_run(settings))


if __name__ == "__main__":
    main()
