# Hebbia Matrix PoC — Progress Log

## Completed phases

### Phase 0: Repo scaffold ✅
- Commits: `7c2b020`, `7dcd7af`, `ca266a6`
- Backend (FastAPI/SQLite/LanceDB) + Frontend (Vite/React/TS) scaffolded
- `.env.example`, `.env` (gitignored), Makefile
- Known deviations: Python 3.13 (not 3.11), Node 22, Tailwind v4 (hand-rolled config)
- `storage/` gitignore scoped to `/storage/` (repo root only)

### Phase 1: Shared infra ✅
- Commits: `ca789cd` (settings+logging), `2ce517a` (LLM), `0af9998` (budget)
- `app/settings.py` — pydantic-settings with Azure config
- `app/logging.py` — structlog JSON output
- `app/llm.py` — `LLM` class: `chat()`, `structured()` with schema-retry, `vision_chat()` (added in P3)
- `app/jobs/budget.py` — TokenBudget (async lock released before sleep)
- 3 tests passing; conftest.py seeds `AZURE_OPENAI_API_KEY` with setdefault
- **Follow-up for Phase 7:** `env_file=".env"` is CWD-relative; uvicorn from `backend/` will fail. Fix before Phase 7.

### Phase 2: Storage layer ✅
- Commit: `30ea807`
- 7 SQLModel tables: Workspace, Document, Grid, Column, Row, Cell, Synthesis
- WAL mode enabled via `PRAGMA journal_mode=WAL`
- `db.py` uses deferred `_make_engine()` + engine reassign in `init_db` to allow test isolation
- 4 tests passing

### Phase 3: Vision-based PDF parser ✅
- Commits: `ff74d77` (parser), `ff45aea` (meta)
- **Replaced PyMuPDF text extraction with gpt-4.1 vision** (user-directed pivot)
- `app/llm.py::vision_chat` — base64 PNG data URL → markdown
- `app/parser/pdf.py` — `async parse_pdf(path)`: renders pages at 150 DPI, sends to vision, stitches markdown into sections + chunks
- Concurrency: `asyncio.Semaphore(4)`
- `app/parser/schema.py` simplified: `pages[].markdown` (not `text`), page-level bboxes only, no Table model
- `app/parser/meta.py` — extracts company/filing_type/period_end from first 3 pages markdown
- `tests/fixtures/tiny.pdf` — 3-page deterministic fixture
- `conftest.py`: `TIKTOKEN_CACHE_DIR` + HF offline env vars
- 6 tests passing

### Phase 4: Retrievers (Naive + ISD — initial thin version) 🟡
- Commits: `d000935` (embeddings), `69d9b42` (naive), `f89891c` (ISD thin)
- `app/retriever/types.py` — Evidence + Retriever Protocol
- `app/retriever/embeddings.py` — Azure auto-detect → local `BAAI/bge-large-en-v1.5` fallback
- `app/retriever/index.py` — LanceDB per-doc table, content-addressable
- `app/retriever/naive.py` — vector top-k
- `app/retriever/isd.py` — **INITIAL THIN VERSION** (just decompose + gather); needs upgrade
- 9 tests passing

### Phase 4 ISD upgrade (in progress)
- Replacing thin ISD with Hebbia-flavored:
  1. Decompose: sub-queries + target_section_ids from section index
  2. Gather: embedding top-k per sub-query, dedup, 0.5x boost for in-target chunks, keep top 30 as attention pool
  3. **Attention rerank**: one batched LLM call scores all candidates 0-1 → distance = 1 - attn
- Public schemas: `DecompPlan`, `ChunkScore`, `RerankResult`
- Two LLM calls per retrieve() regardless of pool size
- Tests: end-to-end (both passes fire once) + section-targeting pulls in-target chunk

## Pending phases
- Phase 5: Per-doc Wiki + WikiRetriever (Tier-3 IP)
- Phase 6: ISD agent cell loop (decompose → draft → verify → revise)
- Phase 7: FastAPI + SSE (fix env_file first)
- Phase 8: Premium frontend
- Phase 9: Synthesis + templates
- Phase 10: FinanceBench harness
- Phase 11: Polish + smoke

## Decisions and deviations
- Python 3.13 instead of 3.11
- Tailwind v4 (init CLI removed, hand-rolled config)
- Vision-based parsing (user directive) — ~$1-2 per 10-K, page-level citations only
- HF offline mode required in conftest due to MITM cert issue
- ISD upgraded from simple decompose-and-gather to full decompose/target/rerank pattern
