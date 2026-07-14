PY := backend/.venv/bin/python
UVICORN := backend/.venv/bin/uvicorn

.PHONY: setup dev api ui worker migrate test

setup:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd frontend && npm install

dev: ## run API (+in-process worker) and UI together
	@trap 'kill 0' INT TERM; \
	(cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000) & \
	(cd frontend && npm run dev) & \
	wait

api:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

ui:
	cd frontend && npm run dev

worker: ## standalone worker (set RUN_WORKER=0 on the API when using this)
	cd backend && .venv/bin/python -m app.worker

migrate:
	cd backend && .venv/bin/python -c "import asyncio; from app import db; print(asyncio.run(db.migrate()) or 'up to date')"

test:
	cd backend && .venv/bin/python -m pytest tests -q
