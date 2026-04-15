"""Test configuration: ensure required env vars exist so `app.settings` imports.

The real `.env` at the repo root supplies `AZURE_OPENAI_API_KEY` in production.
For tests we set a dummy value (only if not already present) so that importing
`app.settings` does not ValidationError. Tests must NOT make real network calls;
they patch `LLM._chat_raw` instead.
"""
import os

os.environ.setdefault("AZURE_OPENAI_API_KEY", "test-dummy-key")
