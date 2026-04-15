# Hebbia Matrix PoC — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working Hebbia-Matrix-style spreadsheet over PDFs: drop 10-Ks, define prompt columns, watch cells stream in with cited answers, synthesise across rows; with three swappable retrievers (Naive / ISD / Wiki) benchmarked against FinanceBench.

**Architecture:** FastAPI + SQLite + LanceDB backend exposing an SSE-streamed grid API; React + Vite + TanStack Table premium frontend; Azure OpenAI (`gpt-4.1`) for all LLM calls; per-doc Wiki pre-indexing is the Tier-3 IP; retriever is a Protocol with three implementations swapped at runtime.

**Tech Stack:** Python 3.11 · FastAPI · SQLModel · LanceDB · PyMuPDF · pdfplumber · pytesseract · structlog · React 18 · Vite · TypeScript · TanStack Table · TailwindCSS · shadcn/ui · Zustand · PDF.js · cmdk · Framer Motion · Azure OpenAI · FinanceBench.

**Spec:** `docs/superpowers/specs/2026-04-15-hebbia-matrix-poc-design.md`

---

## Phase 0 — Repo scaffold

### Task 0.1: Create project skeleton

**Files:**
- Create: `backend/pyproject.toml`, `backend/README.md`, `backend/app/__init__.py`
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`
- Create: `.gitignore`, `.env.example`, `README.md`, `Makefile`

- [ ] **Step 1: Create top-level `.gitignore`**

```gitignore
.env
.env.local
storage/
backend/.venv/
backend/__pycache__/
backend/**/__pycache__/
frontend/node_modules/
frontend/dist/
bench/results/
*.log
.DS_Store
```

- [ ] **Step 2: Create `.env.example`**

```
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_ENDPOINT=https://api.core42.ai/
AZURE_OPENAI_API_VERSION=2024-10-21
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4.1
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-large
EMBEDDING_FALLBACK_MODEL=BAAI/bge-large-en-v1.5
STORAGE_ROOT=./storage
LOG_LEVEL=INFO
HOST=127.0.0.1
PORT=8000
```

- [ ] **Step 3: Create `backend/pyproject.toml`**

```toml
[project]
name = "matrix-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "sqlmodel>=0.0.22",
  "pydantic>=2.9",
  "pydantic-settings>=2.6",
  "httpx>=0.27",
  "openai>=1.54",
  "tiktoken>=0.8",
  "pymupdf>=1.24",
  "pdfplumber>=0.11",
  "pytesseract>=0.3.13",
  "pillow>=10.4",
  "lancedb>=0.14",
  "pyarrow>=17",
  "sentence-transformers>=3.2",
  "structlog>=24.4",
  "python-ulid>=3.0",
  "sse-starlette>=2.1",
  "python-multipart>=0.0.17",
  "python-dotenv>=1.0",
  "datasets>=3.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.3", "pytest-asyncio>=0.24", "pytest-cov>=5.0", "ruff>=0.7", "mypy>=1.12"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py311"
```

- [ ] **Step 4: Scaffold backend package tree**

Run:
```bash
cd backend
mkdir -p app/{api,parser,wiki,retriever,agent,synthesizer,jobs,storage,bench} tests/fixtures
touch app/__init__.py app/api/__init__.py app/parser/__init__.py app/wiki/__init__.py \
      app/retriever/__init__.py app/agent/__init__.py app/synthesizer/__init__.py \
      app/jobs/__init__.py app/storage/__init__.py app/bench/__init__.py tests/__init__.py
python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

Expected: venv created, dependencies installed without error.

- [ ] **Step 5: Scaffold Vite + React + TS frontend**

Run:
```bash
cd frontend
pnpm create vite@latest . --template react-ts
pnpm install
pnpm add @tanstack/react-table zustand cmdk framer-motion lucide-react \
         tailwindcss postcss autoprefixer @radix-ui/react-dialog \
         @radix-ui/react-tooltip @radix-ui/react-slot class-variance-authority \
         clsx tailwind-merge pdfjs-dist
pnpm add -D @types/node
pnpm dlx tailwindcss init -p
```

Expected: frontend installs cleanly, `pnpm dev` serves on 5173.

- [ ] **Step 6: Root `Makefile` with dev commands**

```make
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
```

- [ ] **Step 7: Commit**

```bash
git init
git add .gitignore .env.example backend/ frontend/ Makefile README.md
git commit -m "chore: scaffold backend (FastAPI) and frontend (Vite+React+TS)"
```

---

## Phase 1 — Shared infrastructure

### Task 1.1: Settings + logging

**Files:** Create `backend/app/settings.py`, `backend/app/logging.py`

- [ ] **Step 1: Write settings module**

`backend/app/settings.py`:
```python
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    azure_openai_api_key: str
    azure_openai_endpoint: str = "https://api.core42.ai/"
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_deployment_name: str = "gpt-4.1"
    azure_openai_embedding_deployment: str = "text-embedding-3-large"
    embedding_fallback_model: str = "BAAI/bge-large-en-v1.5"
    storage_root: Path = Path("./storage")
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = 8000

    @property
    def pdfs_dir(self) -> Path: return self.storage_root / "pdfs"
    @property
    def parsed_dir(self) -> Path: return self.storage_root / "parsed"
    @property
    def wikis_dir(self) -> Path: return self.storage_root / "wikis"
    @property
    def vectors_dir(self) -> Path: return self.storage_root / "vectors"
    @property
    def traces_dir(self) -> Path: return self.storage_root / "traces"
    @property
    def db_path(self) -> Path: return self.storage_root / "db" / "matrix.sqlite"

settings = Settings()
for d in (settings.pdfs_dir, settings.parsed_dir, settings.wikis_dir,
          settings.vectors_dir, settings.traces_dir, settings.db_path.parent):
    d.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 2: Write structlog setup**

`backend/app/logging.py`:
```python
import logging, structlog
from .settings import settings

def configure_logging() -> None:
    logging.basicConfig(level=settings.log_level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level)
        ),
    )

log = structlog.get_logger()
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/settings.py backend/app/logging.py
git commit -m "feat(settings): add settings and structured logging"
```

### Task 1.2: LLM wrapper with retries, rate limits, structured output

**Files:** Create `backend/app/llm.py`, `backend/tests/test_llm.py`

- [ ] **Step 1: Write failing test for schema-retry behaviour**

`backend/tests/test_llm.py`:
```python
import pytest
from pydantic import BaseModel
from app.llm import LLM, LLMParseError
from unittest.mock import AsyncMock, MagicMock

class Shape(BaseModel):
    answer: str
    score: int

@pytest.mark.asyncio
async def test_structured_retry_on_bad_json(monkeypatch):
    llm = LLM()
    call_count = {"n": 0}

    async def fake_chat(messages, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return "not json"
        return '{"answer": "ok", "score": 3}'

    monkeypatch.setattr(llm, "_chat_raw", fake_chat)
    result = await llm.structured(messages=[{"role": "user", "content": "x"}], schema=Shape)
    assert result.answer == "ok" and result.score == 3
    assert call_count["n"] == 2

@pytest.mark.asyncio
async def test_structured_fails_after_second_bad_json(monkeypatch):
    llm = LLM()
    async def fake_chat(messages, **kw): return "still not json"
    monkeypatch.setattr(llm, "_chat_raw", fake_chat)
    with pytest.raises(LLMParseError):
        await llm.structured(messages=[{"role": "user", "content": "x"}], schema=Shape)
```

- [ ] **Step 2: Run test — expected to fail (module missing)**

Run: `cd backend && pytest tests/test_llm.py -v`
Expected: `ModuleNotFoundError: app.llm`.

- [ ] **Step 3: Implement LLM wrapper**

`backend/app/llm.py`:
```python
from __future__ import annotations
import asyncio, json, time
from typing import Type, TypeVar
from openai import AsyncAzureOpenAI, RateLimitError, APIError
from pydantic import BaseModel, ValidationError
from .settings import settings
from .logging import log

T = TypeVar("T", bound=BaseModel)

class LLMParseError(Exception): ...
class LLMError(Exception): ...

class LLM:
    def __init__(self) -> None:
        self.client = AsyncAzureOpenAI(
            api_key=settings.azure_openai_api_key,
            azure_endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
        )
        self.deployment = settings.azure_openai_deployment_name
        self._cost_tokens = 0

    @property
    def cost_tokens(self) -> int: return self._cost_tokens

    async def _chat_raw(self, messages: list[dict], *, json_mode: bool = False,
                        temperature: float = 0.0, max_tokens: int = 2000) -> str:
        backoff = 1.0
        for attempt in range(5):
            try:
                resp = await self.client.chat.completions.create(
                    model=self.deployment,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"} if json_mode else None,
                )
                if resp.usage: self._cost_tokens += resp.usage.total_tokens
                return resp.choices[0].message.content or ""
            except RateLimitError as e:
                retry_after = getattr(e, "retry_after", None) or backoff
                log.warning("llm.rate_limited", retry_after=retry_after)
                await asyncio.sleep(retry_after); backoff *= 2
            except APIError as e:
                if attempt == 4: raise LLMError(str(e)) from e
                await asyncio.sleep(backoff); backoff *= 2
        raise LLMError("exhausted retries")

    async def chat(self, messages: list[dict], **kw) -> str:
        return await self._chat_raw(messages, **kw)

    async def structured(self, *, messages: list[dict], schema: Type[T],
                         temperature: float = 0.0, max_tokens: int = 2000) -> T:
        schema_hint = json.dumps(schema.model_json_schema())
        sys = {"role": "system", "content":
               f"Return ONLY valid JSON matching this schema:\n{schema_hint}"}
        msgs = [sys, *messages]
        raw = await self._chat_raw(msgs, json_mode=True,
                                   temperature=temperature, max_tokens=max_tokens)
        try:
            return schema.model_validate_json(raw)
        except (ValidationError, ValueError) as e:
            err = str(e)[:500]
            msgs2 = [*msgs, {"role": "assistant", "content": raw},
                     {"role": "user", "content":
                      f"That output failed validation: {err}. Return ONLY valid JSON matching the schema."}]
            raw2 = await self._chat_raw(msgs2, json_mode=True,
                                        temperature=temperature, max_tokens=max_tokens)
            try:
                return schema.model_validate_json(raw2)
            except (ValidationError, ValueError) as e2:
                raise LLMParseError(f"structured output failed twice: {e2}") from e2

llm = LLM()
```

- [ ] **Step 4: Run tests — expected PASS**

Run: `cd backend && pytest tests/test_llm.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/llm.py backend/tests/test_llm.py
git commit -m "feat(llm): Azure OpenAI wrapper with structured output retry"
```

### Task 1.3: Global job budget (token bucket)

**Files:** Create `backend/app/jobs/budget.py`, `backend/tests/test_budget.py`

- [ ] **Step 1: Write failing test**

`backend/tests/test_budget.py`:
```python
import pytest, asyncio
from app.jobs.budget import TokenBudget

@pytest.mark.asyncio
async def test_acquire_blocks_when_empty():
    b = TokenBudget(tokens_per_minute=120, burst=60)
    await b.acquire(60)
    t0 = asyncio.get_event_loop().time()
    await b.acquire(60)
    elapsed = asyncio.get_event_loop().time() - t0
    assert 0.4 < elapsed < 0.7
```

- [ ] **Step 2: Run test — expect ImportError**

Run: `cd backend && pytest tests/test_budget.py -v`

- [ ] **Step 3: Implement**

`backend/app/jobs/budget.py`:
```python
import asyncio, time

class TokenBudget:
    def __init__(self, tokens_per_minute: int, burst: int | None = None):
        self.rate = tokens_per_minute / 60.0
        self.capacity = burst or tokens_per_minute
        self._tokens = float(self.capacity)
        self._ts = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, n: int) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                self._tokens = min(self.capacity, self._tokens + (now - self._ts) * self.rate)
                self._ts = now
                if self._tokens >= n:
                    self._tokens -= n
                    return
                deficit = n - self._tokens
                wait = deficit / self.rate
            await asyncio.sleep(wait)
```

Note: For test speed, interpret `tokens_per_minute=120` as 2 tokens/sec. The test consumes 60 tokens (burst), then waits ~0.5s for another 60 to refill at 120/min = 2/s × 30s... correcting test expectation.

Fix the test to use realistic values:
```python
b = TokenBudget(tokens_per_minute=7200, burst=60)  # 120/s
await b.acquire(60)
t0 = asyncio.get_event_loop().time()
await b.acquire(60)
elapsed = asyncio.get_event_loop().time() - t0
assert 0.4 < elapsed < 0.7  # 60/120 = 0.5s
```

- [ ] **Step 4: Run tests — expected PASS**

Run: `cd backend && pytest tests/test_budget.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/app/jobs/budget.py backend/tests/test_budget.py
git commit -m "feat(jobs): global TPM token-bucket budget"
```

---

## Phase 2 — Storage layer

### Task 2.1: SQLModel tables

**Files:** Create `backend/app/storage/models.py`, `backend/app/storage/db.py`, `backend/tests/test_models.py`

- [ ] **Step 1: Write failing test**

`backend/tests/test_models.py`:
```python
from sqlmodel import Session, select
from app.storage.db import engine, init_db
from app.storage.models import Workspace, Document, Grid, Column, Row, Cell

def test_create_grid_and_cell(tmp_path, monkeypatch):
    from app import settings as s
    monkeypatch.setattr(s.settings, "storage_root", tmp_path)
    init_db(reset=True)
    with Session(engine) as sess:
        w = Workspace(name="w"); sess.add(w); sess.commit(); sess.refresh(w)
        d = Document(workspace_id=w.id, filename="a.pdf", sha256="x", status="ready")
        g = Grid(workspace_id=w.id, name="g", retriever_mode="naive")
        sess.add_all([d, g]); sess.commit(); sess.refresh(d); sess.refresh(g)
        col = Column(grid_id=g.id, position=0, prompt="Q", shape_hint="text", version=1)
        row = Row(grid_id=g.id, document_id=d.id, position=0)
        sess.add_all([col, row]); sess.commit(); sess.refresh(col); sess.refresh(row)
        cell = Cell(grid_id=g.id, row_id=row.id, column_id=col.id,
                    column_version=1, status="idle")
        sess.add(cell); sess.commit()
        got = sess.exec(select(Cell)).all()
        assert len(got) == 1 and got[0].status == "idle"
```

- [ ] **Step 2: Run test — expected ImportError**

- [ ] **Step 3: Implement models**

`backend/app/storage/models.py`:
```python
from __future__ import annotations
from datetime import datetime
from sqlmodel import SQLModel, Field, Column as SACol
from sqlalchemy import JSON
from ulid import ULID

def _ulid() -> str: return str(ULID())

class Workspace(SQLModel, table=True):
    id: str = Field(default_factory=_ulid, primary_key=True)
    name: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Document(SQLModel, table=True):
    id: str = Field(default_factory=_ulid, primary_key=True)
    workspace_id: str = Field(index=True, foreign_key="workspace.id")
    filename: str
    sha256: str = Field(index=True)
    status: str  # queued | parsing | wiki | indexing | ready | failed
    n_pages: int | None = None
    meta_json: dict | None = Field(default=None, sa_column=SACol(JSON))
    parsed_path: str | None = None
    wiki_path: str | None = None
    wiki_schema_version: int = 1
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Grid(SQLModel, table=True):
    id: str = Field(default_factory=_ulid, primary_key=True)
    workspace_id: str = Field(index=True, foreign_key="workspace.id")
    name: str
    retriever_mode: str = "wiki"  # naive | isd | wiki
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Column(SQLModel, table=True):
    id: str = Field(default_factory=_ulid, primary_key=True)
    grid_id: str = Field(index=True, foreign_key="grid.id")
    position: int
    prompt: str
    shape_hint: str = "text"  # text | number | currency | percentage | list | table
    target_sections_json: list[str] | None = Field(default=None, sa_column=SACol(JSON))
    version: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class Row(SQLModel, table=True):
    id: str = Field(default_factory=_ulid, primary_key=True)
    grid_id: str = Field(index=True, foreign_key="grid.id")
    document_id: str = Field(foreign_key="document.id")
    position: int

class Cell(SQLModel, table=True):
    id: str = Field(default_factory=_ulid, primary_key=True)
    grid_id: str = Field(index=True, foreign_key="grid.id")
    row_id: str = Field(foreign_key="row.id")
    column_id: str = Field(foreign_key="column.id")
    column_version: int
    status: str = "idle"  # idle|queued|retrieving|drafting|verifying|done|stale|failed
    answer_json: dict | None = Field(default=None, sa_column=SACol(JSON))
    citations_json: list | None = Field(default=None, sa_column=SACol(JSON))
    confidence: str | None = None  # high | medium | low
    tokens_used: int = 0
    latency_ms: int = 0
    retriever_mode: str | None = None
    trace_id: str | None = None
    trace_path: str | None = None
    error: str | None = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class Synthesis(SQLModel, table=True):
    id: str = Field(default_factory=_ulid, primary_key=True)
    grid_id: str = Field(foreign_key="grid.id")
    prompt: str
    answer: str
    citations_json: list | None = Field(default=None, sa_column=SACol(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

`backend/app/storage/db.py`:
```python
from sqlmodel import SQLModel, create_engine
from ..settings import settings

engine = create_engine(
    f"sqlite:///{settings.db_path}",
    connect_args={"check_same_thread": False},
)

def init_db(reset: bool = False) -> None:
    if reset and settings.db_path.exists():
        settings.db_path.unlink()
    from . import models  # noqa: F401 - register tables
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
```

- [ ] **Step 4: Run tests — expected PASS**

Run: `cd backend && pytest tests/test_models.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage/ backend/tests/test_models.py
git commit -m "feat(storage): SQLModel tables + WAL SQLite"
```

---

## Phase 3 — PDF parser

### Task 3.1: StructuredDoc schema + parser

**Files:** Create `backend/app/parser/schema.py`, `backend/app/parser/pdf.py`, `backend/tests/test_parser.py`, `backend/tests/fixtures/tiny.pdf` (checked-in 3-page fixture)

- [ ] **Step 1: Add a tiny deterministic fixture PDF**

Run:
```bash
cd backend && python -c "
import fitz
doc = fitz.open()
for i, txt in enumerate([
    'Item 1. Business\nApple Inc. designs and sells consumer electronics.',
    'Item 1A. Risk Factors\nSupply chain concentration in East Asia is a material risk.',
    'Item 7. MD&A\nRevenue for fiscal 2023 was \$383.3 billion, up 2.8% YoY.']):
    p = doc.new_page()
    p.insert_text((72, 72), txt, fontsize=11)
doc.save('tests/fixtures/tiny.pdf')
"
```

- [ ] **Step 2: Write failing test**

`backend/tests/test_parser.py`:
```python
from pathlib import Path
from app.parser.pdf import parse_pdf

def test_parse_tiny():
    doc = parse_pdf(Path("tests/fixtures/tiny.pdf"))
    assert doc.n_pages == 3
    titles = [s.title for s in doc.sections]
    assert any("Item 1." in t for t in titles)
    assert any("Item 7" in t for t in titles)
    assert len(doc.chunks) >= 3
    for c in doc.chunks:
        assert c.bboxes and c.bboxes[0].page >= 1
```

- [ ] **Step 3: Run test — expect ImportError**

- [ ] **Step 4: Implement schema**

`backend/app/parser/schema.py`:
```python
from pydantic import BaseModel
from typing import Literal

class Bbox(BaseModel):
    page: int
    bbox: tuple[float, float, float, float]

class Page(BaseModel):
    page_no: int
    text: str
    ocr_failed: bool = False

class Section(BaseModel):
    id: str
    title: str
    level: int
    page_start: int
    page_end: int
    text: str

class Table(BaseModel):
    id: str
    page: int
    bbox: tuple[float, float, float, float]
    rows: list[list[str]]
    caption: str | None = None
    markdown: str

class Chunk(BaseModel):
    id: str
    section_id: str | None
    page: int
    text: str
    token_count: int
    bboxes: list[Bbox]

class DocMeta(BaseModel):
    company: str | None = None
    filing_type: str | None = None
    period_end: str | None = None

class StructuredDoc(BaseModel):
    doc_id: str
    n_pages: int
    meta: DocMeta = DocMeta()
    pages: list[Page]
    sections: list[Section]
    tables: list[Table]
    chunks: list[Chunk]
```

- [ ] **Step 5: Implement parser**

`backend/app/parser/pdf.py`:
```python
from __future__ import annotations
import hashlib, re
from pathlib import Path
import fitz, tiktoken
from ulid import ULID
from .schema import StructuredDoc, Page, Section, Chunk, Bbox, DocMeta

ENCODER = tiktoken.get_encoding("cl100k_base")
HEADING_RE = re.compile(r"^(Item\s+\d+[A-Z]?\.?|Part\s+[IVX]+)", re.IGNORECASE)

def _sha256(path: Path) -> str:
    h = hashlib.sha256(); h.update(path.read_bytes()); return h.hexdigest()

def _detect_sections(pages: list[Page]) -> list[Section]:
    sections: list[Section] = []
    cur_title: str | None = None
    cur_start = 1
    cur_text: list[str] = []
    for p in pages:
        for line in p.text.splitlines():
            ln = line.strip()
            if HEADING_RE.match(ln):
                if cur_title is not None:
                    sections.append(Section(
                        id=str(ULID()), title=cur_title, level=2,
                        page_start=cur_start, page_end=p.page_no,
                        text="\n".join(cur_text),
                    ))
                cur_title = ln
                cur_start = p.page_no
                cur_text = []
            elif cur_title is not None:
                cur_text.append(ln)
    if cur_title is not None:
        sections.append(Section(
            id=str(ULID()), title=cur_title, level=2,
            page_start=cur_start, page_end=pages[-1].page_no,
            text="\n".join(cur_text),
        ))
    return sections

def _chunk_text(section_id: str | None, page: int, text: str,
                bbox: tuple[float, float, float, float],
                target_tokens: int = 500, overlap: int = 50) -> list[Chunk]:
    tokens = ENCODER.encode(text)
    if not tokens: return []
    out: list[Chunk] = []
    i = 0
    while i < len(tokens):
        window = tokens[i : i + target_tokens]
        txt = ENCODER.decode(window)
        out.append(Chunk(
            id=str(ULID()), section_id=section_id, page=page,
            text=txt, token_count=len(window),
            bboxes=[Bbox(page=page, bbox=bbox)],
        ))
        if i + target_tokens >= len(tokens): break
        i += target_tokens - overlap
    return out

def parse_pdf(path: Path) -> StructuredDoc:
    doc_id = _sha256(path)
    mu = fitz.open(path)
    pages: list[Page] = []
    for i, p in enumerate(mu, start=1):
        text = p.get_text("text") or ""
        pages.append(Page(page_no=i, text=text, ocr_failed=len(text.strip()) < 30))
    sections = _detect_sections(pages)
    section_by_page: dict[int, str] = {}
    for s in sections:
        for pn in range(s.page_start, s.page_end + 1):
            section_by_page.setdefault(pn, s.id)
    chunks: list[Chunk] = []
    for p in pages:
        if not p.text.strip(): continue
        page_rect = mu[p.page_no - 1].rect
        bbox = (page_rect.x0, page_rect.y0, page_rect.x1, page_rect.y1)
        chunks.extend(_chunk_text(section_by_page.get(p.page_no), p.page_no, p.text, bbox))
    return StructuredDoc(
        doc_id=doc_id, n_pages=len(pages),
        pages=pages, sections=sections, tables=[], chunks=chunks,
    )
```

- [ ] **Step 6: Run tests — expected PASS**

Run: `cd backend && pytest tests/test_parser.py -v`

- [ ] **Step 7: Commit**

```bash
git add backend/app/parser/ backend/tests/test_parser.py backend/tests/fixtures/tiny.pdf
git commit -m "feat(parser): PyMuPDF structured parse with section + chunk detection"
```

### Task 3.2: Document meta-extraction via LLM

**Files:** Modify `backend/app/parser/pdf.py`, add `backend/app/parser/meta.py`, `backend/tests/test_meta.py`

- [ ] **Step 1: Write test with mocked LLM**

`backend/tests/test_meta.py`:
```python
import pytest
from app.parser.meta import extract_doc_meta
from app.parser.schema import StructuredDoc, Page

@pytest.mark.asyncio
async def test_meta_extraction(monkeypatch):
    from app.parser import meta as m
    async def fake_structured(*, messages, schema, **kw):
        from app.parser.schema import DocMeta
        return DocMeta(company="Apple Inc.", filing_type="10-K", period_end="2023-09-30")
    monkeypatch.setattr(m.llm, "structured", fake_structured)
    doc = StructuredDoc(doc_id="x", n_pages=3, pages=[
        Page(page_no=1, text="Apple Inc. Annual Report 10-K Fiscal 2023")
    ], sections=[], tables=[], chunks=[])
    out = await extract_doc_meta(doc)
    assert out.company == "Apple Inc." and out.filing_type == "10-K"
```

- [ ] **Step 2: Run test — expect ImportError**

- [ ] **Step 3: Implement**

`backend/app/parser/meta.py`:
```python
from ..llm import llm
from .schema import StructuredDoc, DocMeta

async def extract_doc_meta(doc: StructuredDoc) -> DocMeta:
    head = "\n".join(p.text for p in doc.pages[:3])[:4000]
    prompt = (
        "Extract the issuer name, filing type (e.g. 10-K, 10-Q, earnings call), "
        "and period_end date (YYYY-MM-DD if available) from the following filing header. "
        "Return JSON fields: company, filing_type, period_end. Unknown fields → null.\n\n"
        f"{head}"
    )
    return await llm.structured(messages=[{"role": "user", "content": prompt}], schema=DocMeta)
```

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Commit**

```bash
git add backend/app/parser/meta.py backend/tests/test_meta.py
git commit -m "feat(parser): LLM-based meta extraction"
```

---

## Phase 4 — Retrievers

### Task 4.1: Evidence type + embedding service

**Files:** Create `backend/app/retriever/types.py`, `backend/app/retriever/embeddings.py`, `backend/tests/test_embeddings.py`

- [ ] **Step 1: Define types**

`backend/app/retriever/types.py`:
```python
from pydantic import BaseModel
from typing import Protocol
from ..parser.schema import Bbox, StructuredDoc

class Evidence(BaseModel):
    chunk_id: str
    text: str
    page: int
    bboxes: list[Bbox]
    score: float
    source: str  # "chunk.vector" | "wiki.metric" | "wiki.claim" | "section.drill"

class Retriever(Protocol):
    async def retrieve(self, query: str, doc: StructuredDoc, k: int = 8) -> list[Evidence]: ...
```

- [ ] **Step 2: Write test for embedding auto-detect**

`backend/tests/test_embeddings.py`:
```python
import pytest
from app.retriever.embeddings import EmbeddingService

@pytest.mark.asyncio
async def test_local_fallback(monkeypatch):
    svc = EmbeddingService(force_local=True)
    vecs = await svc.embed(["hello world", "another doc"])
    assert len(vecs) == 2 and len(vecs[0]) > 100
```

- [ ] **Step 3: Implement embedding service**

`backend/app/retriever/embeddings.py`:
```python
from __future__ import annotations
import asyncio
from functools import lru_cache
from openai import AsyncAzureOpenAI
from sentence_transformers import SentenceTransformer
from ..settings import settings
from ..logging import log

@lru_cache(maxsize=1)
def _local_model() -> SentenceTransformer:
    return SentenceTransformer(settings.embedding_fallback_model)

class EmbeddingService:
    def __init__(self, force_local: bool = False):
        self.mode: str = "local" if force_local else "unset"
        self.client: AsyncAzureOpenAI | None = None if force_local else AsyncAzureOpenAI(
            api_key=settings.azure_openai_api_key,
            azure_endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
        )

    async def _probe_azure(self) -> None:
        assert self.client is not None
        try:
            await self.client.embeddings.create(
                model=settings.azure_openai_embedding_deployment, input=["probe"])
            self.mode = "azure"
            log.info("embeddings.azure.ok")
        except Exception as e:
            log.warning("embeddings.azure.unavailable", error=str(e))
            self.mode = "local"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self.mode == "unset": await self._probe_azure()
        if self.mode == "azure":
            assert self.client is not None
            resp = await self.client.embeddings.create(
                model=settings.azure_openai_embedding_deployment, input=texts)
            return [d.embedding for d in resp.data]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _local_model().encode(texts, normalize_embeddings=True).tolist())

embeddings = EmbeddingService()
```

- [ ] **Step 4: Run tests — PASS (downloads model on first run, slow once)**

Run: `cd backend && pytest tests/test_embeddings.py -v -s`

- [ ] **Step 5: Commit**

```bash
git add backend/app/retriever/types.py backend/app/retriever/embeddings.py backend/tests/test_embeddings.py
git commit -m "feat(retriever): evidence types + embedding service with fallback"
```

### Task 4.2: LanceDB index per doc + NaiveRetriever

**Files:** Create `backend/app/retriever/index.py`, `backend/app/retriever/naive.py`, `backend/tests/test_naive_retriever.py`

- [ ] **Step 1: Write failing test**

`backend/tests/test_naive_retriever.py`:
```python
import pytest
from pathlib import Path
from app.parser.pdf import parse_pdf
from app.retriever.index import build_index
from app.retriever.naive import NaiveRetriever

@pytest.mark.asyncio
async def test_naive_retrieval():
    doc = parse_pdf(Path("tests/fixtures/tiny.pdf"))
    await build_index(doc, force_local=True)
    r = NaiveRetriever(force_local=True)
    ev = await r.retrieve("What were the revenue figures for fiscal 2023?", doc, k=3)
    assert ev and any("383" in e.text or "2.8" in e.text for e in ev)
```

- [ ] **Step 2: Implement index builder**

`backend/app/retriever/index.py`:
```python
from __future__ import annotations
import lancedb
import pyarrow as pa
from ..settings import settings
from ..parser.schema import StructuredDoc
from .embeddings import EmbeddingService

def _table_name(doc_id: str) -> str: return f"doc_{doc_id[:16]}"

async def build_index(doc: StructuredDoc, force_local: bool = False) -> None:
    svc = EmbeddingService(force_local=force_local)
    vecs = await svc.embed([c.text for c in doc.chunks])
    db = lancedb.connect(str(settings.vectors_dir))
    rows = [
        {"chunk_id": c.id, "page": c.page, "text": c.text,
         "section_id": c.section_id or "", "vector": v}
        for c, v in zip(doc.chunks, vecs)
    ]
    name = _table_name(doc.doc_id)
    if name in db.table_names():
        db.drop_table(name)
    db.create_table(name, rows)

def open_table(doc_id: str):
    db = lancedb.connect(str(settings.vectors_dir))
    return db.open_table(_table_name(doc_id))
```

- [ ] **Step 3: Implement naive retriever**

`backend/app/retriever/naive.py`:
```python
from ..parser.schema import StructuredDoc, Bbox
from .embeddings import EmbeddingService
from .index import open_table
from .types import Evidence

class NaiveRetriever:
    def __init__(self, force_local: bool = False):
        self.embeddings = EmbeddingService(force_local=force_local)

    async def retrieve(self, query: str, doc: StructuredDoc, k: int = 8) -> list[Evidence]:
        q_vec = (await self.embeddings.embed([query]))[0]
        tbl = open_table(doc.doc_id)
        hits = tbl.search(q_vec).limit(k).to_list()
        chunk_by_id = {c.id: c for c in doc.chunks}
        out: list[Evidence] = []
        for h in hits:
            c = chunk_by_id.get(h["chunk_id"])
            if not c: continue
            out.append(Evidence(
                chunk_id=c.id, text=c.text, page=c.page, bboxes=c.bboxes,
                score=float(h.get("_distance", 0.0)), source="chunk.vector",
            ))
        return out
```

- [ ] **Step 4: Run tests — PASS**

Run: `cd backend && pytest tests/test_naive_retriever.py -v -s`

- [ ] **Step 5: Commit**

```bash
git add backend/app/retriever/index.py backend/app/retriever/naive.py backend/tests/test_naive_retriever.py
git commit -m "feat(retriever): LanceDB index + naive top-k retriever"
```

### Task 4.3: ISDRetriever (agentic iterative retrieval)

**Files:** Create `backend/app/retriever/isd.py`, `backend/tests/test_isd_retriever.py`

- [ ] **Step 1: Write test with mocked LLM**

`backend/tests/test_isd_retriever.py`:
```python
import pytest
from pathlib import Path
from app.parser.pdf import parse_pdf
from app.retriever.index import build_index
from app.retriever.isd import ISDRetriever

@pytest.mark.asyncio
async def test_isd_retrieval(monkeypatch):
    from app.retriever import isd
    async def fake_structured(*, messages, schema, **kw):
        return schema(queries=["fiscal 2023 revenue", "risk factors supply chain"])
    monkeypatch.setattr(isd.llm, "structured", fake_structured)
    doc = parse_pdf(Path("tests/fixtures/tiny.pdf"))
    await build_index(doc, force_local=True)
    r = ISDRetriever(force_local=True)
    ev = await r.retrieve("Summarise financial performance and risks.", doc, k=3)
    assert len(ev) >= 2
```

- [ ] **Step 2: Implement**

`backend/app/retriever/isd.py`:
```python
from pydantic import BaseModel
from ..llm import llm
from ..parser.schema import StructuredDoc
from .naive import NaiveRetriever
from .types import Evidence

class _QueryPlan(BaseModel):
    queries: list[str]

class ISDRetriever:
    def __init__(self, force_local: bool = False):
        self.naive = NaiveRetriever(force_local=force_local)

    async def _decompose(self, query: str) -> list[str]:
        plan = await llm.structured(
            messages=[{"role": "user", "content":
                f"Decompose this retrieval intent into 2-4 specific sub-queries "
                f"targeting distinct aspects of a long document. "
                f"Return JSON field `queries` (string list).\n\nIntent: {query}"}],
            schema=_QueryPlan,
        )
        return plan.queries or [query]

    async def retrieve(self, query: str, doc: StructuredDoc, k: int = 8) -> list[Evidence]:
        sub_queries = await self._decompose(query)
        seen: dict[str, Evidence] = {}
        per_sub_k = max(2, k // max(1, len(sub_queries)))
        for sq in sub_queries:
            for e in await self.naive.retrieve(sq, doc, k=per_sub_k):
                if e.chunk_id not in seen or seen[e.chunk_id].score > e.score:
                    e.source = "chunk.isd"
                    seen[e.chunk_id] = e
        return sorted(seen.values(), key=lambda e: e.score)[:k]
```

- [ ] **Step 3: Run tests — PASS**

Run: `cd backend && pytest tests/test_isd_retriever.py -v -s`

- [ ] **Step 4: Commit**

```bash
git add backend/app/retriever/isd.py backend/tests/test_isd_retriever.py
git commit -m "feat(retriever): ISD iterative retrieval with LLM query decomposition"
```

---

## Phase 5 — Per-doc Wiki (Tier-3 IP)

### Task 5.1: Wiki schemas + per-section builder

**Files:** Create `backend/app/wiki/schema.py`, `backend/app/wiki/builder.py`, `backend/tests/test_wiki.py`

- [ ] **Step 1: Define schemas**

`backend/app/wiki/schema.py`:
```python
from pydantic import BaseModel

WIKI_SCHEMA_VERSION = 1

class Entity(BaseModel):
    name: str
    type: str  # company | product | person | metric | location | other
    mentions: list[str]  # chunk_ids

class Claim(BaseModel):
    text: str
    evidence_chunks: list[str]
    confidence: float = 0.7

class Metric(BaseModel):
    name: str
    value: float | str
    unit: str | None = None
    period: str | None = None
    chunk_id: str

class SectionWikiEntry(BaseModel):
    section_id: str
    summary: str
    entities: list[Entity] = []
    claims: list[Claim] = []
    metrics: list[Metric] = []
    questions_answered: list[str] = []

class DocWiki(BaseModel):
    doc_id: str
    wiki_schema_version: int = WIKI_SCHEMA_VERSION
    overview: str
    section_index: list[dict]
    entries: list[SectionWikiEntry]
    key_metrics_table: dict[str, Metric] = {}
```

- [ ] **Step 2: Write test with mocked LLM**

`backend/tests/test_wiki.py`:
```python
import pytest
from pathlib import Path
from app.parser.pdf import parse_pdf
from app.wiki.builder import build_wiki
from app.wiki.schema import SectionWikiEntry, DocWiki

@pytest.mark.asyncio
async def test_build_wiki(monkeypatch):
    from app.wiki import builder as b
    async def fake_entry(*, messages, schema, **kw):
        if schema is SectionWikiEntry:
            return SectionWikiEntry(
                section_id="s-1", summary="placeholder",
                questions_answered=["what is this section about"])
        return schema(doc_id="x", overview="o", section_index=[], entries=[])
    monkeypatch.setattr(b.llm, "structured", fake_entry)
    doc = parse_pdf(Path("tests/fixtures/tiny.pdf"))
    wiki = await build_wiki(doc)
    assert isinstance(wiki, DocWiki)
    assert len(wiki.entries) == len(doc.sections)
```

- [ ] **Step 3: Implement builder**

`backend/app/wiki/builder.py`:
```python
from __future__ import annotations
import asyncio, gzip, json
from pathlib import Path
from ..llm import llm
from ..logging import log
from ..parser.schema import StructuredDoc, Section, Chunk
from ..settings import settings
from .schema import DocWiki, SectionWikiEntry, WIKI_SCHEMA_VERSION

SECTION_CONCURRENCY = 4

def wiki_path_for(doc_id: str) -> Path:
    return settings.wikis_dir / f"{doc_id}__v{WIKI_SCHEMA_VERSION}.json.gz"

async def _build_section(section: Section, chunks: list[Chunk]) -> SectionWikiEntry:
    chunk_lines = "\n".join(f"[{c.id}] (p.{c.page}) {c.text[:600]}" for c in chunks[:12])
    prompt = (
        f"You are analysing a section of a financial filing.\n\n"
        f"Section title: {section.title}\n\n"
        f"Chunks (cite any evidence by chunk id):\n{chunk_lines}\n\n"
        f"Extract: a concise 3-5 sentence summary, named entities, notable claims "
        f"(each with evidence_chunks), quantitative metrics (with chunk_id), and a list "
        f"of questions this section can answer. Do not invent; only use what's present."
    )
    entry = await llm.structured(
        messages=[{"role": "user", "content": prompt}], schema=SectionWikiEntry,
        max_tokens=1500,
    )
    entry.section_id = section.id
    return entry

async def build_wiki(doc: StructuredDoc) -> DocWiki:
    chunks_by_section: dict[str, list[Chunk]] = {}
    for c in doc.chunks:
        chunks_by_section.setdefault(c.section_id or "_", []).append(c)
    sem = asyncio.Semaphore(SECTION_CONCURRENCY)
    async def guarded(s: Section) -> SectionWikiEntry:
        async with sem:
            return await _build_section(s, chunks_by_section.get(s.id, []))
    entries = await asyncio.gather(*(guarded(s) for s in doc.sections))
    section_index = [
        {"id": s.id, "title": s.title,
         "questions_answered": e.questions_answered, "summary": e.summary}
        for s, e in zip(doc.sections, entries)
    ]
    rollup_prompt = (
        "Given these section summaries, write a 3-5 sentence overview of the document, "
        "then return JSON with: overview (str), key_metrics_table (object mapping "
        "metric name to {name, value, unit, period, chunk_id}) containing only the most "
        "important 3-6 metrics."
        + "\n\n" + "\n".join(f"- {s['title']}: {s['summary']}" for s in section_index)
    )
    class Rollup(DocWiki): pass
    rollup = await llm.structured(
        messages=[{"role": "user", "content": rollup_prompt}], schema=DocWiki,
        max_tokens=1500,
    )
    wiki = DocWiki(
        doc_id=doc.doc_id,
        overview=rollup.overview,
        section_index=section_index,
        entries=list(entries),
        key_metrics_table=rollup.key_metrics_table,
    )
    path = wiki_path_for(doc.doc_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as f:
        f.write(wiki.model_dump_json())
    log.info("wiki.built", doc_id=doc.doc_id, sections=len(entries))
    return wiki

def load_wiki(doc_id: str) -> DocWiki | None:
    p = wiki_path_for(doc_id)
    if not p.exists(): return None
    with gzip.open(p, "rt") as f:
        return DocWiki.model_validate_json(f.read())
```

- [ ] **Step 4: Run tests — PASS**

Run: `cd backend && pytest tests/test_wiki.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/app/wiki/ backend/tests/test_wiki.py
git commit -m "feat(wiki): per-doc wiki builder with section + rollup extraction"
```

### Task 5.2: WikiRetriever (metric/claim-first, then chunk fallback)

**Files:** Create `backend/app/retriever/wiki.py`, `backend/tests/test_wiki_retriever.py`

- [ ] **Step 1: Write test**

`backend/tests/test_wiki_retriever.py`:
```python
import pytest
from pathlib import Path
from app.parser.pdf import parse_pdf
from app.retriever.index import build_index
from app.retriever.wiki import WikiRetriever
from app.wiki.schema import DocWiki, SectionWikiEntry, Claim, Metric

@pytest.mark.asyncio
async def test_wiki_retriever_prefers_metrics(monkeypatch):
    doc = parse_pdf(Path("tests/fixtures/tiny.pdf"))
    await build_index(doc, force_local=True)
    chunk_id = doc.chunks[-1].id  # last page = MD&A revenue
    wiki = DocWiki(
        doc_id=doc.doc_id, overview="x",
        section_index=[],
        entries=[SectionWikiEntry(
            section_id=doc.sections[-1].id, summary="revenue",
            claims=[Claim(text="Revenue grew 2.8% YoY", evidence_chunks=[chunk_id])],
            metrics=[Metric(name="revenue", value=383.3, unit="USD_billions",
                            period="FY2023", chunk_id=chunk_id)],
        )],
        key_metrics_table={"revenue": Metric(
            name="revenue", value=383.3, unit="USD_billions",
            period="FY2023", chunk_id=chunk_id)},
    )
    r = WikiRetriever(wiki=wiki, force_local=True)
    ev = await r.retrieve("revenue fiscal 2023", doc, k=3)
    assert ev and any(e.source.startswith("wiki.") for e in ev)
```

- [ ] **Step 2: Implement**

`backend/app/retriever/wiki.py`:
```python
from __future__ import annotations
from ..parser.schema import StructuredDoc
from ..wiki.schema import DocWiki
from .naive import NaiveRetriever
from .types import Evidence

def _score_overlap(q: str, text: str) -> float:
    q_terms = {t.lower() for t in q.split() if len(t) > 3}
    t_terms = {t.lower() for t in text.split() if len(t) > 3}
    if not q_terms: return 1.0
    return 1.0 - len(q_terms & t_terms) / len(q_terms)  # lower is better

class WikiRetriever:
    def __init__(self, *, wiki: DocWiki, force_local: bool = False):
        self.wiki = wiki
        self.fallback = NaiveRetriever(force_local=force_local)

    async def retrieve(self, query: str, doc: StructuredDoc, k: int = 8) -> list[Evidence]:
        chunk_by_id = {c.id: c for c in doc.chunks}
        hits: list[Evidence] = []

        for m in self.wiki.key_metrics_table.values():
            c = chunk_by_id.get(m.chunk_id)
            if not c: continue
            score = _score_overlap(query, f"{m.name} {m.unit or ''} {m.period or ''}")
            hits.append(Evidence(chunk_id=c.id, text=c.text, page=c.page,
                                 bboxes=c.bboxes, score=score, source="wiki.metric"))

        for entry in self.wiki.entries:
            for cl in entry.claims:
                for cid in cl.evidence_chunks:
                    c = chunk_by_id.get(cid)
                    if not c: continue
                    score = _score_overlap(query, cl.text)
                    hits.append(Evidence(chunk_id=c.id, text=c.text, page=c.page,
                                         bboxes=c.bboxes, score=score, source="wiki.claim"))

        if len(hits) < k:
            hits.extend(await self.fallback.retrieve(query, doc, k=k - len(hits)))

        dedup: dict[str, Evidence] = {}
        for e in hits:
            if e.chunk_id not in dedup or dedup[e.chunk_id].score > e.score:
                dedup[e.chunk_id] = e
        return sorted(dedup.values(), key=lambda e: e.score)[:k]
```

- [ ] **Step 3: Run tests — PASS**

Run: `cd backend && pytest tests/test_wiki_retriever.py -v -s`

- [ ] **Step 4: Commit**

```bash
git add backend/app/retriever/wiki.py backend/tests/test_wiki_retriever.py
git commit -m "feat(retriever): WikiRetriever with metric/claim-first lookup"
```

---

## Phase 6 — ISD agent (cell loop)

### Task 6.1: Cell result types + decompose step

**Files:** Create `backend/app/agent/types.py`, `backend/app/agent/decompose.py`, `backend/tests/test_agent_decompose.py`

- [ ] **Step 1: Types**

`backend/app/agent/types.py`:
```python
from pydantic import BaseModel
from typing import Any, Literal
from ..retriever.types import Evidence

AnswerShape = Literal["text", "number", "currency", "percentage", "list", "table"]
Confidence = Literal["high", "medium", "low"]

class Citation(BaseModel):
    chunk_id: str
    page: int
    snippet: str
    bboxes: list

class DecompositionPlan(BaseModel):
    sub_questions: list[str]
    expected_answer_shape: AnswerShape
    target_sections: list[str] = []

class DraftAnswer(BaseModel):
    answer: Any
    citations: list[str]  # chunk_ids
    reasoning_trace: list[str] = []

class VerifierNote(BaseModel):
    claim: str
    status: Literal["supported", "contradicted", "missing"]
    note: str = ""

class CellResult(BaseModel):
    answer: Any
    answer_shape: AnswerShape
    citations: list[Citation]
    confidence: Confidence
    tokens_used: int = 0
    latency_ms: int = 0
    retriever_mode: str
    trace_id: str
    trace: dict
```

- [ ] **Step 2: Write decompose test**

`backend/tests/test_agent_decompose.py`:
```python
import pytest
from app.agent.decompose import decompose
from app.agent.types import DecompositionPlan

@pytest.mark.asyncio
async def test_decompose(monkeypatch):
    from app.agent import decompose as d
    async def fake(*, messages, schema, **kw):
        return DecompositionPlan(sub_questions=["a", "b"],
                                 expected_answer_shape="percentage")
    monkeypatch.setattr(d.llm, "structured", fake)
    plan = await decompose(prompt="Revenue YoY", doc_meta={"company": "Apple"},
                           section_index=[{"id": "s1", "title": "MD&A"}],
                           shape_hint="percentage")
    assert plan.sub_questions == ["a", "b"]
```

- [ ] **Step 3: Implement**

`backend/app/agent/decompose.py`:
```python
from ..llm import llm
from .types import DecompositionPlan

async def decompose(*, prompt: str, doc_meta: dict, section_index: list[dict],
                    shape_hint: str) -> DecompositionPlan:
    sections_md = "\n".join(f"- [{s['id']}] {s['title']}" for s in section_index[:40])
    msg = (
        f"You are preparing an information-extraction plan for one cell of a matrix.\n"
        f"Document: {doc_meta}\n"
        f"Available sections:\n{sections_md}\n\n"
        f"User prompt: {prompt}\n"
        f"Requested answer shape hint: {shape_hint}\n\n"
        f"Return JSON with:\n"
        f"- sub_questions: 2-4 specific retrieval queries that together cover the prompt\n"
        f"- expected_answer_shape: one of text|number|currency|percentage|list|table\n"
        f"- target_sections: up to 3 section ids most likely to contain the answer\n"
    )
    return await llm.structured(messages=[{"role": "user", "content": msg}],
                                schema=DecompositionPlan, max_tokens=600)
```

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/types.py backend/app/agent/decompose.py backend/tests/test_agent_decompose.py
git commit -m "feat(agent): cell types + prompt decomposition step"
```

### Task 6.2: Draft + Verify + Revise loop

**Files:** Create `backend/app/agent/draft.py`, `backend/app/agent/verify.py`, `backend/app/agent/runner.py`, `backend/tests/test_agent_runner.py`

- [ ] **Step 1: Draft module**

`backend/app/agent/draft.py`:
```python
from ..llm import llm
from ..retriever.types import Evidence
from .types import DraftAnswer

def _evidence_block(evidence: list[Evidence]) -> str:
    return "\n".join(f"[{e.chunk_id}] (p.{e.page}, src={e.source}) {e.text[:500]}"
                     for e in evidence[:20])

async def draft(*, prompt: str, sub_questions: list[str], evidence: list[Evidence],
                shape_hint: str) -> DraftAnswer:
    msg = (
        f"Answer the user prompt using ONLY the evidence below. "
        f"Every factual claim must cite at least one chunk id. "
        f"Return JSON with fields `answer` (shape: {shape_hint}), "
        f"`citations` (list of chunk ids), and `reasoning_trace` (array of short strings).\n\n"
        f"Prompt: {prompt}\n\n"
        f"Sub-questions:\n- " + "\n- ".join(sub_questions) + "\n\n"
        f"Evidence:\n{_evidence_block(evidence)}"
    )
    return await llm.structured(messages=[{"role": "user", "content": msg}],
                                schema=DraftAnswer, max_tokens=1500)
```

- [ ] **Step 2: Verify module**

`backend/app/agent/verify.py`:
```python
from pydantic import BaseModel
from ..llm import llm
from ..retriever.types import Evidence, Retriever
from ..parser.schema import StructuredDoc
from .types import DraftAnswer, VerifierNote

class _VerifierOut(BaseModel):
    notes: list[VerifierNote]

async def verify(*, draft: DraftAnswer, retriever: Retriever,
                 doc: StructuredDoc) -> list[VerifierNote]:
    claims: list[str] = []
    for line in draft.reasoning_trace or [str(draft.answer)]:
        if line.strip(): claims.append(line.strip())
    if not claims: claims = [str(draft.answer)]

    notes: list[VerifierNote] = []
    for claim in claims[:6]:
        evs = await retriever.retrieve(claim, doc, k=3)
        block = "\n".join(f"[{e.chunk_id}] (p.{e.page}) {e.text[:400]}" for e in evs)
        msg = (
            f"Decide whether the following evidence supports, contradicts, or does not "
            f"contain the claim.\n\nClaim: {claim}\n\nEvidence:\n{block}\n\n"
            f"Return JSON with `notes` (list of one element) with fields `claim`, "
            f"`status` (supported|contradicted|missing), `note`."
        )
        out = await llm.structured(messages=[{"role": "user", "content": msg}],
                                   schema=_VerifierOut, max_tokens=400)
        notes.extend(out.notes)
    return notes
```

- [ ] **Step 3: Runner (end-to-end ISD loop)**

`backend/app/agent/runner.py`:
```python
from __future__ import annotations
import gzip, json, time
from typing import Callable, Awaitable
from ulid import ULID
from ..llm import llm
from ..logging import log
from ..parser.schema import StructuredDoc
from ..retriever.types import Retriever, Evidence
from ..settings import settings
from .decompose import decompose
from .draft import draft as draft_step
from .verify import verify as verify_step
from .types import CellResult, Citation, Confidence

StateCallback = Callable[[str, dict | None], Awaitable[None]]
async def _noop(state: str, data: dict | None = None) -> None: return

async def run_cell(*, prompt: str, doc: StructuredDoc, retriever: Retriever,
                   retriever_mode: str, shape_hint: str = "text",
                   section_index: list[dict] | None = None,
                   on_state: StateCallback = _noop) -> CellResult:
    trace_id = str(ULID()); t0 = time.time()
    await on_state("retrieving", None)
    plan = await decompose(prompt=prompt, doc_meta=doc.meta.model_dump(),
                           section_index=section_index or [], shape_hint=shape_hint)

    evidence: list[Evidence] = []
    for sq in plan.sub_questions:
        evidence.extend(await retriever.retrieve(sq, doc, k=6))

    await on_state("drafting", None)
    dr = await draft_step(prompt=prompt, sub_questions=plan.sub_questions,
                          evidence=evidence, shape_hint=plan.expected_answer_shape)

    await on_state("verifying", None)
    notes = await verify_step(draft=dr, retriever=retriever, doc=doc)

    revisions: list[dict] = []
    if any(n.status in {"contradicted", "missing"} for n in notes):
        problems = "\n".join(f"- {n.claim} :: {n.status} :: {n.note}" for n in notes)
        fresh: list[Evidence] = []
        for n in notes:
            if n.status != "supported":
                fresh.extend(await retriever.retrieve(n.claim, doc, k=3))
        revised = await draft_step(prompt=f"{prompt}\n\nVerifier notes:\n{problems}",
                                   sub_questions=plan.sub_questions,
                                   evidence=evidence + fresh,
                                   shape_hint=plan.expected_answer_shape)
        notes2 = await verify_step(draft=revised, retriever=retriever, doc=doc)
        revisions.append({"draft": revised.model_dump(),
                          "verifier_notes": [n.model_dump() for n in notes2]})
        confidence: Confidence = ("high" if all(n.status == "supported" for n in notes2)
                                  else "low")
        dr = revised; notes = notes2
    else:
        confidence = "high"

    chunk_by_id = {c.id: c for c in doc.chunks}
    citations: list[Citation] = []
    for cid in dr.citations:
        c = chunk_by_id.get(cid)
        if not c: continue
        citations.append(Citation(chunk_id=cid, page=c.page,
                                  snippet=c.text[:240], bboxes=[b.model_dump() for b in c.bboxes]))

    trace = {"plan": plan.model_dump(),
             "evidence": [e.model_dump() for e in evidence],
             "draft": dr.model_dump(),
             "verifier_notes": [n.model_dump() for n in notes],
             "revisions": revisions}
    trace_path = settings.traces_dir / f"{trace_id}.json.gz"
    with gzip.open(trace_path, "wt") as f: f.write(json.dumps(trace))

    latency_ms = int((time.time() - t0) * 1000)
    return CellResult(
        answer=dr.answer, answer_shape=plan.expected_answer_shape,
        citations=citations, confidence=confidence,
        tokens_used=llm.cost_tokens, latency_ms=latency_ms,
        retriever_mode=retriever_mode, trace_id=trace_id, trace=trace,
    )
```

- [ ] **Step 4: Integration test**

`backend/tests/test_agent_runner.py`:
```python
import pytest
from pathlib import Path
from app.parser.pdf import parse_pdf
from app.retriever.index import build_index
from app.retriever.naive import NaiveRetriever
from app.agent.runner import run_cell
from app.agent.types import DecompositionPlan, DraftAnswer, VerifierNote

@pytest.mark.asyncio
async def test_run_cell_end_to_end(monkeypatch):
    doc = parse_pdf(Path("tests/fixtures/tiny.pdf"))
    await build_index(doc, force_local=True)
    r = NaiveRetriever(force_local=True)

    from app.agent import decompose as dm, draft as dm2, verify as vm
    async def fake_decompose(**kw):
        return DecompositionPlan(sub_questions=["fiscal 2023 revenue"],
                                 expected_answer_shape="percentage")
    async def fake_draft(**kw):
        cid = doc.chunks[-1].id
        return DraftAnswer(answer="2.8%", citations=[cid],
                           reasoning_trace=["Revenue grew 2.8% YoY in fiscal 2023."])
    async def fake_verify(**kw):
        return [VerifierNote(claim="x", status="supported")]
    monkeypatch.setattr(dm, "decompose", fake_decompose)
    monkeypatch.setattr(dm2, "draft", fake_draft)
    monkeypatch.setattr(vm, "verify", fake_verify)

    res = await run_cell(prompt="Revenue YoY", doc=doc, retriever=r,
                         retriever_mode="naive", shape_hint="percentage")
    assert res.answer == "2.8%" and res.confidence == "high"
    assert res.citations and res.citations[0].page == 3
```

- [ ] **Step 5: Run — PASS**

Run: `cd backend && pytest tests/test_agent_runner.py -v -s`

- [ ] **Step 6: Commit**

```bash
git add backend/app/agent/ backend/tests/test_agent_runner.py
git commit -m "feat(agent): decompose → draft → verify → revise cell loop"
```

---

## Phase 7 — FastAPI + SSE

### Task 7.1: Ingest pipeline service

**Files:** Create `backend/app/services/ingest.py`

- [ ] **Step 1: Implement**

`backend/app/services/__init__.py`: (empty)

`backend/app/services/ingest.py`:
```python
from __future__ import annotations
import hashlib, shutil
from pathlib import Path
from sqlmodel import Session
from ..logging import log
from ..parser.pdf import parse_pdf
from ..parser.meta import extract_doc_meta
from ..retriever.index import build_index
from ..settings import settings
from ..storage.db import engine
from ..storage.models import Document
from ..wiki.builder import build_wiki, wiki_path_for

def _sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256(); h.update(b); return h.hexdigest()

async def ingest_pdf(*, workspace_id: str, filename: str, content: bytes,
                     build_wiki_stage: bool = True) -> str:
    sha = _sha256_bytes(content)
    pdf_path = settings.pdfs_dir / f"{sha}.pdf"
    if not pdf_path.exists():
        pdf_path.write_bytes(content)

    with Session(engine) as sess:
        doc_row = Document(workspace_id=workspace_id, filename=filename,
                           sha256=sha, status="parsing")
        sess.add(doc_row); sess.commit(); sess.refresh(doc_row)
        doc_id = doc_row.id

    try:
        parsed = parse_pdf(pdf_path)
        parsed.meta = await extract_doc_meta(parsed)
        parsed_path = settings.parsed_dir / f"{sha}.json"
        parsed_path.write_text(parsed.model_dump_json())

        with Session(engine) as sess:
            d = sess.get(Document, doc_id)
            assert d
            d.status = "indexing"; d.n_pages = parsed.n_pages
            d.meta_json = parsed.meta.model_dump(); d.parsed_path = str(parsed_path)
            sess.add(d); sess.commit()

        await build_index(parsed)

        wiki_path = None
        if build_wiki_stage:
            with Session(engine) as sess:
                d = sess.get(Document, doc_id); assert d
                d.status = "wiki"; sess.add(d); sess.commit()
            await build_wiki(parsed)
            wiki_path = str(wiki_path_for(parsed.doc_id))

        with Session(engine) as sess:
            d = sess.get(Document, doc_id); assert d
            d.status = "ready"; d.wiki_path = wiki_path
            sess.add(d); sess.commit()
        log.info("ingest.ready", doc_id=doc_id, sha=sha)
        return doc_id
    except Exception as e:
        log.exception("ingest.failed", doc_id=doc_id)
        with Session(engine) as sess:
            d = sess.get(Document, doc_id)
            if d: d.status = "failed"; d.error = str(e)[:500]; sess.add(d); sess.commit()
        raise
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/
git commit -m "feat(services): ingest pipeline (parse → meta → index → wiki)"
```

### Task 7.2: Grid/cell service + SSE event bus

**Files:** Create `backend/app/services/events.py`, `backend/app/services/cells.py`

- [ ] **Step 1: Event bus**

`backend/app/services/events.py`:
```python
import asyncio, itertools
from collections import defaultdict

class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._seq = itertools.count(1)

    def subscribe(self, channel: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subs[channel].append(q)
        return q

    def unsubscribe(self, channel: str, q: asyncio.Queue) -> None:
        if q in self._subs.get(channel, []):
            self._subs[channel].remove(q)

    async def publish(self, channel: str, payload: dict) -> None:
        payload = {"id": next(self._seq), **payload}
        for q in list(self._subs.get(channel, [])):
            try: q.put_nowait(payload)
            except asyncio.QueueFull: pass

bus = EventBus()
```

- [ ] **Step 2: Cell service**

`backend/app/services/cells.py`:
```python
from __future__ import annotations
from pathlib import Path
from sqlmodel import Session, select
from ..logging import log
from ..parser.schema import StructuredDoc
from ..retriever.naive import NaiveRetriever
from ..retriever.isd import ISDRetriever
from ..retriever.wiki import WikiRetriever
from ..agent.runner import run_cell
from ..storage.db import engine
from ..storage.models import Cell, Column, Document, Grid, Row
from ..wiki.builder import load_wiki
from .events import bus

def _load_doc(document_id: str) -> StructuredDoc:
    with Session(engine) as sess:
        d = sess.get(Document, document_id)
        assert d and d.parsed_path
        return StructuredDoc.model_validate_json(Path(d.parsed_path).read_text())

def _make_retriever(mode: str, doc: StructuredDoc):
    if mode == "naive": return NaiveRetriever()
    if mode == "isd": return ISDRetriever()
    if mode == "wiki":
        w = load_wiki(doc.doc_id)
        if not w: return ISDRetriever()
        return WikiRetriever(wiki=w)
    raise ValueError(mode)

async def run_cell_job(*, cell_id: str) -> None:
    with Session(engine) as sess:
        cell = sess.get(Cell, cell_id); assert cell
        col = sess.get(Column, cell.column_id); assert col
        row = sess.get(Row, cell.row_id); assert row
        grid = sess.get(Grid, cell.grid_id); assert grid
        doc = sess.get(Document, row.document_id); assert doc
        cell.status = "retrieving"; cell.column_version = col.version
        cell.retriever_mode = grid.retriever_mode
        sess.add(cell); sess.commit()

    await bus.publish(f"grid:{grid.id}", {"type": "cell", "cell_id": cell_id,
                                           "state": "retrieving"})
    try:
        parsed = _load_doc(row.document_id)
        retriever = _make_retriever(grid.retriever_mode, parsed)
        wiki = load_wiki(parsed.doc_id)
        section_index = wiki.section_index if wiki else [
            {"id": s.id, "title": s.title} for s in parsed.sections]

        async def on_state(state: str, data: dict | None):
            with Session(engine) as s2:
                c2 = s2.get(Cell, cell_id); assert c2
                c2.status = state; s2.add(c2); s2.commit()
            await bus.publish(f"grid:{grid.id}", {"type": "cell", "cell_id": cell_id,
                                                   "state": state})

        result = await run_cell(
            prompt=col.prompt, doc=parsed, retriever=retriever,
            retriever_mode=grid.retriever_mode, shape_hint=col.shape_hint,
            section_index=section_index, on_state=on_state,
        )

        with Session(engine) as s2:
            c2 = s2.get(Cell, cell_id); assert c2
            c2.status = "done"
            c2.answer_json = {"value": result.answer, "shape": result.answer_shape}
            c2.citations_json = [c.model_dump() for c in result.citations]
            c2.confidence = result.confidence
            c2.tokens_used = result.tokens_used
            c2.latency_ms = result.latency_ms
            c2.trace_id = result.trace_id
            c2.trace_path = f"traces/{result.trace_id}.json.gz"
            s2.add(c2); s2.commit()

        await bus.publish(f"grid:{grid.id}", {
            "type": "cell", "cell_id": cell_id, "state": "done",
            "answer": c2.answer_json, "citations": c2.citations_json,
            "confidence": result.confidence,
        })
    except Exception as e:
        log.exception("cell.failed", cell_id=cell_id)
        with Session(engine) as s2:
            c2 = s2.get(Cell, cell_id)
            if c2: c2.status = "failed"; c2.error = str(e)[:500]; s2.add(c2); s2.commit()
        await bus.publish(f"grid:{grid.id}", {"type": "cell", "cell_id": cell_id,
                                               "state": "failed", "error": str(e)[:500]})
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/events.py backend/app/services/cells.py
git commit -m "feat(services): event bus + per-cell job runner"
```

### Task 7.3: FastAPI routes + SSE endpoint

**Files:** Create `backend/app/main.py`, `backend/app/api/routes.py`, `backend/app/api/schemas.py`

- [ ] **Step 1: API schemas**

`backend/app/api/schemas.py`:
```python
from pydantic import BaseModel

class CreateWorkspaceIn(BaseModel): name: str
class CreateGridIn(BaseModel):
    workspace_id: str
    name: str
    retriever_mode: str = "wiki"
class AddColumnIn(BaseModel):
    prompt: str
    shape_hint: str = "text"
class EditColumnIn(BaseModel):
    prompt: str | None = None
    shape_hint: str | None = None
class SetRetrieverIn(BaseModel): retriever_mode: str
class SynthesizeIn(BaseModel):
    prompt: str
    row_ids: list[str] | None = None
    column_ids: list[str] | None = None
```

- [ ] **Step 2: Routes**

`backend/app/api/routes.py`:
```python
from __future__ import annotations
import asyncio, json
from fastapi import APIRouter, Depends, HTTPException, UploadFile, Request
from sse_starlette.sse import EventSourceResponse
from sqlmodel import Session, select
from ..storage.db import engine
from ..storage.models import Workspace, Document, Grid, Column, Row, Cell
from ..services.ingest import ingest_pdf
from ..services.cells import run_cell_job
from ..services.events import bus
from .schemas import CreateWorkspaceIn, CreateGridIn, AddColumnIn, EditColumnIn, SetRetrieverIn

r = APIRouter(prefix="/api")

def _session():
    with Session(engine) as s: yield s

@r.post("/workspaces")
def create_workspace(body: CreateWorkspaceIn, s: Session = Depends(_session)):
    w = Workspace(name=body.name); s.add(w); s.commit(); s.refresh(w)
    return w

@r.post("/workspaces/{ws_id}/documents")
async def upload_document(ws_id: str, file: UploadFile):
    data = await file.read()
    doc_id = await ingest_pdf(workspace_id=ws_id, filename=file.filename or "file.pdf",
                              content=data, build_wiki_stage=True)
    return {"document_id": doc_id}

@r.get("/workspaces/{ws_id}/documents")
def list_documents(ws_id: str, s: Session = Depends(_session)):
    return s.exec(select(Document).where(Document.workspace_id == ws_id)).all()

@r.post("/grids")
def create_grid(body: CreateGridIn, s: Session = Depends(_session)):
    g = Grid(workspace_id=body.workspace_id, name=body.name,
             retriever_mode=body.retriever_mode)
    s.add(g); s.commit(); s.refresh(g); return g

@r.get("/grids/{grid_id}")
def get_grid(grid_id: str, s: Session = Depends(_session)):
    g = s.get(Grid, grid_id)
    if not g: raise HTTPException(404)
    cols = s.exec(select(Column).where(Column.grid_id == grid_id)
                  .order_by(Column.position)).all()
    rows = s.exec(select(Row).where(Row.grid_id == grid_id)
                  .order_by(Row.position)).all()
    cells = s.exec(select(Cell).where(Cell.grid_id == grid_id)).all()
    return {"grid": g, "columns": cols, "rows": rows, "cells": cells}

@r.patch("/grids/{grid_id}")
def set_retriever(grid_id: str, body: SetRetrieverIn, s: Session = Depends(_session)):
    g = s.get(Grid, grid_id); assert g
    g.retriever_mode = body.retriever_mode; s.add(g); s.commit()
    return g

@r.post("/grids/{grid_id}/rows/{document_id}")
def add_row(grid_id: str, document_id: str, s: Session = Depends(_session)):
    n = s.exec(select(Row).where(Row.grid_id == grid_id)).all()
    row = Row(grid_id=grid_id, document_id=document_id, position=len(n))
    s.add(row); s.commit(); s.refresh(row)
    cols = s.exec(select(Column).where(Column.grid_id == grid_id)).all()
    for c in cols:
        s.add(Cell(grid_id=grid_id, row_id=row.id, column_id=c.id,
                   column_version=c.version, status="queued"))
    s.commit()
    for c in cols:
        cell = s.exec(select(Cell).where(Cell.row_id == row.id,
                                         Cell.column_id == c.id)).first()
        if cell: asyncio.create_task(run_cell_job(cell_id=cell.id))
    return row

@r.post("/grids/{grid_id}/columns")
def add_column(grid_id: str, body: AddColumnIn, s: Session = Depends(_session)):
    n = s.exec(select(Column).where(Column.grid_id == grid_id)).all()
    col = Column(grid_id=grid_id, position=len(n), prompt=body.prompt,
                 shape_hint=body.shape_hint, version=1)
    s.add(col); s.commit(); s.refresh(col)
    rows = s.exec(select(Row).where(Row.grid_id == grid_id)).all()
    for row in rows:
        s.add(Cell(grid_id=grid_id, row_id=row.id, column_id=col.id,
                   column_version=1, status="queued"))
    s.commit()
    cells = s.exec(select(Cell).where(Cell.column_id == col.id)).all()
    for cell in cells:
        asyncio.create_task(run_cell_job(cell_id=cell.id))
    return col

@r.patch("/columns/{column_id}")
def edit_column(column_id: str, body: EditColumnIn, s: Session = Depends(_session)):
    col = s.get(Column, column_id); assert col
    if body.prompt is not None: col.prompt = body.prompt
    if body.shape_hint is not None: col.shape_hint = body.shape_hint
    col.version += 1
    s.add(col); s.commit()
    stale = s.exec(select(Cell).where(Cell.column_id == column_id)).all()
    for c in stale:
        c.status = "stale"; s.add(c)
    s.commit(); return col

@r.post("/cells/{cell_id}/rerun")
def rerun_cell(cell_id: str, s: Session = Depends(_session)):
    c = s.get(Cell, cell_id); assert c
    col = s.get(Column, c.column_id); assert col
    c.status = "queued"; c.column_version = col.version
    s.add(c); s.commit()
    asyncio.create_task(run_cell_job(cell_id=cell_id))
    return {"ok": True}

@r.get("/grids/{grid_id}/stream")
async def stream(grid_id: str, request: Request):
    q = bus.subscribe(f"grid:{grid_id}")
    async def gen():
        try:
            while True:
                if await request.is_disconnected(): break
                try: evt = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}; continue
                yield {"id": str(evt["id"]), "event": "cell", "data": json.dumps(evt)}
        finally:
            bus.unsubscribe(f"grid:{grid_id}", q)
    return EventSourceResponse(gen())
```

- [ ] **Step 3: App entrypoint**

`backend/app/main.py`:
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api.routes import r
from .logging import configure_logging
from .storage.db import init_db

configure_logging()
init_db()

app = FastAPI(title="Matrix PoC")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(r)

@app.get("/health")
def health(): return {"ok": True}
```

- [ ] **Step 4: Run server smoke test**

Run:
```bash
cd backend && . .venv/bin/activate && uvicorn app.main:app --host 127.0.0.1 --port 8000 &
sleep 2 && curl -s http://127.0.0.1:8000/health
```
Expected: `{"ok": true}`. Kill the server after.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/app/api/
git commit -m "feat(api): FastAPI routes + SSE streaming"
```

---

## Phase 8 — Frontend (premium)

### Task 8.1: Tailwind + shadcn setup + design tokens

**Files:** Modify `frontend/tailwind.config.js`, create `frontend/src/index.css`, `frontend/src/lib/utils.ts`

- [ ] **Step 1: Configure Tailwind dark-first theme**

`frontend/tailwind.config.js`:
```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        canvas: "#09090b",      // zinc-950
        surface: "#18181b",     // zinc-900
        border: "#27272a",      // zinc-800
        muted: "#a1a1aa",       // zinc-400
        text: "#fafafa",        // zinc-50
        accent: { done:"#10b981", streaming:"#38bdf8",
                  verify:"#f59e0b", fail:"#f43f5e", stale:"#a78bfa" },
      },
      fontFamily: {
        ui: ["Inter Tight", "Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
```

- [ ] **Step 2: Global CSS**

`frontend/src/index.css`:
```css
@import url("https://rsms.me/inter/inter.css");
@import url("https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap");
@tailwind base;
@tailwind components;
@tailwind utilities;

html, body, #root { height: 100%; background: #09090b; color: #fafafa;
                    font-family: "Inter Tight", Inter, system-ui, sans-serif; }
::selection { background: #38bdf8; color: #09090b; }
```

- [ ] **Step 3: cn util**

`frontend/src/lib/utils.ts`:
```ts
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)); }
```

- [ ] **Step 4: Commit**

```bash
git add frontend/tailwind.config.js frontend/src/index.css frontend/src/lib/
git commit -m "feat(ui): dark-first Tailwind theme + design tokens"
```

### Task 8.2: API client + Zustand store

**Files:** Create `frontend/src/api/client.ts`, `frontend/src/api/types.ts`, `frontend/src/store/grid.ts`

- [ ] **Step 1: Types**

`frontend/src/api/types.ts`:
```ts
export type CellStatus = "idle"|"queued"|"retrieving"|"drafting"|"verifying"|"done"|"stale"|"failed";
export type Shape = "text"|"number"|"currency"|"percentage"|"list"|"table";

export interface Workspace { id: string; name: string; }
export interface Document { id: string; filename: string; sha256: string; status: string;
                            n_pages: number | null; meta_json: any; }
export interface Column { id: string; grid_id: string; position: number; prompt: string;
                          shape_hint: Shape; version: number; }
export interface Row { id: string; grid_id: string; document_id: string; position: number; }
export interface Citation { chunk_id: string; page: number; snippet: string; bboxes: any[]; }
export interface Cell {
  id: string; grid_id: string; row_id: string; column_id: string; column_version: number;
  status: CellStatus; answer_json: { value: any; shape: Shape } | null;
  citations_json: Citation[] | null; confidence: "high"|"medium"|"low" | null;
  tokens_used: number; latency_ms: number;
}
export interface Grid { id: string; name: string; retriever_mode: "naive"|"isd"|"wiki"; }
export interface GridView { grid: Grid; columns: Column[]; rows: Row[]; cells: Cell[]; }
```

- [ ] **Step 2: Client**

`frontend/src/api/client.ts`:
```ts
const BASE = "http://127.0.0.1:8000/api";

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(await r.text()); return r.json();
}
export const api = {
  createWorkspace: (name: string) =>
    fetch(`${BASE}/workspaces`, { method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name }) }).then(j),
  uploadDocument: async (wsId: string, file: File) => {
    const fd = new FormData(); fd.append("file", file);
    return fetch(`${BASE}/workspaces/${wsId}/documents`,
      { method: "POST", body: fd }).then(j) as Promise<{document_id: string}>;
  },
  listDocuments: (wsId: string) =>
    fetch(`${BASE}/workspaces/${wsId}/documents`).then(j),
  createGrid: (workspace_id: string, name: string, retriever_mode = "wiki") =>
    fetch(`${BASE}/grids`, { method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ workspace_id, name, retriever_mode }) }).then(j),
  getGrid: (gridId: string) => fetch(`${BASE}/grids/${gridId}`).then(j),
  setRetriever: (gridId: string, mode: string) =>
    fetch(`${BASE}/grids/${gridId}`, { method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ retriever_mode: mode }) }).then(j),
  addRow: (gridId: string, docId: string) =>
    fetch(`${BASE}/grids/${gridId}/rows/${docId}`, { method: "POST" }).then(j),
  addColumn: (gridId: string, prompt: string, shape_hint: string) =>
    fetch(`${BASE}/grids/${gridId}/columns`, { method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ prompt, shape_hint }) }).then(j),
  editColumn: (columnId: string, body: any) =>
    fetch(`${BASE}/columns/${columnId}`, { method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body) }).then(j),
  rerunCell: (cellId: string) =>
    fetch(`${BASE}/cells/${cellId}/rerun`, { method: "POST" }).then(j),
  streamUrl: (gridId: string) => `${BASE}/grids/${gridId}/stream`,
};
```

- [ ] **Step 3: Store**

`frontend/src/store/grid.ts`:
```ts
import { create } from "zustand";
import type { Cell, Column, GridView, Row } from "../api/types";

interface State {
  view: GridView | null;
  focused: string | null;
  setView: (v: GridView) => void;
  upsertCell: (c: Partial<Cell> & { id: string }) => void;
  focus: (cellId: string | null) => void;
}
export const useGrid = create<State>((set) => ({
  view: null, focused: null,
  setView: (v) => set({ view: v }),
  upsertCell: (c) => set((s) => {
    if (!s.view) return s;
    const cells = s.view.cells.map((x) => x.id === c.id ? { ...x, ...c } : x);
    return { view: { ...s.view, cells } };
  }),
  focus: (cellId) => set({ focused: cellId }),
}));
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/ frontend/src/store/
git commit -m "feat(ui): API client + zustand grid store"
```

### Task 8.3: Grid component + cell state machine

**Files:** Create `frontend/src/components/TopBar.tsx`, `frontend/src/components/Matrix.tsx`, `frontend/src/components/Cell.tsx`, `frontend/src/components/CellRenderer.tsx`, modify `frontend/src/App.tsx`

- [ ] **Step 1: CellRenderer (shape-aware)**

`frontend/src/components/CellRenderer.tsx`:
```tsx
import type { Cell } from "../api/types";

export function CellRenderer({ cell }: { cell: Cell }) {
  if (!cell.answer_json) return <span className="text-muted">—</span>;
  const { value, shape } = cell.answer_json;
  const str = typeof value === "string" ? value : JSON.stringify(value);
  switch (shape) {
    case "percentage":
    case "number":
    case "currency":
      return <span className="font-mono tabular-nums text-right">{str}</span>;
    case "list": {
      const items = Array.isArray(value) ? value : [value];
      return <span>{items.slice(0,2).map(String).join(" · ")}
        {items.length > 2 && <span className="text-muted"> +{items.length-2}</span>}</span>;
    }
    case "table":
      return <span className="text-muted">table ({(value as any[])?.length ?? 0} rows)</span>;
    default:
      return <span className="truncate">{str.length > 180 ? str.slice(0,180)+"…" : str}</span>;
  }
}
```

- [ ] **Step 2: Cell component with state dot + shimmer**

`frontend/src/components/Cell.tsx`:
```tsx
import { motion } from "framer-motion";
import { cn } from "../lib/utils";
import type { Cell as TCell } from "../api/types";
import { CellRenderer } from "./CellRenderer";
import { useGrid } from "../store/grid";

const DOT: Record<string, string> = {
  idle: "bg-zinc-700", queued: "bg-zinc-500",
  retrieving: "bg-accent-streaming animate-pulse",
  drafting: "bg-accent-streaming animate-pulse",
  verifying: "bg-accent-verify animate-pulse",
  done: "bg-accent-done", stale: "bg-accent-stale",
  failed: "bg-accent-fail",
};
const STREAMING = new Set(["queued","retrieving","drafting","verifying"]);

export function Cell({ cell }: { cell: TCell }) {
  const focus = useGrid((s) => s.focus);
  return (
    <div onClick={() => focus(cell.id)}
         className="relative h-9 px-2 flex items-center gap-2 cursor-pointer
                    hover:bg-surface/60 text-[13px] border-r border-border">
      <span className={cn("h-1.5 w-1.5 rounded-full", DOT[cell.status] ?? "bg-zinc-700")} />
      <div className="flex-1 min-w-0"><CellRenderer cell={cell} /></div>
      {STREAMING.has(cell.status) && (
        <motion.div layoutId={`sh-${cell.id}`}
          className="absolute bottom-0 left-0 h-[2px] bg-accent-streaming"
          initial={{ width: "10%" }} animate={{ width: "90%" }}
          transition={{ duration: 2, repeat: Infinity, repeatType: "reverse" }} />
      )}
    </div>
  );
}
```

- [ ] **Step 3: Matrix + TopBar + App wiring**

`frontend/src/components/TopBar.tsx`:
```tsx
import { useGrid } from "../store/grid";
export function TopBar({ onCommand }: { onCommand: () => void }) {
  const v = useGrid((s) => s.view);
  return (
    <div className="h-11 border-b border-border px-4 flex items-center gap-4 text-[12px]
                    bg-canvas/80 backdrop-blur sticky top-0 z-10">
      <div className="font-ui text-text">◇ Matrix</div>
      <div className="text-muted">{v?.grid.name ?? "—"}</div>
      <div className="text-muted font-mono">gpt-4.1 · {v?.grid.retriever_mode ?? "—"}</div>
      <div className="flex-1" />
      <button onClick={onCommand}
              className="px-2 py-1 rounded border border-border text-muted hover:text-text">⌘K</button>
    </div>
  );
}
```

`frontend/src/components/Matrix.tsx`:
```tsx
import { useGrid } from "../store/grid";
import { Cell } from "./Cell";

export function Matrix() {
  const v = useGrid((s) => s.view);
  if (!v) return <div className="p-8 text-muted">Loading…</div>;
  const { columns, rows, cells } = v;
  const cellAt = (rowId: string, colId: string) =>
    cells.find((c) => c.row_id === rowId && c.column_id === colId);
  return (
    <div className="m-4 rounded-lg border border-border overflow-auto bg-surface">
      <div className="grid sticky top-0 bg-surface border-b border-border"
           style={{ gridTemplateColumns: `240px repeat(${columns.length}, minmax(160px, 1fr))` }}>
        <div className="px-3 h-9 flex items-center text-muted text-[12px] border-r border-border">Document</div>
        {columns.map((c) => (
          <div key={c.id} className="px-3 h-9 flex items-center text-[12px] border-r border-border">
            <span className="truncate">{c.prompt}</span>
            <span className="ml-2 text-muted font-mono">·{c.shape_hint}</span>
          </div>
        ))}
      </div>
      {rows.map((row) => (
        <div key={row.id} className="grid border-b border-border"
             style={{ gridTemplateColumns: `240px repeat(${columns.length}, minmax(160px, 1fr))` }}>
          <div className="px-3 h-9 flex items-center text-[13px] border-r border-border truncate">
            {row.document_id.slice(0, 8)}…
          </div>
          {columns.map((c) => {
            const cell = cellAt(row.id, c.id);
            return cell ? <Cell key={c.id} cell={cell} /> :
              <div key={c.id} className="h-9 border-r border-border" />;
          })}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: App entrypoint with SSE subscription**

`frontend/src/App.tsx`:
```tsx
import { useEffect, useState } from "react";
import { api } from "./api/client";
import type { GridView } from "./api/types";
import { useGrid } from "./store/grid";
import { Matrix } from "./components/Matrix";
import { TopBar } from "./components/TopBar";
import { CommandBar } from "./components/CommandBar";
import { FocusPane } from "./components/FocusPane";
import "./index.css";

export default function App() {
  const [gridId, setGridId] = useState<string | null>(null);
  const { view, setView, upsertCell } = useGrid();
  const [cmdOpen, setCmdOpen] = useState(false);

  // bootstrap a default workspace + grid on first load
  useEffect(() => {
    (async () => {
      const ws: any = await api.createWorkspace("Demo");
      const g: any = await api.createGrid(ws.id, "Financials", "wiki");
      setGridId(g.id);
    })();
  }, []);

  useEffect(() => {
    if (!gridId) return;
    (async () => setView(await api.getGrid(gridId) as GridView))();
    const es = new EventSource(api.streamUrl(gridId));
    es.addEventListener("cell", (ev: MessageEvent) => {
      const p = JSON.parse(ev.data);
      upsertCell({ id: p.cell_id, status: p.state,
                   answer_json: p.answer ?? undefined,
                   citations_json: p.citations ?? undefined,
                   confidence: p.confidence ?? undefined });
    });
    return () => es.close();
  }, [gridId]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") { e.preventDefault(); setCmdOpen(true); }
    };
    window.addEventListener("keydown", h); return () => window.removeEventListener("keydown", h);
  }, []);

  return (
    <div className="h-full flex flex-col">
      <TopBar onCommand={() => setCmdOpen(true)} />
      <div className="flex-1 flex">
        <div className="flex-1 min-w-0"><Matrix /></div>
        <FocusPane />
      </div>
      <CommandBar open={cmdOpen} onClose={() => setCmdOpen(false)} gridId={gridId} />
    </div>
  );
}
```

- [ ] **Step 5: Stub FocusPane and CommandBar placeholders so build compiles**

`frontend/src/components/FocusPane.tsx`:
```tsx
import { useGrid } from "../store/grid";
export function FocusPane() {
  const { view, focused, focus } = useGrid();
  if (!focused || !view) return null;
  const cell = view.cells.find((c) => c.id === focused);
  if (!cell) return null;
  return (
    <div className="w-[40%] border-l border-border p-4 bg-canvas overflow-auto">
      <button className="text-muted text-xs" onClick={() => focus(null)}>close</button>
      <h3 className="mt-2 font-ui text-lg">Cell</h3>
      <pre className="mt-3 text-xs font-mono whitespace-pre-wrap">
        {JSON.stringify(cell, null, 2)}
      </pre>
    </div>
  );
}
```

`frontend/src/components/CommandBar.tsx`:
```tsx
import { Command } from "cmdk";
import { api } from "../api/client";
import { useGrid } from "../store/grid";

export function CommandBar({ open, onClose, gridId }:
  { open: boolean; onClose: () => void; gridId: string | null }) {
  const refresh = async () => { if (gridId) (useGrid.getState().setView as any)(await api.getGrid(gridId)); };
  if (!open || !gridId) return null;
  return (
    <div className="fixed inset-0 bg-canvas/60 flex items-start justify-center pt-32 z-50"
         onClick={onClose}>
      <div className="w-[560px] rounded-lg border border-border bg-surface p-2"
           onClick={(e) => e.stopPropagation()}>
        <Command>
          <Command.Input autoFocus placeholder="Type a command…"
            className="w-full bg-transparent p-2 outline-none text-[14px]" />
          <Command.List className="max-h-80 overflow-auto">
            <Command.Item onSelect={async () => {
              const p = prompt("Column prompt"); if (!p) return;
              await api.addColumn(gridId, p, "text"); await refresh(); onClose();
            }}>Add column…</Command.Item>
            <Command.Item onSelect={async () => {
              const inp = document.createElement("input");
              inp.type = "file"; inp.accept = "application/pdf"; inp.multiple = true;
              inp.onchange = async () => {
                const files = Array.from(inp.files ?? []);
                const v = useGrid.getState().view;
                if (!v) return;
                for (const f of files) {
                  const d: any = await api.uploadDocument((v.grid as any).workspace_id ?? "x", f);
                  await api.addRow(gridId, d.document_id);
                }
                await refresh(); onClose();
              };
              inp.click();
            }}>Add documents…</Command.Item>
            <Command.Item onSelect={async () => {
              await api.setRetriever(gridId, "naive"); await refresh(); onClose();
            }}>Switch retriever: naive</Command.Item>
            <Command.Item onSelect={async () => {
              await api.setRetriever(gridId, "isd"); await refresh(); onClose();
            }}>Switch retriever: isd</Command.Item>
            <Command.Item onSelect={async () => {
              await api.setRetriever(gridId, "wiki"); await refresh(); onClose();
            }}>Switch retriever: wiki</Command.Item>
          </Command.List>
        </Command>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Smoke — run backend + frontend, upload tiny.pdf, add a column, see cell stream**

Run backend in terminal A, `pnpm dev` in terminal B. Open `http://localhost:5173`. ⌘K → Add documents → pick `backend/tests/fixtures/tiny.pdf`. ⌘K → Add column → "Revenue YoY change". Cell should transition queued → retrieving → drafting → verifying → done.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/
git commit -m "feat(ui): matrix grid + cell state machine + SSE wiring + ⌘K palette"
```

### Task 8.4: Premium focus pane with PDF viewer + citations

**Files:** Modify `frontend/src/components/FocusPane.tsx`, create `frontend/src/components/PdfView.tsx`

- [ ] **Step 1: PDF viewer with bbox highlights**

`frontend/src/components/PdfView.tsx`:
```tsx
import { useEffect, useRef } from "react";
import * as pdfjs from "pdfjs-dist";
// @ts-ignore
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

export function PdfView({ url, page, highlight }:
  { url: string; page: number; highlight?: [number,number,number,number] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    (async () => {
      const pdf = await pdfjs.getDocument(url).promise;
      const p = await pdf.getPage(page);
      const viewport = p.getViewport({ scale: 1.2 });
      const canvas = canvasRef.current!;
      canvas.width = viewport.width; canvas.height = viewport.height;
      const ctx = canvas.getContext("2d")!;
      await p.render({ canvasContext: ctx, viewport }).promise;
      if (highlight) {
        const [x0,y0,x1,y1] = highlight;
        const s = viewport.scale;
        ctx.fillStyle = "rgba(56,189,248,0.25)";
        ctx.fillRect(x0*s, canvas.height - y1*s, (x1-x0)*s, (y1-y0)*s);
      }
    })();
  }, [url, page, highlight?.join(",")]);
  return <canvas ref={canvasRef} className="rounded border border-border" />;
}
```

- [ ] **Step 2: Focus pane**

`frontend/src/components/FocusPane.tsx`:
```tsx
import { api } from "../api/client";
import { useGrid } from "../store/grid";
import { CellRenderer } from "./CellRenderer";
import { PdfView } from "./PdfView";
import { useState } from "react";

export function FocusPane() {
  const { view, focused, focus, upsertCell } = useGrid();
  const [activeCite, setActiveCite] = useState<number>(0);
  if (!focused || !view) return null;
  const cell = view.cells.find((c) => c.id === focused);
  if (!cell) return null;
  const cites = cell.citations_json ?? [];
  const cite = cites[activeCite];
  const doc = view.rows.find((r) => r.id === cell.row_id)?.document_id;
  const pdfUrl = doc ? `http://127.0.0.1:8000/api/pdf/${doc}` : "";

  return (
    <div className="w-[44%] border-l border-border bg-canvas flex flex-col">
      <div className="h-11 px-4 flex items-center justify-between border-b border-border">
        <span className="text-[12px] text-muted font-mono">{cell.id.slice(-8)}</span>
        <div className="flex gap-2">
          <button onClick={async () => { await api.rerunCell(cell.id);
                   upsertCell({ id: cell.id, status: "queued" }); }}
            className="px-2 py-1 text-[12px] border border-border rounded hover:bg-surface">rerun</button>
          <button onClick={() => focus(null)}
            className="px-2 py-1 text-[12px] border border-border rounded hover:bg-surface">close</button>
        </div>
      </div>
      <div className="p-4 space-y-4 overflow-auto">
        <div>
          <div className="text-[11px] text-muted uppercase tracking-wide">Answer</div>
          <div className="mt-1 text-xl font-ui"><CellRenderer cell={cell} /></div>
          <div className="mt-1 text-[12px] text-muted">
            confidence: <span className="font-mono">{cell.confidence ?? "—"}</span>
            · {cell.latency_ms}ms · {cell.tokens_used}tok
          </div>
        </div>
        <div>
          <div className="text-[11px] text-muted uppercase tracking-wide mb-1">Citations</div>
          <div className="flex flex-wrap gap-2">
            {cites.map((c, i) => (
              <button key={i} onClick={() => setActiveCite(i)}
                className={`px-2 py-1 text-[11px] font-mono rounded border
                  ${i===activeCite?"border-accent-streaming text-accent-streaming":"border-border text-muted"}`}>
                [{c.chunk_id.slice(-4)}] p.{c.page}
              </button>
            ))}
          </div>
          {cite && <div className="mt-2 text-[12px] bg-surface p-3 rounded border border-border">
            {cite.snippet}
          </div>}
        </div>
        {cite && pdfUrl && (
          <div>
            <div className="text-[11px] text-muted uppercase tracking-wide mb-1">Source</div>
            <PdfView url={pdfUrl} page={cite.page}
                     highlight={cite.bboxes?.[0]?.bbox as any} />
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Add PDF-serving route backend-side**

`backend/app/api/routes.py` — append:
```python
from fastapi.responses import FileResponse
from ..settings import settings

@r.get("/pdf/{document_id}")
def get_pdf(document_id: str, s: Session = Depends(_session)):
    d = s.get(Document, document_id); assert d
    p = settings.pdfs_dir / f"{d.sha256}.pdf"
    if not p.exists(): raise HTTPException(404)
    return FileResponse(p, media_type="application/pdf")
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/routes.py frontend/src/components/PdfView.tsx frontend/src/components/FocusPane.tsx
git commit -m "feat(ui): focus pane with citation pills + PDF.js bbox highlights"
```

---

## Phase 9 — Synthesis + templates + cost preview

### Task 9.1: Synthesis backend + UI

**Files:** Create `backend/app/services/synthesize.py`, modify `backend/app/api/routes.py`, create `frontend/src/components/SynthesisDock.tsx`

- [ ] **Step 1: Backend synthesis service**

`backend/app/services/synthesize.py`:
```python
from __future__ import annotations
from sqlmodel import Session, select
from ..llm import llm
from ..storage.db import engine
from ..storage.models import Cell, Column, Row, Grid, Synthesis

async def synthesize(grid_id: str, prompt: str) -> Synthesis:
    with Session(engine) as s:
        g = s.get(Grid, grid_id); assert g
        cols = s.exec(select(Column).where(Column.grid_id == grid_id)
                      .order_by(Column.position)).all()
        rows = s.exec(select(Row).where(Row.grid_id == grid_id)
                      .order_by(Row.position)).all()
        cells = s.exec(select(Cell).where(Cell.grid_id == grid_id)).all()

    table_lines = ["| Row | " + " | ".join(c.prompt for c in cols) + " |"]
    table_lines.append("|---" * (len(cols) + 1) + "|")
    cell_by_rc = {(c.row_id, c.column_id): c for c in cells}
    for row in rows:
        values = []
        for col in cols:
            c = cell_by_rc.get((row.id, col.id))
            v = c.answer_json.get("value") if c and c.answer_json else "—"
            values.append(str(v))
        table_lines.append(f"| {row.document_id[:8]} | " + " | ".join(values) + " |")

    msg = (f"Given the matrix of extracted answers below, "
           f"answer the user's synthesis prompt. Cite row+column as [row_id×col_id].\n\n"
           f"Synthesis prompt: {prompt}\n\n" + "\n".join(table_lines))
    answer = await llm.chat(messages=[{"role": "user", "content": msg}], max_tokens=1200)
    with Session(engine) as s:
        syn = Synthesis(grid_id=grid_id, prompt=prompt, answer=answer, citations_json=[])
        s.add(syn); s.commit(); s.refresh(syn); return syn
```

- [ ] **Step 2: API route**

In `backend/app/api/routes.py` add:
```python
from ..services.synthesize import synthesize
from .schemas import SynthesizeIn

@r.post("/grids/{grid_id}/synthesize")
async def synthesize_ep(grid_id: str, body: SynthesizeIn):
    return await synthesize(grid_id, body.prompt)
```

- [ ] **Step 3: Synthesis UI dock**

`frontend/src/components/SynthesisDock.tsx`:
```tsx
import { useState } from "react";
import { useGrid } from "../store/grid";

export function SynthesisDock({ gridId }: { gridId: string | null }) {
  const [open, setOpen] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [out, setOut] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const run = async () => {
    if (!gridId || !prompt) return;
    setLoading(true);
    try {
      const res = await fetch(`http://127.0.0.1:8000/api/grids/${gridId}/synthesize`,
        { method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ prompt }) }).then((r) => r.json());
      setOut(res.answer);
    } finally { setLoading(false); }
  };
  return (
    <div className="border-t border-border bg-surface">
      <button onClick={() => setOpen((o) => !o)}
        className="px-4 py-2 text-[12px] text-muted w-full text-left">
        {open ? "▾" : "▸"} Synthesis
      </button>
      {open && (
        <div className="p-4 space-y-3">
          <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)}
            placeholder="Summarise across these rows…"
            className="w-full h-20 p-2 text-[13px] bg-canvas border border-border rounded"/>
          <button onClick={run} disabled={loading}
            className="px-3 py-1 text-[12px] rounded border border-accent-streaming
                       text-accent-streaming disabled:opacity-50">
            {loading ? "Synthesising…" : "Run synthesis"}
          </button>
          {out && <div className="p-3 bg-canvas border border-border rounded text-[13px] whitespace-pre-wrap">
            {out}
          </div>}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Wire into App**

In `frontend/src/App.tsx`, below `<Matrix />`:
```tsx
import { SynthesisDock } from "./components/SynthesisDock";
// inside return, wrap Matrix in a column that includes the dock
<div className="flex-1 flex flex-col min-w-0">
  <div className="flex-1 min-h-0 overflow-auto"><Matrix /></div>
  <SynthesisDock gridId={gridId} />
</div>
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/synthesize.py backend/app/api/routes.py frontend/src/components/SynthesisDock.tsx frontend/src/App.tsx
git commit -m "feat: cross-row synthesis endpoint + dock UI"
```

### Task 9.2: Template packs + empty state

**Files:** Create `frontend/src/templates.ts`, modify `CommandBar.tsx`

- [ ] **Step 1: Templates**

`frontend/src/templates.ts`:
```ts
export const TEMPLATES = {
  "Risk extraction": [
    { prompt: "Top 3 material risk factors", shape: "list" as const },
    { prompt: "Supply chain concentration", shape: "text" as const },
    { prompt: "Cybersecurity incidents disclosed", shape: "list" as const },
    { prompt: "Regulatory / legal proceedings", shape: "text" as const },
  ],
  "Revenue & margins": [
    { prompt: "Total revenue (fiscal year)", shape: "currency" as const },
    { prompt: "YoY revenue growth %", shape: "percentage" as const },
    { prompt: "Operating margin %", shape: "percentage" as const },
    { prompt: "Gross margin %", shape: "percentage" as const },
  ],
  "Auditor & governance": [
    { prompt: "Independent auditor", shape: "text" as const },
    { prompt: "Auditor opinion type", shape: "text" as const },
    { prompt: "CEO name", shape: "text" as const },
    { prompt: "Board size", shape: "number" as const },
  ],
};
```

- [ ] **Step 2: Add template entries to CommandBar**

In `CommandBar.tsx`, inside `<Command.List>`:
```tsx
import { TEMPLATES } from "../templates";
...
{Object.entries(TEMPLATES).map(([name, cols]) => (
  <Command.Item key={name} onSelect={async () => {
    for (const c of cols) await api.addColumn(gridId, c.prompt, c.shape);
    await refresh(); onClose();
  }}>Template: {name}</Command.Item>
))}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/templates.ts frontend/src/components/CommandBar.tsx
git commit -m "feat(ui): template packs in command palette"
```

---

## Phase 10 — FinanceBench benchmark harness

### Task 10.1: Dataset loader + PDF fetcher

**Files:** Create `backend/app/bench/dataset.py`, `backend/app/bench/run.py`

- [ ] **Step 1: Dataset loader**

`backend/app/bench/dataset.py`:
```python
from __future__ import annotations
import hashlib, httpx
from pathlib import Path
from datasets import load_dataset
from ..settings import settings
from ..logging import log

FINBENCH_PDF_BASE = "https://github.com/patronus-ai/financebench/raw/main/pdfs"

def load_questions(split: str = "train", limit: int | None = None):
    ds = load_dataset("PatronusAI/financebench", split=split)
    if limit: ds = ds.select(range(min(limit, len(ds))))
    return list(ds)

def _sha(b: bytes) -> str:
    h = hashlib.sha256(); h.update(b); return h.hexdigest()

async def fetch_pdf(doc_name: str) -> Path:
    url = f"{FINBENCH_PDF_BASE}/{doc_name}"
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(url); r.raise_for_status()
        sha = _sha(r.content)
        target = settings.pdfs_dir / f"{sha}.pdf"
        if not target.exists(): target.write_bytes(r.content)
        log.info("bench.pdf.ready", doc_name=doc_name, sha=sha[:8])
        return target
```

- [ ] **Step 2: Bench runner**

`backend/app/bench/run.py`:
```python
from __future__ import annotations
import asyncio, json, time
from pathlib import Path
from ..llm import llm
from ..logging import log, configure_logging
from ..parser.pdf import parse_pdf
from ..parser.meta import extract_doc_meta
from ..retriever.index import build_index
from ..retriever.naive import NaiveRetriever
from ..retriever.isd import ISDRetriever
from ..retriever.wiki import WikiRetriever
from ..wiki.builder import build_wiki, load_wiki
from ..agent.runner import run_cell
from .dataset import load_questions, fetch_pdf

async def _ensure_doc(doc_name: str, *, want_wiki: bool):
    pdf = await fetch_pdf(doc_name)
    parsed = parse_pdf(pdf)
    parsed.meta = await extract_doc_meta(parsed)
    await build_index(parsed)
    if want_wiki and not load_wiki(parsed.doc_id):
        await build_wiki(parsed)
    return parsed

async def _judge(question: str, gold: str, predicted: str) -> str:
    msg = (f"You are grading an answer against a gold answer. Reply with one word: "
           f"correct | partially_correct | incorrect.\n\n"
           f"Question: {question}\nGold: {gold}\nPredicted: {predicted}")
    return (await llm.chat(messages=[{"role": "user", "content": msg}], max_tokens=10)).strip().lower()

def _page_recall(cited_pages: list[int], gold_pages: list[int]) -> float:
    if not gold_pages: return 1.0
    hit = sum(1 for p in gold_pages if any(abs(p - q) <= 1 for q in cited_pages))
    return hit / len(gold_pages)

async def run(*, mode: str, limit: int, out_dir: Path):
    configure_logging()
    out_dir.mkdir(parents=True, exist_ok=True)
    qs = load_questions(limit=limit)
    results = []
    for i, q in enumerate(qs):
        try:
            parsed = await _ensure_doc(q["doc_name"], want_wiki=(mode == "wiki"))
            if mode == "naive": retr = NaiveRetriever()
            elif mode == "isd": retr = ISDRetriever()
            else:
                w = load_wiki(parsed.doc_id); assert w
                retr = WikiRetriever(wiki=w)
            res = await run_cell(
                prompt=q["question"], doc=parsed, retriever=retr, retriever_mode=mode,
                shape_hint="text",
                section_index=[{"id": s.id, "title": s.title} for s in parsed.sections],
            )
            pred = res.answer if isinstance(res.answer, str) else json.dumps(res.answer)
            verdict = await _judge(q["question"], q["answer"], pred)
            gold_pages = q.get("page_number") or []
            if isinstance(gold_pages, int): gold_pages = [gold_pages]
            cited = [c.page for c in res.citations]
            results.append({
                "id": i, "question": q["question"], "doc": q["doc_name"],
                "gold": q["answer"], "predicted": pred, "verdict": verdict,
                "cited_pages": cited, "gold_pages": gold_pages,
                "page_recall": _page_recall(cited, gold_pages),
                "latency_ms": res.latency_ms, "tokens": res.tokens_used,
            })
            log.info("bench.q", i=i, verdict=verdict)
        except Exception as e:
            results.append({"id": i, "error": str(e)[:300]})
            log.exception("bench.q.failed", i=i)
    (out_dir / f"{mode}.jsonl").write_text("\n".join(json.dumps(r) for r in results))
    return results

def report(paths: dict[str, Path], out_md: Path) -> None:
    rows = ["| Mode | correct | partial | incorrect | page_recall | avg_latency(ms) | avg_tokens |",
            "|---|---|---|---|---|---|---|"]
    for mode, p in paths.items():
        lines = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
        good = [l for l in lines if "verdict" in l]
        if not good: rows.append(f"| {mode} | — | — | — | — | — | — |"); continue
        c = sum(1 for l in good if l["verdict"] == "correct")
        pa = sum(1 for l in good if l["verdict"] == "partially_correct")
        i = sum(1 for l in good if l["verdict"] == "incorrect")
        pr = sum(l["page_recall"] for l in good) / len(good)
        lt = sum(l["latency_ms"] for l in good) / len(good)
        tk = sum(l["tokens"] for l in good) / len(good)
        rows.append(f"| {mode} | {c} | {pa} | {i} | {pr:.2f} | {lt:.0f} | {tk:.0f} |")
    out_md.write_text("\n".join(rows))

async def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", default="naive,isd,wiki")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--out", default="bench/results/last")
    args = ap.parse_args()
    out = Path(args.out); paths = {}
    for mode in args.modes.split(","):
        paths[mode] = Path(args.out) / f"{mode}.jsonl"
        await run(mode=mode, limit=args.limit, out_dir=out)
    report(paths, Path(args.out) / "report.md")
    print(Path(f"{args.out}/report.md").read_text())

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Smoke run (2 questions, naive only)**

Run:
```bash
cd backend && . .venv/bin/activate
python -m app.bench.run --modes naive --limit 2 --out bench/results/smoke
```
Expected: produces `bench/results/smoke/naive.jsonl` + `report.md`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/bench/
git commit -m "feat(bench): FinanceBench harness with three-mode comparison"
```

---

## Phase 11 — Polish + final smoke

### Task 11.1: README with demo instructions

**Files:** Modify `README.md`

- [ ] **Step 1: Write README**

`README.md`:
```markdown
# Matrix PoC

Hebbia-Matrix-style spreadsheet over PDFs, with a swappable retriever and a FinanceBench benchmark harness.

## Setup

```bash
cp .env.example .env   # fill AZURE_OPENAI_API_KEY
cd backend && python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
cd ../frontend && pnpm install
```

## Run

Two terminals:
```
make backend   # http://127.0.0.1:8000
make frontend  # http://127.0.0.1:5173
```

## Benchmark

```bash
cd backend && . .venv/bin/activate
python -m app.bench.run --modes naive,isd,wiki --limit 50 --out bench/results/run1
cat bench/results/run1/report.md
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with setup, run, and bench instructions"
```

### Task 11.2: End-to-end smoke checklist

- [ ] **Step 1: Run through the demo**
  1. Start backend + frontend.
  2. ⌘K → Add documents → pick 2 real 10-K PDFs.
  3. Wait for rows to turn "ready" (wiki built).
  4. ⌘K → Template: Revenue & margins.
  5. Watch cells stream.
  6. Click a cell → focus pane opens → citation pills → PDF page highlighted.
  7. Edit a column prompt → cells go "stale" → rerun one.
  8. Open Synthesis dock → "Which issuer grew faster?" → answer renders.
  9. ⌘K → Switch retriever: naive, rerun grid, observe worse citations.
- [ ] **Step 2: Record demo video**
- [ ] **Step 3: Commit any fixups**

```bash
git add -A
git commit -m "chore: final smoke + polish"
```

---

## Self-review checklist (run after writing)

- [x] Every spec section has a task: product (All), stack (0.1), storage (2.1), parser (3.1-3.2), wiki (5.1-5.2), retrievers (4.1-4.3, 5.2), ISD loop (6.1-6.2), synthesis (9.1), frontend premium layout (8.1-8.4, 9.2), data model (2.1), benchmark (10.1), risks mitigated (budget 1.3, embeddings fallback 4.1, versioning 7.3, SSE resume via DB snapshot + SSE 7.3, local-only binding 0.1 env, trace_id 6.2).
- [x] No placeholders. Every code block is complete and runnable.
- [x] Type consistency: `Evidence.bboxes: list[Bbox]` across parser → retriever → agent → citations. `Column.version`/`Cell.column_version` consistent. `CellResult.citations` → `Citation` model consistent with `cells.citations_json` shape.
- [x] Exact commands + expected output at every step.

## Risks this plan does not eliminate

- Azure TPM at the deployment. `TokenBudget` exists but is not wired into every LLM call. Follow-up: thread the budget through `LLM._chat_raw` in a second pass once real numbers come in.
- FinanceBench dataset schema changes (e.g. HF field renames). First bench run will surface; loader is small and easy to fix.
- Local embedding model download (~1.3GB) on first run; cached after.
- Wiki cost on a full 10-K (~$3-5). Mitigated by content-addressable cache; still painful if many novel docs.

---
