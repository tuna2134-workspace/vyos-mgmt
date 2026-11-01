# syntax=docker/dockerfile:1

# ---------- Frontend: Next.js static export ----------
FROM node:24-alpine AS frontend

WORKDIR /app/frontend
RUN npm install -g pnpm@12.3.4

COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend/ ./
ARG NEXT_PUBLIC_API_BASE_URL=/api/v1
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

# ---------- Backend runtime ----------
FROM python:3.13-slim AS runtime

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    SERVE_FRONTEND=true \
    FRONTEND_DIR=/app/frontend/out \
    PORT=8000

WORKDIR /app

# Dependency layer (changes less often than source).
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY docker/entrypoint.sh ./docker/entrypoint.sh
RUN uv sync --frozen --no-dev \
    && chmod +x /app/docker/entrypoint.sh \
    && useradd --create-home --uid 10001 app \
    && chown -R app:app /app

COPY --from=frontend --chown=app:app /app/frontend/out ./frontend/out

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)"

ENTRYPOINT ["/app/docker/entrypoint.sh"]
