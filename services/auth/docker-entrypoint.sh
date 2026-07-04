#!/bin/sh
# Apply migrations, then serve. Single-replica dev ordering; Phase 2 moves the
# migration step to a dedicated pre-deploy job (devops O-roadmap).
set -eu

echo "auth: alembic upgrade head"
alembic upgrade head

# The in-container port is fixed at 8001 (matches EXPOSE, the compose port map's
# container side, and the healthcheck). AUTH_PORT only varies the *host-published*
# port in compose — it must never change the internal bind (m3).
echo "auth: starting uvicorn on :8001"
exec uvicorn auth.main:app --host 0.0.0.0 --port 8001
