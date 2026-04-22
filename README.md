# MATRIX

> Hebbia Matrix style spreadsheet over PDFs. Drop financial filings, define prompt columns, watch cells stream answers with inline citations. Three swappable retrievers. FinanceBench benchmark harness.

## Overview

Matrix turns unstructured PDFs into a structured, queryable grid. Each row is a document, each column is a prompt, each cell streams an answer with citations linking back to the exact PDF page.

Under the hood: **vision based parsing** (gpt 4.1 renders each page to markdown), **three swappable retriever tiers**, a **per cell ISD agent** that decomposes, drafts, verifies, and revises every answer, and a **per document Wiki** that pre extracts structured knowledge at ingest for high precision retrieval.

---

## Architecture

```mermaid
flowchart LR
  subgraph FE["Frontend · React + Vite"]
    UI["Matrix Grid"]
    ASK["AskBar · prompt→columns"]
    CMD["⌘K Palette"]
    FOC["Focus Pane + PDF.js"]
    FLOW["3D Pipeline Viz"]
    SSE_C["SSE Client"]
  end

  subgraph BE["Backend · FastAPI"]
    API["REST Routes"]
    SSEB["SSE Publisher"]
    INGEST["Ingest Service"]
    CELLJOB["Cell Job Runner"]
    SUGGEST["Column Suggester"]
    SYN["Synthesis Service"]
    EXPORT["CSV / JSON Export"]
  end

  subgraph CORE["Core Pipeline"]
    PARSE["Vision Parser\ngpt 4.1 vision"]
    WIKI["Wiki Builder"]
    IDX["LanceDB Index"]
    AGENT["ISD Agent\ndecompose→draft→verify"]
    RET{"Retriever"}
    RET_N["Naive\nvector top k"]
    RET_I["ISD\ndecompose + attention rerank"]
    RET_W["Wiki\nmetric / claim first"]
  end

  subgraph STORE["Storage"]
    SQLITE[("SQLite + WAL")]
    DISK[("storage/\npdfs · parsed · wikis\nvectors · traces")]
  end

  subgraph LLM["Azure OpenAI"]
    GPT["gpt 4.1"]
    EMB["text-embedding-3-large\n→ local bge-large fallback"]
  end

  UI --> API
  ASK --> SUGGEST
  CMD --> API
  FOC --> API
  API --> SSEB
  SSEB -.SSE.-> SSE_C
  SSE_C -.updates.-> UI

  API --> INGEST
  API --> CELLJOB
  API --> SYN
  API --> EXPORT

  INGEST --> PARSE --> WIKI --> IDX
  CELLJOB --> AGENT --> RET
  RET --> RET_N
  RET --> RET_I
  RET --> RET_W

  PARSE -.vision.-> GPT
  WIKI -.structured.-> GPT
  AGENT -.chat+structured.-> GPT
  SUGGEST -.structured.-> GPT
  SYN -.chat.-> GPT
  IDX -.embeddings.-> EMB
  RET_N -.query embed.-> EMB
  RET_I -.query embed + rerank.-> GPT

  API <--> SQLITE
  PARSE --> DISK
  WIKI --> DISK
  IDX --> DISK
  AGENT --> DISK
```

---

## Per Cell Query Flow (ISD Loop)

Every `(row, column)` cell runs this pipeline:

```mermaid
sequenceDiagram
  autonumber
  participant UI as Frontend
  participant API as FastAPI
  participant Job as Cell Job
  participant Dec as Decompose
  participant Ret as Retriever
  participant Drf as Draft
  participant Ver as Verify
  participant SSE as SSE Bus

  UI->>API: POST /columns (prompt)
  API-->>UI: 200 column created
  API->>Job: create_task(run_cell_job)
  Job->>SSE: state=retrieving
  SSE-->>UI: cell event (blue dot)
  Job->>Dec: decompose(prompt, doc meta, section index)
  Dec-->>Job: sub_questions, target_sections, shape
  loop each sub question
    Job->>Ret: retrieve(sub_q, doc, k=6)
    Ret-->>Job: evidence chunks
  end
  Job->>SSE: state=drafting
  Job->>Drf: draft(prompt, evidence, shape)
  Drf-->>Job: answer + citations + reasoning trace
  Job->>SSE: state=verifying
  Job->>Ver: verify(draft, retriever, doc)
  Ver-->>Job: supported / contradicted / missing per claim
  alt any unsupported claim
    Job->>Ret: re-retrieve(failing claim)
    Job->>Drf: revise with verifier notes
    Job->>Ver: verify again
  end
  Job->>SSE: state=done + answer + citations
  SSE-->>UI: cell turns green
```

---

## Ingest Pipeline (Vision First)

```mermaid
flowchart TB
  PDF["PDF upload"] --> SHA["sha256 hash\ncontent addressable"]
  SHA --> DEDUP{"cached?"}
  DEDUP -->|yes| REUSE["reuse parsed + wiki"]
  DEDUP -->|no| WRITE["storage/pdfs/sha.pdf"]
  WRITE --> RENDER["PyMuPDF render\n150 DPI PNG per page"]
  RENDER --> VISION["gpt 4.1 vision\nPNG → markdown\nconcurrency = 4"]
  VISION --> STITCH["detect sections\nchunk ~500 tokens"]
  STITCH --> META["meta extraction\ncompany · filing type · period"]
  META --> INDEX["embed chunks\nLanceDB write"]
  INDEX --> WIKI_BUILD
  subgraph WIKI_BUILD["Wiki Builder"]
    WSEC["per section LLM call\nentities · claims · metrics"]
    WROLL["doc rollup LLM call\noverview · key_metrics_table"]
    WSEC --> WROLL
  end
  WIKI_BUILD --> PERSIST["storage/wikis/sha__v1.json.gz"]
  PERSIST --> READY["Document.status = ready\nSSE event → UI progress bar"]
```

---

## Three Retriever Tiers

```mermaid
flowchart LR
  Q["query"] --> MODE{"retriever mode"}

  MODE -->|naive| N1["embed query"]
  N1 --> N2["LanceDB top k"]
  N2 --> NOUT["evidence\nsource = chunk.vector"]

  MODE -->|isd| I1["Decompose LLM\nsub queries + target sections"]
  I1 --> I2["per sub query\nvector top k"]
  I2 --> I3["dedup + 0.5x boost\nfor in-target chunks"]
  I3 --> I4["Attention Rerank LLM\nscore every candidate 0 to 1"]
  I4 --> IOUT["evidence\nsource = chunk.isd\nsorted by attention"]

  MODE -->|wiki| W1["scan DocWiki\nkey_metrics + claims"]
  W1 --> W2["token overlap score\nvs metric / claim text"]
  W2 --> W3{"hits >= k?"}
  W3 -->|yes| WOUT["evidence\nsource = wiki.metric\nor wiki.claim"]
  W3 -->|no| W4["topup via naive\nvector fallback"]
  W4 --> WOUT
```

---

## Cell State Machine

```mermaid
stateDiagram-v2
  [*] --> idle
  idle --> queued : column added / row added
  queued --> retrieving : job picked up
  retrieving --> drafting : evidence gathered
  drafting --> verifying : draft produced
  verifying --> done : all claims supported
  verifying --> drafting : contradicted (max 1 revise)
  done --> stale : column prompt edited
  stale --> queued : user clicks rerun
  verifying --> failed : LLM error
  retrieving --> failed : retrieval error
  failed --> queued : rerun
```

---

## Data Model

```mermaid
erDiagram
  Workspace ||--o{ Document : owns
  Workspace ||--o{ Grid : owns
  Grid ||--o{ Column : has
  Grid ||--o{ Row : has
  Row }o--|| Document : references
  Grid ||--o{ Cell : has
  Cell }o--|| Row : "row position"
  Cell }o--|| Column : "column position"
  Grid ||--o{ Synthesis : produces

  Workspace { string id PK string name }
  Document { string id PK string sha256 string status int n_pages json meta_json }
  Grid { string id PK string name string retriever_mode }
  Column { string id PK int position string prompt string shape_hint int version }
  Row { string id PK int position string document_id FK }
  Cell { string id PK string status json answer_json json citations_json string confidence int tokens_used int latency_ms string trace_id }
  Synthesis { string id PK string prompt string answer }
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18 · Vite · TypeScript · Tailwind CSS v4 · TanStack Table |
| UI Components | cmdk (⌘K palette) · Framer Motion · Lucide · PDF.js · three.js |
| State | Zustand · SSE (Server Sent Events) |
| Backend | Python 3.11+ · FastAPI · Uvicorn · async everywhere |
| Database | SQLite (WAL mode) via SQLModel · LanceDB (embedded vectors) |
| PDF Parsing | PyMuPDF (render only) → gpt 4.1 vision → markdown |
| Embeddings | Azure text-embedding-3-large → local BAAI/bge-large-en-v1.5 fallback |
| LLM | Azure OpenAI gpt 4.1 (chat + vision + structured output) |
| Logging | structlog (JSON) · per cell trace_id (ULID) |
| Benchmark | FinanceBench (PatronusAI) · LLM as judge · citation page recall |

---

## Setup

  Terminal 1 — Backend:
  cd "/Users/anup.roy/Downloads/Hebbia POC" && make backend

  Terminal 2 — Frontend (needs Node 22, make frontend won't work due to Node 18):
  cd "/Users/anup.roy/Downloads/Hebbia POC/frontend" && PATH="$HOME/.local/node22/bin:$PATH"
  pnpm dev

  Then open http://localhost:5173
  
```bash
cp .env.example .env       # set AZURE_OPENAI_API_KEY
cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
cd ../frontend && pnpm install
```

## Run

Two terminals:

```bash
make backend     # http://127.0.0.1:8000
make frontend    # http://127.0.0.1:5173
```

Open **http://127.0.0.1:5173**.

## Demo Flow

1. **⌘K → Add documents** → select PDFs (samples included in `samples/`)
2. Watch the **ingest progress bar** stream live (per page vision progress)
3. **AskBar**: type *"give me a financial summary"* → click **suggest columns** → **add all**
4. Watch cells stream: `queued → retrieving → drafting → verifying → done`
5. Click any cell → **Focus pane** with answer, citations, PDF viewer with bbox overlay
6. Click **✦ 3D** → live 3D pipeline visualization
7. **Synthesis dock** (bottom) → cross row narrative with cell citations
8. **CSV** button (top bar) → structured export for downstream analytics

## Benchmark

```bash
cd backend && . .venv/bin/activate
python -m app.bench.run --modes naive,isd,wiki --limit 50 --out bench/results/run1
cat bench/results/run1/report.md
```

Emits JSONL per mode + markdown comparison: correctness (LLM judge), citation page recall / precision, latency, tokens.

## Tests

```bash
make test        # 23 backend tests, all hermetic
```

## Project Layout

```
backend/
  app/
    agent/          # decompose → draft → verify → revise cell loop
    api/            # FastAPI routes + SSE + export
    bench/          # FinanceBench harness
    jobs/           # token bucket budget
    parser/         # vision PDF → markdown → sections + chunks
    retriever/      # naive, isd (attention rerank), wiki
    services/       # ingest, events, cell jobs, synthesis, suggest
    storage/        # SQLModel tables
    wiki/           # per doc wiki builder
frontend/
  src/
    api/            # client + types
    components/     # TopBar, AskBar, Matrix, Cell, CommandBar,
                    # FocusPane, PdfView, SynthesisDock,
                    # IngestProgress, FlowOverlay, IngestFlowOverlay
    store/          # Zustand grid store with ingest tracking
docs/
  architecture.md   # Mermaid diagrams (this README has them inline too)
  specs/            # Design spec
  plans/            # Implementation plan
  progress.md       # Phase by phase build log
samples/            # Demo 10-K PDFs (AMD, NVIDIA, Netflix, Ferrari)
scripts/            # PDF generator, status doc builder
```

## Key Features

**Vision First Parsing** — No fragile text extraction. Every page rendered to PNG, sent to gpt 4.1 vision, returned as clean markdown. Tables, footnotes, charts handled natively.

**ISD Retrieval (Hebbia Pattern)** — Decompose query into sub queries + identify target sections from the wiki index. Embed and gather candidates. One batched attention rerank LLM call scores every candidate 0 to 1. Two LLM calls per retrieve regardless of pool size.

**Per Document Wiki** — At ingest, gpt 4.1 extracts per section: summary, entities, claims with evidence chunk ids, quantitative metrics. Doc level rollup: overview + key_metrics_table. WikiRetriever queries this structured knowledge first, falls back to vectors.

**Verify Loop** — Every drafted answer is claim checked: re retrieve evidence per claim, ask "does this support or contradict?". Unsupported claims trigger one revision pass. Confidence flagged if second pass fails.

**Live Streaming** — SSE per grid for cell state transitions. SSE per workspace for ingest progress (per page during vision). Zustand store merges events in real time.

**Query Decomposition** — AskBar: natural language → gpt 4.1 decomposes into 4 to 8 concrete column prompts with shape hints. One click to accept all.

**Structured Export** — CSV / JSON export keyed by issuer, metric, period, value, confidence, source pages. Ready for NAV returns pipelines or downstream analytics.

**3D Pipeline Visualization** — three.js scene showing the ISD loop (or ingest pipeline) as animated nodes with particle flow, driven by real SSE events. Click nodes for stage details.

## License

Internal use only.
