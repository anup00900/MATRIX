from __future__ import annotations
import lancedb
from ..settings import settings
from ..parser.schema import StructuredDoc
from .embeddings import EmbeddingService

def _table_name(doc_id: str) -> str: return f"doc_{doc_id[:16]}"

async def build_index(doc: StructuredDoc, force_local: bool = False) -> None:
    if not doc.chunks: return
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
