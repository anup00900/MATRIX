"""Test configuration: ensure required env vars exist so `app.settings` imports.

The real `.env` at the repo root supplies `AZURE_OPENAI_API_KEY` in production.
For tests we set a dummy value (only if not already present) so that importing
`app.settings` does not ValidationError. Tests must NOT make real network calls;
they patch `LLM._chat_raw` instead.
"""
import os

os.environ.setdefault("AZURE_OPENAI_API_KEY", "test-dummy-key")
# tiktoken cache dir: avoids network + SSL issues for cl100k_base encoding
os.environ.setdefault("TIKTOKEN_CACHE_DIR", "/tmp/tiktoken_cache")
# HuggingFace / sentence-transformers downloads: disable telemetry and
# allow fallback to system CA certs when corporate MITM interferes.
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
# Corporate MITM proxy blocks huggingface.co SSL verification. If the model
# is already present in the local cache, force offline mode so we don't try
# to hit the network at all. Tests must therefore rely on a pre-cached model.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
# Work around SSL cert verify failures for huggingface.co behind corp proxies.
# certifi is used by default; if the system python openssl can't validate,
# try the certifi bundle explicitly.
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    os.environ.setdefault("CURL_CA_BUNDLE", certifi.where())
except Exception:
    pass
