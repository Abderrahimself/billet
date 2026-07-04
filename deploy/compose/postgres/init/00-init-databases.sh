#!/usr/bin/env bash
# billet — Postgres bootstrap: one database + one least-privilege role per
# service (D5, mvp.md §3.1). Runs once, on an empty data dir, as the superuser.
#
# Passwords come from the container environment (injected from .env via compose),
# never hard-coded (O5). Identifiers/literals are passed as psql variables so the
# server does the quoting.
set -euo pipefail

create_service_db() {
  local svc="$1" pw="$2" db="${1}_db"

  # role + database, and lock the database down to its owner only (D5):
  # REVOKE ALL FROM PUBLIC means no other role can even CONNECT.
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
       --set=role="$svc" --set=db="$db" --set=pw="$pw" <<'SQL'
CREATE ROLE :"role" LOGIN PASSWORD :'pw';
CREATE DATABASE :"db" OWNER :"role";
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO :"role";
SQL

  # PG15+ locks down the public schema by default; hand it to the service role
  # so Alembic can create/alter tables in its own DB.
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" \
       --set=role="$svc" <<'SQL'
ALTER SCHEMA public OWNER TO :"role";
SQL

  echo "  ok: ${db} owned by role ${svc}"
}

echo "billet: provisioning per-service databases and roles (D5)..."
create_service_db auth    "$AUTH_DB_PASSWORD"
create_service_db catalog "$CATALOG_DB_PASSWORD"
create_service_db booking "$BOOKING_DB_PASSWORD"
create_service_db payment "$PAYMENT_DB_PASSWORD"
create_service_db tickets "$TICKETS_DB_PASSWORD"

# Harden the maintenance DBs too: no service role should be able to CONNECT to
# postgres/template1 and enumerate cluster-wide metadata (pg_database/pg_roles).
# The superuser bypasses CONNECT checks, so the healthcheck is unaffected (D5).
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<'SQL'
REVOKE CONNECT ON DATABASE postgres, template1 FROM PUBLIC;
SQL

echo "billet: 5 service databases ready."
