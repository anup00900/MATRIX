from __future__ import annotations
from pydantic import BaseModel
from ..llm import llm
from ..parser.schema import StructuredDoc
from .naive import NaiveRetriever
from .types import Evidence


class DecompPlan(BaseModel):
    sub_queries: list[str]
    target_section_ids: list[str] = []


class ChunkScore(BaseModel):
    chunk_id: str
    score: float


class RerankResult(BaseModel):
    scores: list[ChunkScore]


class ISDRetriever:
    """Iterative Source Decomposition retriever (Hebbia-flavored).

    Pass 1: LLM decomposes intent -> sub-queries + target_section_ids.
    Pass 2: embedding top-k per sub-query, deduped, with section-target boost.
    Pass 3: ONE batched LLM call ranks the candidate pool by attention score.
    Final: top-k by attention.
    """

    def __init__(self, force_local: bool = False, attention_pool: int = 30):
        self.naive = NaiveRetriever(force_local=force_local)
        self.attention_pool = attention_pool

    async def _decompose(self, query: str, doc: StructuredDoc) -> DecompPlan:
        if not doc.sections:
            return DecompPlan(sub_queries=[query], target_section_ids=[])
        sec_lines = "\n".join(f"[{s.id}] {s.title}" for s in doc.sections[:60])
        prompt = (
            "You are planning retrieval over a long document. Given a user intent "
            "and the document's section index, return:\n"
            "  - sub_queries: 2-5 specific retrieval queries that together cover the intent\n"
            "  - target_section_ids: up to 5 section ids most likely to contain the answer "
            "(omit if the intent spans the whole doc)\n\n"
            f"Section index:\n{sec_lines}\n\n"
            f"Intent: {query}"
        )
        return await llm.structured(
            messages=[{"role": "user", "content": prompt}],
            schema=DecompPlan,
            max_tokens=600,
        )

    async def _gather(
        self, sub_queries: list[str], target_section_ids: list[str],
        doc: StructuredDoc,
    ) -> list[Evidence]:
        per_q_k = max(8, self.attention_pool // max(1, len(sub_queries)))
        chunk_section = {c.id: c.section_id for c in doc.chunks}
        candidates: dict[str, Evidence] = {}
        for sq in sub_queries:
            hits = await self.naive.retrieve(sq, doc, k=per_q_k)
            for h in hits:
                if target_section_ids and chunk_section.get(h.chunk_id) in target_section_ids:
                    h.score = h.score * 0.5
                prev = candidates.get(h.chunk_id)
                if prev is None or prev.score > h.score:
                    candidates[h.chunk_id] = h
        ranked = sorted(candidates.values(), key=lambda e: e.score)
        return ranked[: self.attention_pool]

    async def _attention_rerank(
        self, query: str, candidates: list[Evidence],
    ) -> list[Evidence]:
        if not candidates:
            return []
        chunks_block = "\n\n".join(
            f"[{e.chunk_id}] (p.{e.page})\n{e.text[:1500]}" for e in candidates
        )
        prompt = (
            "Score each chunk's relevance to the query on a STRICT 0.0-1.0 scale.\n"
            "  1.0 - chunk directly answers the query\n"
            "  0.7 - strongly relevant, partial answer\n"
            "  0.4 - tangentially related context\n"
            "  0.0 - irrelevant\n"
            "Return JSON {scores: [{chunk_id, score}]}. Score every chunk.\n\n"
            f"Query: {query}\n\n"
            f"Chunks:\n{chunks_block}"
        )
        result = await llm.structured(
            messages=[{"role": "user", "content": prompt}],
            schema=RerankResult,
            max_tokens=2000,
        )
        score_by_id = {s.chunk_id: max(0.0, min(1.0, s.score)) for s in result.scores}
        out: list[Evidence] = []
        for e in candidates:
            attn = score_by_id.get(e.chunk_id, 0.0)
            e.score = 1.0 - attn
            e.source = "chunk.isd"
            out.append(e)
        return sorted(out, key=lambda e: e.score)

    async def retrieve(
        self, query: str, doc: StructuredDoc, k: int = 8,
    ) -> list[Evidence]:
        plan = await self._decompose(query, doc)
        sub_queries = plan.sub_queries or [query]
        candidates = await self._gather(sub_queries, plan.target_section_ids, doc)
        ranked = await self._attention_rerank(query, candidates)
        return ranked[:k]
