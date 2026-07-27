.PHONY: help install migrate revision api worker test test-pg lint format front-dev front-build up down logs

VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Crée l'environnement Python et installe les dépendances
	python3 -m venv $(VENV)
	$(PIP) install -U pip wheel
	$(PIP) install -r backend/requirements.txt
	$(PIP) install pytest pytest-asyncio httpx ruff

migrate: ## Applique les migrations
	cd backend && ../$(PY) -m alembic upgrade head

revision: ## Génère une migration (make revision m="ajout de X")
	cd backend && ../$(PY) -m alembic revision --autogenerate -m "$(m)"

api: ## Lance l'API en rechargement automatique
	cd backend && ../$(PY) -m uvicorn app.main:app --reload --port 8000

worker: ## Lance le worker d'imagerie
	cd backend && ../$(PY) -m celery -A app.workers.celery_app.celery_app worker -Q imaging --loglevel=info

worker-publish: ## Lance le worker de publication (navigateur)
	cd backend && ../$(PY) -m celery -A app.workers.celery_app.celery_app worker -Q publish -c 1 --loglevel=info

beat: ## Lance l'ordonnanceur (synchro ventes, relances, santé)
	cd backend && ../$(PY) -m celery -A app.workers.celery_app.celery_app beat --loglevel=info

seed: ## Charge les référentiels plateformes (idempotent)
	cd backend && ../$(PY) scripts/seed_referentials.py

calibrate-vinted: ## Vérifie les sélecteurs Vinted (make calibrate-vinted id=<account_id>)
	cd backend && ../$(PY) scripts/calibrate_vinted.py $(id)

test: ## Suite de tests sur SQLite (rapide, sans service externe)
	cd backend && ../$(PY) -m pytest

test-pg: ## Même suite sur PostgreSQL, migrations Alembic comprises
	cd backend && TEST_DATABASE_URL=postgresql+psycopg://ziia:ziia@127.0.0.1:5432/ziia_test \
		DATABASE_URL=postgresql+psycopg://ziia:ziia@127.0.0.1:5432/ziia_test ../$(PY) -m pytest

lint: ## Analyse statique
	cd backend && ../$(VENV)/bin/ruff check app tests

format: ## Reformate le code
	cd backend && ../$(VENV)/bin/ruff format app tests

front-dev: ## Lance le front en développement
	cd frontend && npm run dev

front-build: ## Compile le front
	cd frontend && npm run build

up: ## Démarre la pile complète
	docker compose up --build -d

down: ## Arrête la pile
	docker compose down

logs: ## Suit les journaux
	docker compose logs -f api worker-imaging
