"""Long-format structured export of a grid into CSV/JSON for downstream
consumption (e.g. NAV returns pipelines, dashboards).
"""
from __future__ import annotations
import csv, io, json
from sqlmodel import Session, select
from ..storage.db import engine
from ..storage.models import Cell, Column, Row, Document, Grid


EXPORT_COLUMNS = [
    "issuer",
    "filing_type",
    "period_end",
    "document_id",
    "filename",
    "column_id",
    "metric",
    "shape",
    "value",
    "confidence",
    "source_pages",
    "retriever_mode",
    "latency_ms",
    "tokens_used",
    "cell_id",
]


def _rows_for_grid(grid_id: str) -> list[dict]:
    with Session(engine) as s:
        grid = s.get(Grid, grid_id)
        if grid is None:
            raise ValueError(f"grid {grid_id} not found")
        cols = s.exec(
            select(Column).where(Column.grid_id == grid_id).order_by(Column.position)
        ).all()
        rows = s.exec(
            select(Row).where(Row.grid_id == grid_id).order_by(Row.position)
        ).all()
        cells = s.exec(select(Cell).where(Cell.grid_id == grid_id)).all()
        docs = {d.id: d for d in s.exec(select(Document)).all()}

    cell_by_rc = {(c.row_id, c.column_id): c for c in cells}
    col_by_id = {c.id: c for c in cols}
    out: list[dict] = []
    for row in rows:
        doc = docs.get(row.document_id)
        meta = doc.meta_json if doc and doc.meta_json else {}
        for col in cols:
            c = cell_by_rc.get((row.id, col.id))
            value_raw = (c.answer_json or {}).get("value") if c and c.answer_json else None
            shape = (c.answer_json or {}).get("shape") if c and c.answer_json else col.shape_hint
            if isinstance(value_raw, (dict, list)):
                value = json.dumps(value_raw, ensure_ascii=False)
            elif value_raw is None:
                value = ""
            else:
                value = str(value_raw)
            citations = c.citations_json or [] if c else []
            pages = sorted({ci["page"] for ci in citations if isinstance(ci, dict) and "page" in ci})
            out.append({
                "issuer": meta.get("company") or "",
                "filing_type": meta.get("filing_type") or "",
                "period_end": meta.get("period_end") or "",
                "document_id": row.document_id,
                "filename": doc.filename if doc else "",
                "column_id": col.id,
                "metric": col_by_id[col.id].prompt,
                "shape": shape or "",
                "value": value,
                "confidence": (c.confidence if c else "") or "",
                "source_pages": ";".join(str(p) for p in pages),
                "retriever_mode": (c.retriever_mode if c else "") or "",
                "latency_ms": c.latency_ms if c else 0,
                "tokens_used": c.tokens_used if c else 0,
                "cell_id": c.id if c else "",
            })
    return out


def export_csv(grid_id: str) -> str:
    rows = _rows_for_grid(grid_id)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return buf.getvalue()


def export_json(grid_id: str) -> list[dict]:
    return _rows_for_grid(grid_id)
