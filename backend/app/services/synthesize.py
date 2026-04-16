from __future__ import annotations
from sqlmodel import Session, select
from ..llm import llm
from ..logging import log
from ..storage.db import engine
from ..storage.models import Cell, Column, Row, Grid, Synthesis


async def synthesize(grid_id: str, prompt: str) -> Synthesis:
    with Session(engine) as s:
        g = s.get(Grid, grid_id)
        if g is None:
            raise ValueError(f"grid {grid_id} not found")
        cols = s.exec(
            select(Column).where(Column.grid_id == grid_id).order_by(Column.position)
        ).all()
        rows = s.exec(
            select(Row).where(Row.grid_id == grid_id).order_by(Row.position)
        ).all()
        cells = s.exec(select(Cell).where(Cell.grid_id == grid_id)).all()

    cell_by_rc = {(c.row_id, c.column_id): c for c in cells}

    if not cols or not rows:
        raise ValueError("grid has no columns or rows")

    header = "| Row | " + " | ".join(c.prompt for c in cols) + " |"
    divider = "|---" * (len(cols) + 1) + "|"
    lines = [header, divider]
    for row in rows:
        values: list[str] = []
        for col in cols:
            c = cell_by_rc.get((row.id, col.id))
            if c and c.answer_json:
                v = c.answer_json.get("value") if isinstance(c.answer_json, dict) else c.answer_json
                values.append(str(v))
            else:
                values.append("—")
        lines.append(f"| {row.document_id[:8]} | " + " | ".join(values) + " |")
    grid_md = "\n".join(lines)

    msg = (
        "Given the matrix of extracted answers below, answer the user's synthesis prompt.\n"
        "Cite row and column references inline as [row_id×col_id] when useful.\n"
        "Keep the answer concise and grounded in the visible matrix only.\n\n"
        f"Synthesis prompt: {prompt}\n\n"
        f"Matrix:\n{grid_md}"
    )
    answer = await llm.chat(
        messages=[{"role": "user", "content": msg}],
        max_tokens=1200,
    )
    with Session(engine) as s:
        syn = Synthesis(grid_id=grid_id, prompt=prompt, answer=answer, citations_json=[])
        s.add(syn); s.commit(); s.refresh(syn)
        log.info("synthesis.done", grid_id=grid_id, chars=len(answer))
        return syn
