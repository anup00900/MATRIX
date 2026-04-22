from __future__ import annotations
from pathlib import Path
from sqlmodel import Session
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
    if mode == "naive":
        return NaiveRetriever()
    if mode == "isd":
        return ISDRetriever()
    if mode == "wiki":
        w = load_wiki(doc.doc_id)
        if w is None:
            return ISDRetriever()
        return WikiRetriever(wiki=w)
    raise ValueError(f"unknown retriever mode: {mode}")


async def run_cell_job(*, cell_id: str) -> None:
    with Session(engine) as sess:
        cell = sess.get(Cell, cell_id); assert cell
        col = sess.get(Column, cell.column_id); assert col
        row = sess.get(Row, cell.row_id); assert row
        grid = sess.get(Grid, cell.grid_id); assert grid
        doc = sess.get(Document, row.document_id); assert doc
        # snapshot all fields we need after the session closes
        grid_id = grid.id
        retriever_mode = grid.retriever_mode
        document_id = row.document_id
        prompt = col.prompt
        shape_hint = col.shape_hint
        col_version = col.version
        cell.status = "retrieving"
        cell.column_version = col_version
        cell.retriever_mode = retriever_mode
        sess.add(cell); sess.commit()

    channel = f"grid:{grid_id}"
    await bus.publish(channel, {
        "type": "cell", "cell_id": cell_id, "state": "retrieving",
    })
    try:
        parsed = _load_doc(document_id)
        retriever = _make_retriever(retriever_mode, parsed)
        wiki = load_wiki(parsed.doc_id)
        section_index = (
            [item.model_dump() for item in wiki.section_index] if wiki
            else [{"id": s.id, "title": s.title} for s in parsed.sections]
        )

        async def on_state(state: str, data: dict | None = None) -> None:
            with Session(engine) as s2:
                c2 = s2.get(Cell, cell_id); assert c2
                c2.status = state
                s2.add(c2); s2.commit()
            await bus.publish(channel, {
                "type": "cell", "cell_id": cell_id, "state": state,
            })

        result = await run_cell(
            prompt=prompt, doc=parsed, retriever=retriever,
            retriever_mode=retriever_mode, shape_hint=shape_hint,
            section_index=section_index, wiki=wiki, on_state=on_state,
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
            published_answer = dict(c2.answer_json) if c2.answer_json else None
            published_citations = list(c2.citations_json) if c2.citations_json else []

        await bus.publish(channel, {
            "type": "cell", "cell_id": cell_id, "state": "done",
            "answer": published_answer, "citations": published_citations,
            "confidence": result.confidence,
        })
    except Exception as e:
        log.exception("cell.failed", cell_id=cell_id)
        with Session(engine) as s2:
            c2 = s2.get(Cell, cell_id)
            if c2:
                c2.status = "failed"
                c2.error = str(e)[:500]
                s2.add(c2); s2.commit()
        await bus.publish(channel, {
            "type": "cell", "cell_id": cell_id, "state": "failed",
            "error": str(e)[:500],
        })
