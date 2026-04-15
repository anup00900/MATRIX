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
