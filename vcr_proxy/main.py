"""Main entrypoint: creates and configures the FastAPI app."""

from vcr_proxy.app import create_app
from vcr_proxy.config import Settings
from vcr_proxy.logging import setup_logging

settings = Settings()
setup_logging(level=settings.log_level, fmt=settings.log_format)
app = create_app(settings=settings)
