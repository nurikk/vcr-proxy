# VCR Proxy

HTTP record/replay proxy server. See `vcr-proxy-prd-en.md` for full PRD.

## Commands
- `uv run pytest` — run tests
- `uv run ruff check .` — lint
- `uv run ruff format .` — format
- `uv run uvicorn vcr_proxy.main:app --port 8080` — run proxy server

## Code Rules
- ALL data structures must be Pydantic BaseModel. No raw dicts except for arbitrary external JSON.
- Tests: plain functions, no classes. pytest fixtures, plain assert.
- Test naming: `test_{what}_{scenario}`
- Python 3.14, async throughout.
