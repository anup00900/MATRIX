# Matrix PoC — Architecture

Paste any of these Mermaid blocks into https://mermaid.live or view directly in GitHub / VS Code (with the Mermaid extension).

---

## 1. System overview

```mermaid
flowchart LR
  subgraph FE[Frontend · React + Vite]
    UI[Matrix Grid UI]
    CMD[⌘K Palette]
    FOC[Focus Pane + PDF.js]
    SSE_C[SSE Client]
  end

  subgraph BE[Backend · FastAPI]
    API[REST Routes]
    SSEB[SSE Publisher]
    INGEST[Ingest Service]
    CELLJOB[Cell Job Runner]
    SYN[Synthesis Service]
  end

  subgraph CORE[Core Pipeline]
    PARSE[Vision Parser<br/>gpt-4.1 vision]
    WIKI[Wiki Builder]
    IDX[LanceDB Index]
    AGENT[ISD Agent<br/>decompose→draft→verify]
    RET{Retriever}
    RET_N[Naive<br/>vector top-k]
    RET_I[ISD<br/>decompose + attention rerank]
    RET_W[Wiki<br/>metric/claim first]
  end

  subgraph STORE[Storage]
    SQLITE[(SQLite + WAL)]
    DISK[(storage/<br/>pdfs · parsed · wikis · vectors · traces)]
  end

  subgraph LLM[Azure OpenAI]
    GPT[gpt-4.1]
    EMB[text-embedding-3-large<br/>→ local bge-large fallback]
  end

  UI --> API
  CMD --> API
  FOC --> API
  API --> SSEB
  SSEB -.SSE.-> SSE_C
  SSE_C -.updates.-> UI

  API --> INGEST
  API --> CELLJOB
  API --> SYN

  INGEST --> PARSE --> WIKI --> IDX
  CELLJOB --> AGENT --> RET
  RET --> RET_N
  RET --> RET_I
  RET --> RET_W

  PARSE -.vision.-> GPT
  WIKI -.structured.-> GPT
  AGENT -.chat+structured.-> GPT
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

## 2. Per-cell query flow (the ISD loop)

This is what happens for each `(row, column)` cell.

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
  API-->>UI: 200 column
  API->>Job: create_task(run_cell_job)
  Job->>SSE: state=retrieving
  SSE-->>UI: cell event
  Job->>Dec: decompose(prompt, doc_meta, section_index, shape_hint)
  Dec-->>Job: sub_questions[], target_sections[], shape
  loop for each sub_question
    Job->>Ret: retrieve(sub_q, doc, k=6)
    Ret-->>Job: evidence[]
  end
  Job->>SSE: state=drafting
  Job->>Drf: draft(prompt, sub_questions, evidence, shape)
  Drf-->>Job: {answer, citations, reasoning_trace}
  Job->>SSE: state=verifying
  Job->>Ver: verify(draft, retriever, doc)
  Ver-->>Job: notes[status: supported|contradicted|missing]
  alt any contradicted or missing
    Job->>Ret: retrieve(failing claim) — fresh evidence
    Job->>Drf: draft again with verifier notes
    Drf-->>Job: revised answer
    Job->>Ver: verify again
    Ver-->>Job: final notes
  end
  Job->>SSE: state=done + answer + citations
  SSE-->>UI: cell event → focus pane ready
```

---

## 3. Ingest pipeline (vision-first)

```mermaid
flowchart TB
  PDF[PDF upload] --> SHA[sha256 hash<br/>content-addressable]
  SHA --> DEDUP{exists?}
  DEDUP -->|yes| REUSE[reuse cached]
  DEDUP -->|no| WRITE[storage/pdfs/sha.pdf]
  WRITE --> RENDER[PyMuPDF render<br/>150 DPI PNG per page]
  REUSE --> RENDER
  RENDER --> VISION[gpt-4.1 vision<br/>PNG → markdown<br/>concurrency=4]
  VISION --> STITCH[stitch pages<br/>detect sections<br/>chunk ~500 tokens]
  STITCH --> META[meta extraction<br/>company · filing_type · period]
  META --> INDEX[embed chunks<br/>LanceDB write]
  INDEX --> WIKI_BUILD[wiki builder]
  subgraph WIKI_BUILD[Wiki builder]
    WSEC[per-section LLM call<br/>entities · claims · metrics · questions]
    WROLL[doc rollup LLM call<br/>overview · key_metrics_table]
    WSEC --> WROLL
  end
  WIKI_BUILD --> PERSIST[storage/wikis/sha__v1.json.gz]
  PERSIST --> READY[Document.status = ready<br/>SSE event]
```

---

## 4. Retriever comparison (the three tiers)

```mermaid
flowchart LR
  Q[query] --> MODE{mode}

  MODE -->|naive| N1[embed query]
  N1 --> N2[LanceDB top-k]
  N2 --> NOUT[evidence · source=chunk.vector]

  MODE -->|isd| I1[Decompose LLM<br/>sub-queries + target sections]
  I1 --> I2[per sub-query<br/>vector top-k]
  I2 --> I3[dedup + 0.5× boost<br/>for in-target chunks]
  I3 --> I4[Attention Rerank LLM<br/>score every candidate 0–1]
  I4 --> IOUT[evidence · source=chunk.isd<br/>sorted by attention]

  MODE -->|wiki| W1[scan DocWiki<br/>key_metrics + claims]
  W1 --> W2[token-overlap score<br/>vs metric label / claim text]
  W2 --> W3{hits ≥ k ?}
  W3 -->|yes| WOUT[evidence · source=wiki.metric<br/>or wiki.claim]
  W3 -->|no| W4[topup via naive fallback]
  W4 --> WOUT
```

---

## 5. Data model (SQLite)

```mermaid
erDiagram
  Workspace ||--o{ Document : owns
  Workspace ||--o{ Grid : owns
  Grid ||--o{ Column : has
  Grid ||--o{ Row : has
  Row }o--|| Document : references
  Grid ||--o{ Cell : has
  Cell }o--|| Row : at
  Cell }o--|| Column : at
  Grid ||--o{ Synthesis : produces

  Workspace { string id PK  string name }
  Document { string id PK  string sha256  string status  int n_pages  json meta_json  string parsed_path  string wiki_path }
  Grid { string id PK  string name  string retriever_mode }
  Column { string id PK  int position  string prompt  string shape_hint  int version }
  Row { string id PK  int position }
  Cell { string id PK  string status  json answer_json  json citations_json  string confidence  int tokens_used  int latency_ms  string trace_id }
  Synthesis { string id PK  string prompt  string answer }
```

---

## 6. Cell state machine

```mermaid
stateDiagram-v2
  [*] --> idle
  idle --> queued : new column/row
  queued --> retrieving : job picked up
  retrieving --> drafting : evidence gathered
  drafting --> verifying : draft produced
  verifying --> done : all claims supported
  verifying --> drafting : contradicted/missing<br/>(max 1 revise)
  done --> stale : column prompt edited
  stale --> queued : user clicks rerun
  verifying --> failed : LLM/parse error
  retrieving --> failed : retrieval error
  drafting --> failed : draft error
  failed --> queued : rerun
```
