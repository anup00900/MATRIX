from __future__ import annotations
import asyncio, json
from fastapi import APIRouter, Depends, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse
from sqlmodel import Session, select
from ..settings import settings
from ..storage.db import engine
from ..storage.models import Workspace, Document, Grid, Column, Row, Cell
from ..services.ingest import ingest_pdf
from ..services.cells import run_cell_job
from ..services.events import bus
from .schemas import (
    CreateWorkspaceIn, CreateGridIn, AddColumnIn, EditColumnIn, SetRetrieverIn,
)

r = APIRouter(prefix="/api")


def _session():
    with Session(engine) as s:
        yield s


@r.post("/workspaces")
def create_workspace(body: CreateWorkspaceIn, s: Session = Depends(_session)):
    w = Workspace(name=body.name); s.add(w); s.commit(); s.refresh(w)
    return w


@r.post("/workspaces/{ws_id}/documents")
async def upload_document(ws_id: str, file: UploadFile):
    data = await file.read()
    doc_id = await ingest_pdf(
        workspace_id=ws_id, filename=file.filename or "file.pdf",
        content=data, build_wiki_stage=True,
    )
    return {"document_id": doc_id}


@r.get("/workspaces/{ws_id}/documents")
def list_documents(ws_id: str, s: Session = Depends(_session)):
    return s.exec(select(Document).where(Document.workspace_id == ws_id)).all()


@r.post("/grids")
def create_grid(body: CreateGridIn, s: Session = Depends(_session)):
    g = Grid(
        workspace_id=body.workspace_id, name=body.name,
        retriever_mode=body.retriever_mode,
    )
    s.add(g); s.commit(); s.refresh(g)
    return g


@r.get("/grids/{grid_id}")
def get_grid(grid_id: str, s: Session = Depends(_session)):
    g = s.get(Grid, grid_id)
    if g is None:
        raise HTTPException(404)
    cols = s.exec(
        select(Column).where(Column.grid_id == grid_id).order_by(Column.position)
    ).all()
    rows = s.exec(
        select(Row).where(Row.grid_id == grid_id).order_by(Row.position)
    ).all()
    cells = s.exec(select(Cell).where(Cell.grid_id == grid_id)).all()
    return {"grid": g, "columns": cols, "rows": rows, "cells": cells}


@r.patch("/grids/{grid_id}")
def set_retriever(grid_id: str, body: SetRetrieverIn, s: Session = Depends(_session)):
    g = s.get(Grid, grid_id)
    if g is None:
        raise HTTPException(404)
    g.retriever_mode = body.retriever_mode
    s.add(g); s.commit(); s.refresh(g)
    return g


@r.post("/grids/{grid_id}/rows/{document_id}")
def add_row(grid_id: str, document_id: str, s: Session = Depends(_session)):
    existing = s.exec(select(Row).where(Row.grid_id == grid_id)).all()
    row = Row(grid_id=grid_id, document_id=document_id, position=len(existing))
    s.add(row); s.commit(); s.refresh(row)
    cols = s.exec(select(Column).where(Column.grid_id == grid_id)).all()
    new_cells: list[Cell] = []
    for c in cols:
        cell = Cell(
            grid_id=grid_id, row_id=row.id, column_id=c.id,
            column_version=c.version, status="queued",
        )
        s.add(cell); new_cells.append(cell)
    s.commit()
    for cell in new_cells:
        s.refresh(cell)
        asyncio.create_task(run_cell_job(cell_id=cell.id))
    s.refresh(row)
    return row


@r.post("/grids/{grid_id}/columns")
def add_column(grid_id: str, body: AddColumnIn, s: Session = Depends(_session)):
    existing = s.exec(select(Column).where(Column.grid_id == grid_id)).all()
    col = Column(
        grid_id=grid_id, position=len(existing), prompt=body.prompt,
        shape_hint=body.shape_hint, version=1,
    )
    s.add(col); s.commit(); s.refresh(col)
    rows = s.exec(select(Row).where(Row.grid_id == grid_id)).all()
    new_cells: list[Cell] = []
    for row in rows:
        cell = Cell(
            grid_id=grid_id, row_id=row.id, column_id=col.id,
            column_version=1, status="queued",
        )
        s.add(cell); new_cells.append(cell)
    s.commit()
    for cell in new_cells:
        s.refresh(cell)
        asyncio.create_task(run_cell_job(cell_id=cell.id))
    s.refresh(col)
    return col


@r.patch("/columns/{column_id}")
def edit_column(column_id: str, body: EditColumnIn, s: Session = Depends(_session)):
    col = s.get(Column, column_id)
    if col is None:
        raise HTTPException(404)
    if body.prompt is not None:
        col.prompt = body.prompt
    if body.shape_hint is not None:
        col.shape_hint = body.shape_hint
    col.version += 1
    s.add(col); s.commit()
    stale = s.exec(select(Cell).where(Cell.column_id == column_id)).all()
    for c in stale:
        c.status = "stale"; s.add(c)
    s.commit()
    s.refresh(col)
    return col


@r.post("/cells/{cell_id}/rerun")
def rerun_cell(cell_id: str, s: Session = Depends(_session)):
    c = s.get(Cell, cell_id)
    if c is None:
        raise HTTPException(404)
    col = s.get(Column, c.column_id); assert col
    c.status = "queued"; c.column_version = col.version
    s.add(c); s.commit()
    asyncio.create_task(run_cell_job(cell_id=cell_id))
    return {"ok": True}


@r.get("/pdf/{document_id}")
def get_pdf(document_id: str, s: Session = Depends(_session)):
    d = s.get(Document, document_id)
    if d is None:
        raise HTTPException(404)
    p = settings.pdfs_dir / f"{d.sha256}.pdf"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="application/pdf")


@r.get("/grids/{grid_id}/stream")
async def stream(grid_id: str, request: Request):
    q = bus.subscribe(f"grid:{grid_id}")

    async def gen():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue
                yield {"id": str(evt["id"]), "event": "cell", "data": json.dumps(evt)}
        finally:
            bus.unsubscribe(f"grid:{grid_id}", q)

    return EventSourceResponse(gen())
