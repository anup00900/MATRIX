# Matrix PoC

A Hebbia-Matrix-style spreadsheet over PDFs. Drop 10-Ks into a grid, define prompt columns, watch cells stream in with cited answers, synthesise across rows.

Three swappable retrievers: **naive** (vector top-k), **isd** (iterative source decomposition: sub-queries + section targeting + batched attention rerank), **wiki** (retrieves against a pre-built per-doc structured wiki). Benchmarked against FinanceBench.

## Stack

- **Backend**: Python 3.11+ · FastAPI · SQLModel (SQLite + WAL) · LanceDB · PyMuPDF · Azure OpenAI (`gpt-4.1` vision for parsing, chat for agents).
- **Frontend**: React 18 · Vite · TypeScript · TanStack Table · Tailwind v4 · cmdk · Framer Motion · PDF.js.
- **Vision-first parsing**: each page → PNG → `gpt-4.1` vision → clean markdown. No fragile text extraction.
- **Local embedding fallback**: `BAAI/bge-large-en-v1.5` via sentence-transformers if the Azure embedding deployment isn't exposed.

## One-time setup

```bash
cp .env.example .env       # then edit: set AZURE_OPENAI_API_KEY
cd backend && python3.11 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
cd ../frontend && pnpm install
```

The first backend test run downloads the `bge-large-en-v1.5` model (~1.3 GB, HuggingFace cache). Subsequent runs use the cache with `HF_HUB_OFFLINE=1`.

## Run the app

Two terminals:

```bash
make backend     # http://127.0.0.1:8000 — FastAPI + SSE
make frontend    # http://127.0.0.1:5173 — Vite dev server
```

Open the frontend. ⌘K opens the command palette:

- **Add documents** — drop PDFs, rows appear as wikis finish building.
- **Add column** — type a prompt; cells stream in per row.
- **Template pack** — seeds 4 starter columns (Risk, Revenue & margins, Auditor & governance).
- **Switch retriever** — naive / isd / wiki at runtime.

Click a cell → focus pane shows the answer, confidence meter, citation pills, PDF viewer with bbox highlight, and reasoning trace stub.

## Benchmark

```bash
cd backend && . .venv/bin/activate
python -m app.bench.run --modes naive,isd,wiki --limit 50 --out bench/results/run1
cat bench/results/run1/report.md
```

Output: JSONL per mode + a markdown comparison table with correctness (LLM-judge), citation page recall / precision (±1 tolerance), latency, tokens.

## Tests

```bash
make test        # 23 tests, all hermetic (no real network)
```

## Layout

```
backend/
  app/
    agent/          # decompose → draft → verify → revise cell loop
    api/            # FastAPI routes + SSE
    bench/          # FinanceBench harness
    jobs/           # token-bucket budget
    parser/         # vision PDF → markdown → sections+chunks
    retriever/      # naive, isd (w/ attention rerank), wiki
    services/       # ingest, events, cell jobs, synthesis
    storage/        # SQLModel tables
    wiki/           # per-doc wiki builder (section entries + rollup)
frontend/
  src/
    api/            # client + types
    components/     # TopBar, Matrix, Cell, CellRenderer, CommandBar, FocusPane, PdfView, SynthesisDock
    store/          # zustand grid store
docs/
  superpowers/
    specs/          # design spec
    plans/          # implementation plan
    progress.md     # phase-by-phase log
```

## Design docs

- `docs/superpowers/specs/2026-04-15-hebbia-matrix-poc-design.md` — architecture, ISD engine, wiki, premium UI, benchmark, risks.
- `docs/superpowers/plans/2026-04-15-hebbia-matrix-poc-implementation.md` — TDD-shaped implementation plan.
