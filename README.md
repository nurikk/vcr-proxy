# VCR Proxy

HTTP record/replay proxy server. Intercepts traffic between your app and external APIs, saves request/response pairs as "cassettes," and replays them without hitting the real server.

**Why not Hoverfly / Proxay / MockServer?** They lack proper request body matching — two POST requests to the same endpoint with different JSON payloads return the same response. VCR Proxy matches on **everything** by default: method, path, query string, headers, and body.

## Quick Start

### Docker

```bash
# Record mode — proxy to a real API and save cassettes
docker run -d \
  -p 8080:8080 -p 8081:8081 \
  -e VCR_TARGET=https://api.example.com \
  -e VCR_MODE=record \
  -v ./cassettes:/app/cassettes \
  vcr-proxy

# Replay mode — serve from cassettes, no network needed
docker run -d \
  -p 8080:8080 \
  -e VCR_MODE=replay \
  -v ./cassettes:/app/cassettes \
  vcr-proxy
```

### Docker Compose

```yaml
services:
  vcr-proxy:
    image: vcr-proxy:latest
    ports:
      - "8080:8080"
      - "8081:8081"
    environment:
      VCR_MODE: spy
    volumes:
      - ./cassettes:/app/cassettes
      - ./vcr-proxy.yaml:/app/vcr-proxy.yaml:ro

  app:
    image: my-app:latest
    environment:
      API_BASE_URL: http://vcr-proxy:8080/api
      AUTH_BASE_URL: http://vcr-proxy:8080/auth
    depends_on:
      - vcr-proxy
```

### Local Development

```bash
uv sync
uv run uvicorn vcr_proxy.main:app --port 8080
```

## Modes

| Mode | Behavior |
|------|----------|
| **record** | Forward all requests to the target, save responses as cassettes |
| **replay** | Serve from cassettes only, return 404 on miss |
| **spy** | Serve from cassettes on hit, forward and record on miss |

Switch modes at runtime via the Admin API:

```bash
curl -X PUT http://localhost:8081/api/mode -H 'Content-Type: application/json' -d '{"mode": "replay"}'
```

## Configuration

Configure via YAML file, environment variables, or both. Env vars use the `VCR_` prefix and take precedence.

### vcr-proxy.yaml

```yaml
mode: spy                          # record | replay | spy
port: 8080
admin_port: 8081

# Route-to-target mapping
# Request to /api/* → https://api.example.com/*
# Request to /auth/* → https://auth.example.com/*
targets:
  "/api": https://api.example.com
  "/auth": https://auth.example.com
  "/": https://default-backend.example.com

cassettes:
  dir: ./cassettes
  overwrite: true

matching:
  always_ignore_headers:
    - date
    - x-request-id
    - x-trace-id
    - traceparent
    - tracestate

logging:
  level: info                      # debug | info | warning | error
  format: json                     # json | text
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VCR_MODE` | `spy` | Operating mode: `record`, `replay`, `spy` |
| `VCR_PORT` | `8080` | Proxy server port |
| `VCR_ADMIN_PORT` | `8081` | Admin API port |
| `VCR_TARGET` | — | Single target URL |
| `VCR_CASSETTES_DIR` | `cassettes` | Cassette storage directory |
| `VCR_PROXY_TIMEOUT` | `30.0` | Target request timeout (seconds) |
| `VCR_LOG_LEVEL` | `info` | Log level |
| `VCR_LOG_FORMAT` | `json` | Log format: `json` or `text` |

## Client Integration

No special libraries needed — just point your HTTP client at VCR Proxy:

```python
import httpx

async with httpx.AsyncClient(base_url="http://localhost:8080") as client:
    # /api/* → api.example.com
    users = await client.get("/api/v1/users")

    # /auth/* → auth.example.com
    token = await client.post("/auth/oauth/token", data={...})
```

Or via environment variables:

```python
import os
API_URL = os.getenv("API_BASE_URL", "https://api.example.com")
```

## Request Matching

### Exact by Default

Every request component participates in matching: method, path, query string, headers, and body. Two POST requests with different JSON payloads always produce different cassettes.

### Normalization

| Component | Normalization |
|-----------|--------------|
| Method | Uppercase (`post` → `POST`) |
| Path | Lowercase, trailing slash stripped |
| Query string | Params sorted by key, values URL-decoded |
| Headers | Lowercase keys, sorted, ignored headers excluded |
| Body (JSON) | Keys sorted recursively, compact serialization |
| Body (form) | Params sorted by key |
| Body (other) | Raw bytes as-is |

### Ignored Headers

These headers are always excluded from matching (configurable):

- `date`
- `x-request-id`
- `x-trace-id`
- `traceparent`
- `tracestate`

### Per-Route Overrides

When recording, VCR Proxy auto-generates a route config in `cassettes/_routes/`:

```yaml
route:
  method: POST
  path: "/api/v1/events"

matched:
  headers:
    - content-type
    - authorization
  body_fields:
    - action
    - user_id
    - request_id

ignore:
  headers: []
  body_fields: []
  query_params: []
```

To relax matching for non-deterministic fields, add them to `ignore`:

```yaml
ignore:
  body_fields:
    - "$.request_id"
    - "$.timestamp"
  headers:
    - authorization
```

## Cassette Storage

Cassettes are JSON files grouped by target domain:

```
cassettes/
├── _routes/                              # auto-generated route configs
│   └── api.example.com/
│       └── POST_api_v1_events.yaml
├── api.example.com/
│   ├── GET_api_v1_users_f8e2a1b3.json
│   ├── POST_api_v1_users_a1b2c3d4.json
│   └── POST_api_v1_users_7c9d3e5f.json  # same endpoint, different body
└── auth.example.com/
    └── POST_oauth_token_1a2b3c4d.json
```

Each cassette contains the full request and response:

```json
{
  "meta": {
    "recorded_at": "2025-02-28T12:00:00Z",
    "target": "https://api.example.com",
    "domain": "api.example.com",
    "vcr_proxy_version": "1.0.0"
  },
  "request": {
    "method": "POST",
    "path": "/api/v1/users",
    "query": {"page": ["1"]},
    "headers": {"content-type": "application/json"},
    "body": "{\"name\": \"Alice\"}",
    "body_encoding": "utf-8",
    "content_type": "application/json"
  },
  "response": {
    "status_code": 201,
    "headers": {"content-type": "application/json"},
    "body": "{\"id\": 42, \"name\": \"Alice\"}",
    "body_encoding": "utf-8"
  }
}
```

## Admin API

REST API on a separate port (default 8081) for runtime management.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/mode` | Get current mode |
| `PUT` | `/api/mode` | Switch mode (`{"mode": "replay"}`) |
| `GET` | `/api/stats` | Request statistics (hits, misses, recorded) |
| `GET` | `/api/cassettes` | List all cassettes |
| `GET` | `/api/cassettes/{domain}` | List cassettes for a domain |
| `DELETE` | `/api/cassettes` | Delete all cassettes |
| `DELETE` | `/api/cassettes/{domain}` | Delete all cassettes for a domain |
| `DELETE` | `/api/cassettes/{domain}/{id}` | Delete a specific cassette |

### Examples

```bash
# Check current mode
curl http://localhost:8081/api/mode

# Switch to replay
curl -X PUT http://localhost:8081/api/mode \
  -H 'Content-Type: application/json' \
  -d '{"mode": "replay"}'

# View stats
curl http://localhost:8081/api/stats

# List all cassettes
curl http://localhost:8081/api/cassettes

# Delete all cassettes for a domain
curl -X DELETE http://localhost:8081/api/cassettes/api.example.com
```

## Development

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest -v

# Run tests in Docker (same as CI)
docker compose run --rm tests-ci

# Lint
uv run ruff check .

# Format
uv run ruff format .
```

## Architecture

```
vcr_proxy/
├── main.py           # Entrypoint (uvicorn target)
├── app.py            # FastAPI app factory
├── proxy.py          # Core proxy handler (record/replay/spy)
├── matching.py       # Request normalization + SHA-256 hashing
├── storage.py        # File-based cassette storage
├── route_config.py   # Per-route matching override configs
├── admin.py          # Admin API endpoints
├── models.py         # Pydantic models (all data structures)
├── config.py         # Settings via pydantic-settings
└── logging.py        # Structured logging (structlog)
```

## License

MIT
