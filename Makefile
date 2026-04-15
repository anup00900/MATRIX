.PHONY: dev backend frontend test lint
dev:
	@echo "Run 'make backend' and 'make frontend' in two terminals."
backend:
	cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
frontend:
	cd frontend && pnpm dev
test:
	cd backend && . .venv/bin/activate && pytest -v
lint:
	cd backend && . .venv/bin/activate && ruff check app tests
	cd frontend && pnpm tsc --noEmit
