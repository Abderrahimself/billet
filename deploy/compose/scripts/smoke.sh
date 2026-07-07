#!/usr/bin/env bash
# billet — health smoke test for the local backing services.
# Proves each backing service is live AND that D5 database isolation holds.
# Runs every check (does not abort on first failure), then exits non-zero if any
# failed. Invoked by `make up` and `make smoke` from the repo root.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/../docker-compose.dev.yml"
ENV_FILE="$REPO_ROOT/.env"

# load .env for host-side vars (users, passwords, ports)
set -a
# shellcheck disable=SC1090
[ -f "$ENV_FILE" ] && . "$ENV_FILE"
set +a

DC=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

pass=0 fail=0
ok()  { printf '  \033[32mok  \033[0m %s\n' "$1"; pass=$((pass + 1)); }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail + 1)); }

check_http() { # url — curl if present, else a minimal HTTP GET over /dev/tcp
  if command -v curl >/dev/null 2>&1; then
    curl -fsS -o /dev/null --max-time 5 "$1"
    return
  fi
  local rest=${1#*://} hostport path host port line
  hostport=${rest%%/*}; path=/${rest#*/}; [ "$path" = "/$rest" ] && path=/
  host=${hostport%%:*}; port=${hostport##*:}
  exec 3<>"/dev/tcp/$host/$port" 2>/dev/null || return 1
  printf 'GET %s HTTP/1.0\r\nHost: %s\r\n\r\n' "$path" "$host" >&3
  IFS= read -r line <&3
  exec 3>&- 3<&-
  case "$line" in *" 200"*|*" 204"*) return 0 ;; *) return 1 ;; esac
}

retry_http() { # url — up to 10 tries over ~5s (minio/mailhog cold-start slack)
  local i
  for i in $(seq 1 10); do
    check_http "$1" && return 0
    sleep 0.5
  done
  return 1
}

echo "== billet backing-services smoke =========================="

# 1) Postgres reachable + all 5 service databases present -------------------
expected="auth_db,booking_db,catalog_db,payment_db,tickets_db"
dbs=$("${DC[@]}" exec -T postgres psql -U "$POSTGRES_USER" -d "${POSTGRES_DB:-postgres}" -tAc \
  "SELECT string_agg(datname, ',' ORDER BY datname) FROM pg_database
   WHERE datname IN ('auth_db','booking_db','catalog_db','payment_db','tickets_db')" 2>/dev/null | tr -d '\r')
if [ "$dbs" = "$expected" ]; then
  ok "postgres: 5 service databases present"
else
  bad "postgres: expected [$expected], got [$dbs]"
fi

# 2) Each service role connects to its OWN db (least privilege works) -------
role_can_connect() { # role pw db
  "${DC[@]}" exec -T -e PGPASSWORD="$2" postgres \
    psql -U "$1" -d "$3" -tAc 'SELECT 1' >/dev/null 2>&1
}
for pair in "auth:$AUTH_DB_PASSWORD" "catalog:$CATALOG_DB_PASSWORD" \
            "booking:$BOOKING_DB_PASSWORD" "payment:$PAYMENT_DB_PASSWORD" \
            "tickets:$TICKETS_DB_PASSWORD"; do
  svc=${pair%%:*}; pw=${pair#*:}
  if role_can_connect "$svc" "$pw" "${svc}_db"; then
    ok "postgres: role '$svc' -> ${svc}_db"
  else
    bad "postgres: role '$svc' cannot reach its own ${svc}_db"
  fi
done

# 3) D5 isolation: a role must NOT reach another service's db ---------------
if role_can_connect auth "$AUTH_DB_PASSWORD" catalog_db; then
  bad "postgres: role 'auth' reached catalog_db — D5 isolation is broken"
else
  ok "postgres: role 'auth' denied catalog_db (D5 isolation holds)"
fi

# 4) Redis: PING + keyspace expiry events (needed by the §5.2 listener) -----
if [ "$("${DC[@]}" exec -T redis redis-cli ping 2>/dev/null | tr -d '\r')" = "PONG" ]; then
  ok "redis: responds to PING"
else
  bad "redis: no PONG"
fi
kse=$("${DC[@]}" exec -T redis redis-cli config get notify-keyspace-events 2>/dev/null | tail -1 | tr -d '\r')
case "$kse" in
  *A*|*E*x*|*x*E*) ok "redis: keyspace expiry events enabled ('$kse')" ;;
  *)               bad "redis: notify-keyspace-events='$kse' lacks expiry flags — §5.2 listener would be deaf" ;;
esac

# 5) RabbitMQ: node ping + vhost present ------------------------------------
if "${DC[@]}" exec -T rabbitmq rabbitmq-diagnostics -q ping >/dev/null 2>&1; then
  ok "rabbitmq: node responds to ping"
else
  bad "rabbitmq: ping failed"
fi
vhost=${RABBITMQ_DEFAULT_VHOST:-billet}
if "${DC[@]}" exec -T rabbitmq rabbitmqctl -q list_vhosts 2>/dev/null | grep -qx "$vhost"; then
  ok "rabbitmq: vhost '$vhost' present"
else
  bad "rabbitmq: vhost '$vhost' missing"
fi

# 6) MinIO: liveness endpoint ----------------------------------------------
if retry_http "http://127.0.0.1:${MINIO_API_PORT:-9000}/minio/health/live"; then
  ok "minio: /minio/health/live (:${MINIO_API_PORT:-9000})"
else
  bad "minio: health endpoint not responding"
fi

# 7) Mailhog: JSON API ------------------------------------------------------
if retry_http "http://127.0.0.1:${MAILHOG_UI_PORT:-8025}/api/v2/messages"; then
  ok "mailhog: API reachable (:${MAILHOG_UI_PORT:-8025})"
else
  bad "mailhog: UI/API not responding"
fi

# 8) auth service: liveness + readiness (D8, §3.1) -------------------------
AUTH="http://127.0.0.1:${AUTH_PORT:-8001}"
if retry_http "$AUTH/healthz"; then ok "auth: /healthz"; else bad "auth: /healthz not responding"; fi
if retry_http "$AUTH/readyz"; then ok "auth: /readyz (auth_db reachable)"; else bad "auth: /readyz not 200"; fi

# 9) auth JWKS + signup→/me round-trip: proves RS256 verifies end to end ----
if command -v curl >/dev/null 2>&1; then
  jwks=$(curl -fsS --max-time 5 "$AUTH/.well-known/jwks.json" 2>/dev/null || true)
  case "$jwks" in
    *'"kty"'*'"RSA"'* | *'"kty":"RSA"'*) ok "auth: JWKS serves an RSA signing key" ;;
    *) bad "auth: JWKS missing RSA key [$jwks]" ;;
  esac

  email="smoke+$(date +%s)@example.com"
  body=$(curl -fsS --max-time 5 -H 'Content-Type: application/json' \
    -d "{\"email\":\"$email\",\"password\":\"smokepassword123\",\"display_name\":\"Smoke\"}" \
    "$AUTH/api/auth/signup" 2>/dev/null || true)
  access=$(printf '%s' "$body" | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')
  if [ -n "$access" ]; then
    me=$(curl -fsS --max-time 5 -H "Authorization: Bearer $access" "$AUTH/api/auth/me" 2>/dev/null || true)
    case "$me" in
      *"$email"*) ok "auth: signup→/me round-trip (token verified)" ;;
      *) bad "auth: /me did not return the new user [$me]" ;;
    esac
  else
    bad "auth: signup returned no access_token [$body]"
  fi
else
  echo "  -- skip auth JWKS + round-trip (curl not installed)"
fi

# 10) catalog service: liveness + readiness (D1, §3.1) ---------------------
CATALOG="http://127.0.0.1:${CATALOG_PORT:-8002}"
if retry_http "$CATALOG/healthz"; then ok "catalog: /healthz"; else bad "catalog: /healthz not responding"; fi
if retry_http "$CATALOG/readyz"; then ok "catalog: /readyz (catalog_db reachable)"; else bad "catalog: /readyz not 200"; fi

# 11) auth→catalog: an auth-minted token is accepted by catalog, verified via
#     JWKS — the first proof of D8 across a service boundary. Then the full
#     organizer flow: draft → tier → publish → public read → internal read. ----
if command -v curl >/dev/null 2>&1; then
  org="org+$(date +%s)@example.com"
  reg=$(curl -fsS --max-time 5 -H 'Content-Type: application/json' \
    -d "{\"email\":\"$org\",\"password\":\"smokepassword123\",\"display_name\":\"Organizer\"}" \
    "$AUTH/api/auth/signup" 2>/dev/null || true)
  tok=$(printf '%s' "$reg" | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')
  if [ -z "$tok" ]; then
    bad "catalog: could not obtain an auth token [$reg]"
  else
    ev=$(curl -fsS --max-time 5 -H "Authorization: Bearer $tok" -H 'Content-Type: application/json' \
      -d '{"title":"Jazz au Studio des Arts","description":"Une soiree jazz.","venue_name":"Studio des Arts","venue_city":"Casablanca","starts_at":"2030-01-01T20:00:00Z"}' \
      "$CATALOG/api/catalog/events" 2>/dev/null || true)
    eid=$(printf '%s' "$ev" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')
    slug=$(printf '%s' "$ev" | sed -n 's/.*"slug":"\([^"]*\)".*/\1/p')
    if [ -z "$eid" ]; then
      bad "catalog: event creation returned no id [$ev]"
    else
      ok "catalog: organizer created a draft event (auth token verified via JWKS)"
      tier=$(curl -fsS --max-time 5 -H "Authorization: Bearer $tok" -H 'Content-Type: application/json' \
        -d '{"name":"Standard","price_cent":15000,"quantity":100,"max_per_order":4,"sale_starts_at":"2029-01-01T00:00:00Z","sale_ends_at":"2030-01-01T19:00:00Z"}' \
        "$CATALOG/api/catalog/events/$eid/tiers" 2>/dev/null || true)
      tid=$(printf '%s' "$tier" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')
      pub=$(curl -fsS --max-time 5 -o /dev/null -w '%{http_code}' -X POST \
        -H "Authorization: Bearer $tok" "$CATALOG/api/catalog/events/$eid/publish" 2>/dev/null || true)
      if [ "$pub" = "200" ]; then ok "catalog: draft → published"; else bad "catalog: publish returned $pub"; fi
      if check_http "$CATALOG/api/catalog/events/$slug"; then
        ok "catalog: public event detail by slug"
      else
        bad "catalog: public detail by slug failed"
      fi
      # /internal is reachable directly only because the gateway does not exist
      # yet; once it lands, this path is off the public edge (D3, §3.2 r2).
      if [ -n "$tid" ] && check_http "$CATALOG/internal/tiers/$tid"; then
        ok "catalog: GET /internal/tiers/{id} (booking's read path)"
      else
        bad "catalog: internal tier lookup failed"
      fi
    fi
  fi
else
  echo "  -- skip catalog auth round-trip (curl not installed)"
fi

echo "==========================================================="
printf 'smoke: %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
