from ..parser.schema import StructuredDoc
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
