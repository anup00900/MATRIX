.PHONY: dev backend frontend test lint
dev:
	@echo "Run 'make backend' and 'make frontend' in two terminals."
backend:
	cd backend && . .venv/bin/activate && \
	TIKTOKEN_CACHE_DIR=/tmp/tiktoken_cache \
	HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
	SSL_CERT_FILE=$$(python -c 'import certifi; print(certifi.where())') \
	REQUESTS_CA_BUNDLE=$$(python -c 'import certifi; print(certifi.where())') \
	uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
frontend:
	cd frontend && pnpm dev
test:
	cd backend && . .venv/bin/activate && pytest -v
lint:
	cd backend && . .venv/bin/activate && ruff check app tests
	cd frontend && pnpm tsc --noEmit
