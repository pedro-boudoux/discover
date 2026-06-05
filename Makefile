# Local development helpers for the Underground Music Discovery app.
# Typical loop (three terminals):
#   make db        # 1. start Postgres + pgvector (once)
#   make api       # 2. backend at http://localhost:8000  (auto-reload)
#   make web       # 3. frontend at http://localhost:5173 (auto-reload)
#
# Other targets:
#   make db-down   # stop the DB (keeps data)
#   make db-reset  # wipe the DB and recreate it from scratch
#   make test      # run the backend test suite
#   make install   # install backend + frontend dependencies

VENV ?= .venv

.PHONY: db db-down db-reset api web test install

db:
	docker compose up -d
	@echo "Postgres + pgvector is up on localhost:5432"

db-down:
	docker compose down

db-reset:
	docker compose down -v
	docker compose up -d
	@echo "Database wiped and recreated."

api:
	$(VENV)/bin/uvicorn app.main:app --reload --port 8000

web:
	cd frontend && npm run dev

test:
	$(VENV)/bin/pytest -q

install:
	$(VENV)/bin/pip install -r requirements.txt -r requirements-dev.txt
	cd frontend && npm install
