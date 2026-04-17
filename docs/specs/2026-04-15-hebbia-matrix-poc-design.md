# Hebbia Matrix PoC — Design Spec

**Date:** 2026-04-15
**Author:** Anup Roy 
**Status:** Draft for review
**Target:** Working PoC of a Hebbia-Matrix-style spreadsheet-on-documents UI over FinanceBench 10-K / earnings PDFs, with a swappable retrieval core (Naive / ISD / per-doc Wiki) and a reproducible benchmark harness.

---

## 1. Product summary

A web app that turns a folder of PDFs plus a set of prompts into a filled spreadsheet:

- **Rows = documents** (10-Ks, earnings transcripts).
- **Columns = prompts** ("Revenue YoY change", "Material risks", "Auditor opinion", ...).
- **Cell (row_i, col_j) = the answer** for that prompt against that document, with inline citations (page + snippet + bbox) and a visible reasoning trace.
- **Synthesis panel** = cross-row aggregator ("summarise risks across all issuers", "rank by margin expansion") that cites back to filled grid cells.

The PoC must prove four things in order of importance:

1. The grid UX works: ingest → add column → watch cells stream in → click a cell and audit the answer against the PDF.
2. Per-cell quality beats naive top-k RAG on FinanceBench, measured by answer correctness and citation-page overlap.
3. A per-document "wiki" (structured pre-built representation) beats chunk-level retrieval on the same benchmark.
4. Everything is transparent: every factual claim is cited; every cell exposes its sub-questions, evidence set, draft, and verifier report.

Karpathy's "LLM wiki" framing and the internal conversation about *belief-oriented* memory motivate the Tier-3 retrieval layer: retrieve against structured knowledge extracted from the document, not raw chunks.

---

## 2. Stack

### Frontend
- **React 18 + Vite + TypeScript**.
- **TanStack Table v8** for the matrix (headless; we own every pixel).
- **Tailwind CSS** + **shadcn/ui** primitives, customised for dark-first look.
- **Zustand** for client state (grid, focused cell, SSE subscription).
- **PDF.js** for the in-app PDF viewer with bbox overlays.
- **cmdk** for the ⌘K command palette.
- **Framer Motion** for state-machine cell animations.

### Backend
- **Python 3.11 + FastAPI**, fully async.
- **Uvicorn**, bound to `127.0.0.1` only. Azure keys in `.env`, never logged.
- **SQLite** via SQLModel; WAL mode for concurrent reads during cell streaming.
- **LanceDB** (embedded) for vector storage.
- **PyMuPDF** for text + layout + page anchors, **pdfplumber** for tables, **pytesseract** fallback for scanned pages.
- **Structured logging** (`structlog`, JSON) threaded by per-cell `trace_id` (ULID).

### Models
- **Chat**: Azure OpenAI deployment `gpt-4.1` (endpoint `https://api.core42.ai/`, api version `2024-10-21`).
- **Embeddings**: auto-detected at startup.
  - First choice: Azure `text-embedding-3-large` if the deployment exposes it.
  - Fallback: `BAAI/bge-large-en-v1.5` via `sentence-transformers` running locally.
  - The choice is locked for the lifetime of the process and written into `config.runtime.json` so indices aren't cross-contaminated.

### Storage layout (local disk)
```
storage/
  pdfs/{sha256}.pdf                # content-addressable, deduped
  parsed/{sha256}.json              # structured doc tree
  wikis/{sha256}__{wiki_v}.json.gz  # per-doc wiki, versioned
  vectors/                          # LanceDB tables
  traces/{cell_id}.json.gz          # gzipped ISD traces
  db/matrix.sqlite                  # SQLite
```

---

## 3. Architecture

Four stages — three offline (per-PDF, cached), one online (per-cell):

```
[1. INGEST]  PDF → structured parse (pages, sections, tables, chunks, bboxes)
[2. WIKI]    structured doc → per-doc wiki (entities, claims, metrics, section index)
[3. INDEX]   chunks + wiki nodes → embeddings in LanceDB
                       ────────────────────────────────
[4. QUERY]   per cell: decompose → ISD retrieve ↔ draft ↔ verify → answer + citations + trace
```

### Module boundaries
```
backend/
  parser/        # PDF → StructuredDoc. Pure, no LLM.
  wiki/          # StructuredDoc → DocWiki. LLM-driven, cached by (sha256, wiki_v).
  retriever/     # Protocol + 3 impls: NaiveRetriever, ISDRetriever, WikiRetriever.
  agent/         # ISD loop: decompose → retrieve → draft → verify → revise.
  synthesizer/   # Cross-row aggregator for the synthesis panel.
  jobs/          # Global async job queue with Azure TPM budget.
  llm.py         # Thin Azure wrapper: retries, 429 handling, cost logging, structured output.
  api/           # FastAPI routes + SSE.
  storage/       # SQLModel models + LanceDB glue.
  bench/         # FinanceBench harness (standalone CLI).
```

Everything behind `retriever/` is swappable. Same grid frontend, same ISD agent, different retriever implementations for benchmarking.

---

## 4. Structured parse (stage 1)

For each PDF produce one JSON "document tree":

```jsonc
{
  "doc_id": "sha256:...",
  "meta": { "company": "Apple Inc.", "filing_type": "10-K", "period_end": "2023-09-30" },
  "pages": [{ "page_no": 1, "text": "...", "bbox_blocks": [...] }],
  "sections": [{
    "id": "s-1", "title": "Item 1A. Risk Factors", "level": 2,
    "page_start": 12, "page_end": 34, "text": "...", "children": []
  }],
  "tables": [{ "id": "t-1", "page": 42, "bbox": [...], "rows": [[...]], "caption": "...", "markdown": "..." }],
  "chunks": [{
    "id": "c-1", "section_id": "s-1", "page": 13,
    "text": "...", "token_count": 487,
    "bboxes": [{ "page": 13, "bbox": [x0, y0, x1, y1] }]
  }]
}
```

**Section detection:** PyMuPDF `get_toc()` first. If absent or thin, heading heuristics (font-size + numbering: `Item 1`, `Item 1A`, `Part II`) with a domain hint for 10-Ks that boosts `Item N[A-Z]?` headings.

**Chunks:** split on section boundaries first, then pack into ~500-token windows with ~50-token overlap. Every chunk preserves `bboxes: [{page, bbox}]` as a list to handle multi-page tables and flowing paragraphs that span pages.

**OCR fallback:** a page with <30 characters of extractable text triggers `pytesseract` on the rendered page. Pages that still fail are flagged per-page in `pages[].ocr_failed` and excluded from retrieval; a warning is shown on the row in the UI.

**Parse meta-extraction:** the first 2-3 pages go to a single LLM call to extract `meta.company`, `filing_type`, `period_end` in JSON mode (structured output). Any failure surfaces as an editable row header in the UI rather than blocking ingest.

---

## 5. Per-doc Wiki (stage 2 — the Tier-3 IP)

The wiki is the key thesis: retrieve against *structured, pre-built knowledge* rather than raw chunks.

### 5.1 Per-section entries

For each section, one LLM call (gpt-4.1, JSON mode, schema-validated), parallelised with a global concurrency budget:

```jsonc
{
  "section_id": "s-7",
  "summary": "3-5 sentence summary",
  "entities": [{ "name": "iPhone", "type": "product", "mentions": ["c-42", "c-43"] }],
  "claims": [{ "text": "Revenue grew 2.8% YoY", "evidence_chunks": ["c-42"], "confidence": 0.9 }],
  "metrics": [{ "name": "revenue", "value": 383285, "unit": "USD_millions", "period": "FY2023", "chunk_id": "c-42" }],
  "questions_answered": ["what is total revenue", "how did revenue change YoY"]
}
```

### 5.2 Doc-level rollup

One extra LLM call per doc fuses section entries into:

```jsonc
{
  "doc_id": "sha256:...",
  "wiki_schema_version": 1,
  "overview": "...",
  "timeline": [{ "date": "...", "event": "...", "section_id": "s-N" }],
  "key_metrics_table": { "revenue": {...}, "net_income": {...}, "operating_margin": {...} },
  "entity_graph": [{ "from": "Apple", "to": "Foxconn", "relation": "supplier", "evidence": ["c-91"] }],
  "section_index": [{ "id": "s-N", "title": "...", "questions_answered": [...], "summary": "..." }]
}
```

### 5.3 Caching & invalidation

- Wiki files are stored as `storage/wikis/{sha256}__{wiki_schema_version}.json.gz`.
- Lookup is by `(sha256, wiki_schema_version)`. On schema bump, wikis are lazily rebuilt on next query; old files are kept for reproducibility of past benchmarks.
- The same PDF across workspaces yields the same wiki (content-addressable): Apple 10-K 2023 built once.
- Cost control: the Add Document flow shows an estimated `n_sections × ~1.2k tokens × 2 calls` preview before starting, with an opt-out "skip wiki, use naive retrieval" mode.

### 5.4 Retriever protocol

```python
class Evidence(TypedDict):
    chunk_id: str
    text: str
    page: int
    bboxes: list[Bbox]        # list, not single
    score: float              # retriever-assigned relevance
    source: str               # "wiki.metric", "wiki.claim", "chunk.vector", etc.

class Retriever(Protocol):
    async def retrieve(self, query: str, doc: Doc, k: int = 8) -> list[Evidence]: ...

class NaiveRetriever:    # vector top-k over chunks
class ISDRetriever:      # iterative agentic retrieval over chunks (no wiki)
class WikiRetriever:     # wiki.metrics/claims first → section drill-down → chunk vector fallback
```

All three implement the same interface, exposed through a config flag and a runtime switch in the UI. This is the surface the benchmark compares.

---

## 6. ISD loop (stage 4 — per cell)

One cell = one `CellJob(doc_id, column_id, prompt, shape_hint, column_version)`.

```
1. DECOMPOSE
   LLM call with: prompt + doc.meta + doc.section_index (from the wiki) →
     { sub_questions: [str], expected_answer_shape: "number|currency|percentage|text|list|table",
       target_sections: [section_id] }   // wiki-guided targeting
   Retry once on JSON parse failure with the parser error surfaced in the prompt.
   Second failure → cell fails with a diagnostic; no silent fallback.

2. GATHER (parallel over sub_questions, bounded by global budget)
   For each sub_q: evidence = retriever.retrieve(sub_q, doc, k=6)

3. DRAFT
   LLM call: prompt + sub_questions + all evidence (with chunk_ids) + shape schema →
     { answer: <matches shape>, citations: [chunk_id], reasoning_trace: [...] }
   Hard constraint in the prompt: every factual claim must cite ≥1 chunk_id.

4. VERIFY
   For each cited claim: re-retrieve(claim_text, doc, k=3) →
     verifier LLM call: "does this evidence support this claim?" →
       { supported | contradicted | missing, note }
   Any unsupported/contradicted → step 5; else step 6.

5. REVISE (max 1 retry)
   LLM call: draft + verifier notes + fresh evidence → revised answer.
   Goto VERIFY once more. Second failure → return with confidence=low
   and surface the specific claim in the trace.

6. RETURN CellResult {
     answer, answer_shape, citations: [{ chunk_id, page, snippet, bboxes }],
     trace: { sub_questions, evidence_sets, draft, verifier_report, revisions },
     confidence: high|medium|low, tokens_used, latency_ms,
     retriever_mode, column_version, trace_id
   }
```

### Budget and concurrency

- Per-cell: max 2 revise iterations, max tokens cap, max wall-clock 90s.
- Global: a single async job queue with an Azure TPM budget. `jobs/budget.py` implements a token-bucket allocator that ingest, wiki builds, ISD cells and synthesis all draw from. Prevents fan-out from saturating the deployment.
- 429 handling in `llm.py`: honour `retry-after`, exponential backoff with jitter, surface `rate_limited` in the UI without failing the cell.

### Structured outputs

All LLM calls that parse JSON use Azure structured-output mode with the exact Pydantic schema. On parse failure: one retry with the parser error in the user message. On second failure: raise, recorded with `trace_id`.

---

## 7. Synthesis (cross-row output)

Input: the filled cells (answers + citations) across the user-selected rows and columns.

The grid is serialised into a compact markdown table and handed to one LLM call with the synthesis prompt. Output is rendered below the grid in the Synthesis panel with citations of the form `[row×col]` that jump focus to the cited cell on click.

---

## 8. Frontend — premium layout

### 8.1 Design system

- **Theme**: dark-first. Canvas `zinc-950`; grid surfaces `zinc-900`; borders `zinc-800`; text primary `zinc-100`, meta `zinc-400`. Accent: emerald-500 (done), amber-400 (verifying), rose-500 (failed), sky-400 (streaming).
- **Type**: Inter Tight 13px for UI, 12px for meta; JetBrains Mono 12px for numbers, cell ids, citations.
- **Spacing**: 4pt base. Grid row height 36px. Top bar 44px. Cell padding 8px x.
- **Motion**: Framer Motion. Liquid shimmer on streaming cells (no spinners). 150ms ease for state transitions.

### 8.2 Layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│  ◇ Matrix · workspace name   gpt-4.1 · wiki mode   $0.42   ● live  ⌘K    │  44px glass top bar
├──────────────────────────────────────────────────────────────────────────┤
│  ┌── Matrix ────────────────────────────────────────────────────────┐    │
│  │  ⌘   Document            Revenue YoY    Material risks   Auditor │    │  sticky header
│  │  ●   AAPL 10-K FY23      +2.8% ⓘ        Supply chain…    EY      │    │  done row
│  │  ◐   MSFT 10-K FY23      ░streaming░    —                —       │    │  streaming row
│  │  ○   + Add document                                              │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│  ┌── Synthesis (collapsible) ──────────────────────────────────────┐    │
│  │  Across these three issuers, revenue growth diverged… [A2][C2]  │    │
│  └──────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘

Focus mode (cell opened): grid shrinks to 60%, right 40% = cell pane.
```

### 8.3 Cell states

Every cell carries a state machine visible as a leading coloured dot + shimmer bar under the value:

`idle · queued · retrieving · drafting · verifying · done · stale · failed`

`stale` appears when the column prompt has been edited and the cell's stored `column_version` is older — shown with a ghost value + "rerun" affordance.

### 8.4 Cell renderers by shape

The column declares a `shape_hint`. Cell renderers dispatch:

- **number / currency / percentage** — right-aligned, monospaced, formatted. Small unit/period caption under the value.
- **text** — left-aligned, truncated at 180 chars with `…` and an expand chip.
- **list** — first 2 bullets inline, `+N more` chip.
- **table** — compact 3×3 preview with "expand" into the focus pane.

### 8.5 Focus pane (replaces drawer)

Right 40% split when a cell is focused:

- Answer (large, shape-rendered) + confidence meter (●●●○).
- Sub-questions list.
- Evidence list with page, snippet, score, source tag (`wiki.metric`, `chunk.vector`, ...).
- PDF.js viewer with bbox overlays for cited evidence; click a citation pill → viewer scrolls to the page and flashes the bbox.
- Collapsible reasoning trace (raw LLM outputs + verifier report).
- Actions: rerun, copy answer, copy citation, pin to synthesis.

### 8.6 Interactions

- **⌘K command palette** (cmdk): Add column · Add documents · Switch retriever mode · Run benchmark · Export grid · Toggle focus mode · Open template pack.
- **Keyboard**: arrows navigate cells, Enter opens focus, Esc closes, `R` reruns focused cell, `⌘Enter` runs column, `⌘⇧Enter` runs whole grid, `/` opens search, `F` toggles focus-mode demo chrome.
- **Column header**: prompt preview (truncated) + shape icon + inline edit. Editing bumps `column.version`, downstream cells become `stale`.
- **Pin / freeze / reorder / resize** columns and rows. Doc column freezes by default.
- **Empty state**: centred card with "Drop PDFs or start from a template". Templates: Risk extraction · Revenue & margins · Auditor & governance — each seeds 4-6 columns.
- **Cost preview modal** on "Add column": estimated tokens × rows × $/1M. Confirm or cancel before run.

### 8.7 Streaming protocol

- One SSE connection per open grid: `GET /api/grids/{id}/stream`.
- Events are JSON: `{ type: "cell", cell_id, state, delta?, result? }`.
- Each event has a monotonic `Last-Event-ID`. On reconnect the client sends it back; server replays missed events from the DB journal, then subscribes to live.
- If the browser closes mid-run, jobs continue server-side (DB is source of truth). Reopening the grid pulls the current snapshot then resumes the live stream.

---

## 9. Data model (SQLite)

```
workspaces(id, name, created_at)

documents(id, workspace_id, filename, sha256, status, n_pages, meta_json,
          parsed_path, wiki_path, wiki_schema_version, created_at)

grids(id, workspace_id, name, retriever_mode, created_at)

columns(id, grid_id, position, prompt, shape_hint, target_sections_json,
        version, created_at, updated_at)

rows(id, grid_id, document_id, position)

cells(id, grid_id, row_id, column_id, column_version,
      status, answer_json, citations_json, confidence,
      tokens_used, latency_ms, retriever_mode, trace_id, trace_path,
      updated_at)

runs(id, cell_id, retriever_mode, column_version,
     started_at, finished_at, status, error, tokens_used)

synthesis(id, grid_id, prompt, answer, citations_json, created_at)

jobs(id, kind, payload_json, priority, status, tokens_reserved,
     created_at, started_at, finished_at, error)
```

- Cells are the source of truth. Traces live on disk keyed by `trace_id` (ULID) to keep SQLite small.
- `cells.column_version` together with `columns.version` makes staleness explicit. A newer `columns.version` → client marks cells stale → user can batch-rerun.
- `jobs` queue is persisted so restarts resume in flight work.

---

## 10. FinanceBench benchmark harness

`bench/run.py` is a standalone CLI. Flow:

1. Load questions from HuggingFace dataset `PatronusAI/financebench` (`question`, `answer`, `evidence_text`, `page_number`, `doc_name`).
2. Resolve doc PDFs via the Patronus GitHub mirror; download on first use; dedup by sha256 into `storage/pdfs/`.
3. Ingest referenced PDFs through the production pipeline (parse + wiki + index). Wiki build is skipped for `--mode naive`.
4. For each `--mode in {naive, isd, wiki}`, run every question as a one-cell ISD job against the correct doc.
5. Score:
   - **Answer correctness**: LLM-as-judge (gpt-4.1) given question, gold answer, and model answer → `{correct, partially_correct, incorrect}` with rationale. Standard FinanceBench protocol.
   - **Citation page recall**: fraction of gold pages covered by the model's cited pages.
   - **Citation precision**: fraction of cited pages that appear in the gold page set (or adjacent ±1 page).
   - **Cost** (tokens × $/1M) and **latency** per question.
6. Emit `bench/results/{ts}/{mode}.jsonl` + a markdown comparison table. Also emits a per-question diff so failures are inspectable.

A 50-question subset (`--subset smoke`) is cheap enough to run on PRs that touch retrieval; full runs are manual.

---

## 11. Risks, gaps, mitigations

| Risk | Mitigation |
|------|------------|
| Azure TPM saturation on large grids | Global async job queue with token-bucket budget in `jobs/budget.py`; per-request retries with `retry-after`. |
| Wiki build cost per 10-K ($2-5) | Content-addressable cache keyed by `(sha256, wiki_schema_version)`; optional "skip wiki" mode; cost preview before column runs. |
| Embeddings endpoint not deployed on the Azure account | Auto-detect at startup; fall back to local `bge-large-en-v1.5`; locked per-process in `config.runtime.json`. |
| Multi-page tables break single-bbox citations | Citations carry `bboxes: [{page, bbox}]` list; the viewer highlights each. |
| Prompt edits invalidate historical answers | Explicit `columns.version` / `cells.column_version`; UI shows stale chip + one-click rerun. |
| LLM returns malformed JSON | Structured-output mode + schema validation + 1 retry with parse error surfaced; explicit fail on second attempt. |
| Browser disconnect mid-run loses progress | DB is source of truth; SSE reconnect with `Last-Event-ID`; jobs continue server-side. |
| Cell answers too long for a grid cell | 180-char truncation + expand chip; shape-specific renderers (number, currency, %, list, table). |
| Scanned-PDF pages yield empty text | OCR fallback; per-page flags; row warning instead of silent failure. |
| FinanceBench PDFs are large (tens of GB) | Lazy download on first use; content-addressable dedup; never committed to git. |
| Azure key exposure | `.env` only, not checked in; FastAPI binds `127.0.0.1`; logs scrubbed. |
| Wiki schema drift over the project | `wiki_schema_version` field; lazy rebuild on bump; old wikis retained for past benchmarks. |
| Silent retrieval regressions | Retriever contract tests with a fixed eval set asserting minimum accuracy. |

---

## 12. Testing strategy

- **Unit**: parser (fixture PDFs with known sections/tables), wiki JSON schema validation, each retriever against canned docs, verifier against adversarially hallucinated drafts, LLM wrapper (retries, rate limits, structured output retries).
- **Integration**: end-to-end ingest → wiki → cell on 2-3 small 10-Ks checked into `tests/fixtures/`.
- **Contract tests** for the `Retriever` protocol: same interface, same eval set, asserts a minimum accuracy floor; refactors can't silently regress.
- **Benchmark smoke** (50 FinanceBench questions) runnable locally in under 5 minutes on `wiki` mode; full runs are manual.

---

## 13. Out of scope (explicit)

- Auth, multi-user, realtime collab.
- Multi-modal vision over charts/images; we extract table text only.
- Agent training / self-improving decomposition from past actions.
- Annotation drawing in the PDF viewer beyond page-level bbox highlights.
- Production deploy, Docker, full CI pipeline beyond local `pnpm dev` + `uvicorn`.
- Cloud-hosted demo — local-only for the PoC.

---

## 14. Milestones (sequencing, not dates)

1. **Skeleton**: FastAPI + Vite + SQLite + SSE + grid renders an empty matrix.
2. **Ingest**: PDF → structured doc tree + OCR fallback + meta extraction + ingest progress in UI.
3. **Naive retriever + ISD loop**: cells stream in end-to-end on one toy 10-K with one column.
4. **Wiki builder**: per-doc wiki built on ingest, cached; WikiRetriever implemented.
5. **Focus pane + PDF.js viewer** with bbox highlights; citation pills linked.
6. **Synthesis panel**, column versioning / staleness, ⌘K palette, command shortcuts.
7. **FinanceBench harness**: smoke run on 50 questions across all three retriever modes; markdown comparison table emitted.
8. **Polish pass**: empty state, template packs, cost preview modal, focus mode, performance tune.

Each milestone is independently demoable.

---

## 15. Open questions for the user

None blocking. To confirm during implementation:

- Exact Azure embeddings availability (decided at first startup).
- Which three FinanceBench issuers to pin as the demo rows (suggest AAPL / MSFT / NVDA FY23).
- Whether the synthesis panel should also accept free-form cross-row questions beyond "summarise the grid" in the PoC scope.
