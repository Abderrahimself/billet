# billet — the local platform interface (devops.md P1: "the Makefile is the
# only interface"). O1: compose is the P1–P3 runtime.
#
#   make up · down · test · seed · logs
#
SHELL := bash
COMPOSE_FILE := deploy/compose/docker-compose.dev.yml
ENV_FILE     := .env
COMPOSE      := docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE)
SMOKE        := deploy/compose/scripts/smoke.sh

.DEFAULT_GOAL := help
.PHONY: help up down test seed logs smoke ps nuke

help: ## show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-7s\033[0m %s\n", $$1, $$2}'

$(ENV_FILE):
	@cp .env.example $(ENV_FILE) \
	  && echo "created $(ENV_FILE) from .env.example (dev defaults — edit as needed)"

up: $(ENV_FILE) ## start backing services, wait for health, run smoke
	$(COMPOSE) up -d --wait
	@$(SHELL) $(SMOKE)

down: ## stop and remove containers (data volumes kept)
	$(COMPOSE) down

logs: ## follow logs from all backing services
	$(COMPOSE) logs -f

smoke: ## run the health smoke test against the running stack
	@$(SHELL) $(SMOKE)

ps: ## show container status
	$(COMPOSE) ps

test: ## run service test suites against real deps (testcontainers, O6)
	@shopt -s nullglob; found=0; \
	for svc in services/*/; do \
	  if [ -f "$$svc/pyproject.toml" ]; then \
	    found=1; echo "== pytest $$svc"; ( cd "$$svc" && uv run pytest ) || exit 1; \
	  fi; \
	done; \
	if [ "$$found" = 0 ]; then \
	  echo "no service test suites yet — services land in milestone A1 (mvp.md §3.1)"; \
	fi

seed: ## seed the 5 demo Moroccan events (DR-1) — needs catalog/booking (A1)
	@echo "seed needs the catalog + booking services (milestone A1) — not available yet"

nuke: ## stop everything and DELETE data volumes (full reset)
	$(COMPOSE) down -v
