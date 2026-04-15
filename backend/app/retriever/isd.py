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
