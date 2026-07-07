#!/bin/sh
# Apply migrations, then serve. Single-replica dev ordering; Phase 2 moves the
# migration step to a dedicated pre-deploy job (devops O-roadmap).
set -eu

echo "catalog: alembic upgrade head"
alembic upgrade head

# The in-container port is fixed at 8002 (matches EXPOSE, the compose port map's
# container side, and the healthcheck). CATALOG_PORT only varies the *host-published*
# port in compose — it must never change the internal bind.
echo "catalog: starting uvicorn on :8002"
exec uvicorn catalog.main:app --host 0.0.0.0 --port 8002
