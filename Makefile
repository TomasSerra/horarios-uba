.PHONY: up down restart logs ps psql scrape vacantes vacantes-dry reset test install-test-deps install-hooks help

DC := docker compose
VENV := backend/.venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest

# Comando único: levanta DB + API + Frontend; siembra la DB si está vacía.
up:
	@$(DC) up -d --build db api frontend
	@echo "→ Esperando DB lista..."
	@until $(DC) exec -T db pg_isready -U postgres -d horarios >/dev/null 2>&1; do sleep 1; done
	@count=$$($(DC) exec -T db psql -U postgres -d horarios -tAc "SELECT COUNT(*) FROM cursos" 2>/dev/null || echo 0); \
	if [ "$$count" = "0" ]; then \
		echo "→ DB vacía, scrapeando (~2 min)..."; \
		$(DC) run --rm scraper; \
	else \
		echo "→ DB ya tiene $$count cursos."; \
	fi
	@echo ""
	@echo "✓ Stack listo:"
	@echo "  Frontend:  http://localhost:5173"
	@echo "  API:       http://localhost:8000"
	@echo "  Docs:      http://localhost:8000/docs"
	@echo "  DB:        postgresql://postgres:postgres@localhost:5437/horarios"

down:
	$(DC) down

restart: down up

logs:
	$(DC) logs -f api frontend

ps:
	$(DC) ps

psql:
	$(DC) exec db psql -U postgres -d horarios

scrape:
	$(DC) run --rm scraper

# Job horario que sólo actualiza cursos.vacantes. `vacantes-dry` no escribe nada
# (la transacción se abre READ ONLY), así que es seguro incluso contra prod.
# Flags extra por ARGS:  make vacantes-dry ARGS="--limit 5"
vacantes-dry:
	$(DC) run --rm scraper python -m scraper.vacantes --dry-run $(ARGS)

vacantes:
	$(DC) run --rm scraper python -m scraper.vacantes $(ARGS)

reset:
	$(DC) down -v
	$(MAKE) up

# Tests del backend: corren localmente con un venv en backend/.venv (no Docker).
# `make install-test-deps` lo crea idempotentemente. Tests puros: sin DB real.
install-test-deps:
	@if [ ! -x $(PY) ]; then \
		echo "→ Creando venv en $(VENV)..."; \
		python3 -m venv $(VENV); \
	fi
	@$(PIP) install --quiet --upgrade pip
	@$(PIP) install --quiet -r backend/requirements-dev.txt
	@echo "✓ Dev deps instaladas en $(VENV)"

test:
	@if [ ! -x $(PYTEST) ]; then \
		echo "⚠️  pytest no instalado. Corré primero: make install-test-deps"; \
		exit 1; \
	fi
	cd backend && ../$(PYTEST)

install-hooks:
	@mkdir -p .git/hooks
	@ln -sf ../../scripts/git-hooks/pre-commit .git/hooks/pre-commit
	@chmod +x scripts/git-hooks/pre-commit
	@echo "✓ Hook pre-commit instalado."
	@echo "  Saltearlo (no recomendado): git commit --no-verify"

help:
	@echo "Targets:"
	@echo "  make up                 - Levanta DB + API + Frontend; si la DB está vacía, la siembra"
	@echo "  make down               - Apaga containers (preserva datos)"
	@echo "  make restart            - down + up"
	@echo "  make reset              - Borra datos y vuelve a levantar desde cero"
	@echo "  make scrape             - Re-corre el scraper completo (idempotente)"
	@echo "  make vacantes-dry       - Diff de cupos sin escribir (READ ONLY, seguro contra prod)"
	@echo "  make vacantes           - Actualiza sólo cursos.vacantes"
	@echo "  make psql               - Abre psql contra la DB"
	@echo "  make logs               - Sigue logs de API + Frontend"
	@echo "  make ps                 - Lista containers"
	@echo "  make install-test-deps  - Crea venv en backend/.venv e instala pytest + deps"
	@echo "  make test               - Corre la suite de tests del backend (sin Docker)"
	@echo "  make install-hooks      - Instala el hook pre-commit que corre tests antes de commitear"
