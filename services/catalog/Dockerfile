# syntax=docker/dockerfile:1
# billet catalog image — multi-stage, non-root, patch-pinned base (O4).
# uv uses the base image's Python (no separate interpreter download) so the
# venv copied into the runtime stage resolves against /usr/local/bin/python.

FROM python:3.12.13-slim AS builder
ENV UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv
RUN pip install --no-cache-dir uv==0.11.26
WORKDIR /app
# deps first (cached until the lockfile changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
# then the project itself
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
RUN uv sync --frozen --no-dev

FROM python:3.12.13-slim AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN groupadd --system app \
    && useradd --system --gid app --uid 1000 --no-create-home appuser
WORKDIR /app
COPY --from=builder /app /app
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
USER appuser
EXPOSE 8002
ENTRYPOINT ["docker-entrypoint.sh"]
