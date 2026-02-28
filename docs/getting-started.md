# Getting Started with VCR Proxy

## 1. Install

```bash
git clone https://github.com/nurikk/vcr-proxy.git
cd vcr-proxy
uv sync
```

## 2. Choose Your Proxy Architecture

### Option A: Reverse Proxy (change your app's base URL)

```bash
# Point at one API
VCR_MODE=spy VCR_TARGET=https://api.example.com \
  uv run uvicorn vcr_proxy.main:app --port 8080

# Your app calls http://localhost:8080 instead of https://api.example.com
```

```bash
# Point at multiple APIs via path prefixes
cat > vcr-proxy.yaml <<EOF
mode: spy
targets:
  "/api": https://api.example.com
  "/auth": https://auth.example.com
EOF

uv run uvicorn vcr_proxy.main:app --port 8080

# /api/*  → api.example.com
# /auth/* → auth.example.com
```

### Option B: Forward Proxy (zero code changes, HTTPS support)

```bash
uv run vcr-forward-proxy

# In your app's shell:
export HTTP_PROXY=http://localhost:8888
export HTTPS_PROXY=http://localhost:8888

# All HTTP/HTTPS traffic is now intercepted
```

For HTTPS, trust the CA cert on first run:
```bash
# Python
export SSL_CERT_FILE=~/.mitmproxy/mitmproxy-ca-cert.pem

# curl
curl --cacert ~/.mitmproxy/mitmproxy-ca-cert.pem https://api.example.com/users

# Node.js
export NODE_EXTRA_CA_CERTS=~/.mitmproxy/mitmproxy-ca-cert.pem
```

## 3. Typical Workflow

```
1. Start in SPY mode (default)        → cache hits served, misses forwarded & recorded
2. Run your app / test suite           → cassettes accumulate in ./cassettes/
3. Commit cassettes/ to your repo
4. Switch to REPLAY in CI              → fully offline, deterministic
```

```bash
# Switch mode at runtime
curl -X PUT http://localhost:8081/api/mode \
  -H 'Content-Type: application/json' -d '{"mode": "replay"}'
```

## 4. Use in pytest (no server needed)

### Reverse proxy — in-process

```python
# conftest.py
from pathlib import Path
from collections.abc import AsyncIterator
import httpx, pytest
from vcr_proxy.app import create_app

@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        cassettes_dir=Path("cassettes"),
        mode="replay",                              # or "spy" during dev
        targets={"/api": "https://api.example.com"},
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c
```

```python
# test_users.py
async def test_list_users(client):
    resp = await client.get("/api/v1/users")
    assert resp.status_code == 200
```

### Forward proxy — mitmproxy addon

```python
# conftest.py
from pathlib import Path
import pytest
from vcr_proxy.config import Settings
from vcr_proxy.forward import VCRAddon

@pytest.fixture
def vcr(tmp_path):
    return VCRAddon(Settings(mode="spy", cassettes_dir=tmp_path / "cassettes"))
```

```python
# test_forward.py
from mitmproxy.test import tflow, tutils

def test_record_replay(vcr):
    flow = tflow.tflow(req=tutils.treq(
        host="api.example.com", port=443, scheme=b"https",
        authority=b"api.example.com", path=b"/v1/users",
        method=b"GET", headers=[(b"host", b"api.example.com")], content=b"",
    ))
    vcr.request(flow)
    flow.response = tutils.tresp(content=b'[{"id":1}]', status_code=200)
    flow.response.headers.clear()
    flow.response.headers["content-type"] = "application/json"
    vcr.response(flow)

    vcr.mode = "replay"
    replay = tflow.tflow(req=tutils.treq(
        host="api.example.com", port=443, scheme=b"https",
        authority=b"api.example.com", path=b"/v1/users",
        method=b"GET", headers=[(b"host", b"api.example.com")], content=b"",
    ))
    vcr.request(replay)
    assert replay.response.status_code == 200
```

## 5. Docker

```bash
# Reverse proxy
docker compose up vcr-proxy          # localhost:8080 (proxy) + :8081 (admin)

# Forward proxy
docker compose up vcr-forward-proxy  # localhost:8888 (proxy) + :8082 (admin)

# Run tests in Docker
docker compose run --rm tests-ci
```

## 6. Key Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `VCR_MODE` | `spy` | `record` / `replay` / `spy` |
| `VCR_TARGET` | — | Single target URL (reverse proxy) |
| `VCR_CASSETTES_DIR` | `cassettes` | Where cassettes are stored |
| `VCR_FORWARD_PROXY_PORT` | `8888` | Forward proxy listen port |
| `VCR_ADMIN_PORT` | `8081` | Admin API port |
| `VCR_MITM_CONFDIR` | — | Custom mitmproxy CA cert directory |

## 7. Admin API (port 8081)

```bash
curl localhost:8081/api/mode                        # get mode
curl -X PUT localhost:8081/api/mode -d '{"mode":"replay"}' -H 'Content-Type: application/json'
curl localhost:8081/api/stats                        # hits/misses/recorded
curl localhost:8081/api/cassettes                    # list all
curl -X DELETE localhost:8081/api/cassettes           # delete all
curl localhost:8081/api/ca-cert -o ca.pem            # download MITM cert
```
