ARG PYTHON_VERSION=3.14
FROM python:${PYTHON_VERSION}-slim AS base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./

# --- Test stage: includes dev deps + tests ---
FROM base AS test

COPY vcr_proxy/ vcr_proxy/
COPY tests/ tests/
RUN uv sync --frozen

CMD ["uv", "run", "pytest", "-v", "--tb=short"]

# --- Production stage ---
FROM base AS production

COPY vcr_proxy/ vcr_proxy/
RUN uv sync --frozen --no-dev

EXPOSE 8080 8081

ENTRYPOINT ["uv", "run", "uvicorn", "vcr_proxy.main:app", "--host", "0.0.0.0", "--port", "8080"]
