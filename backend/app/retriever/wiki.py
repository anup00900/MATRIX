from __future__ import annotations
from ..parser.schema import StructuredDoc
from ..wiki.schema import DocWiki
from .naive import NaiveRetriever
from .types import Evidence


def _overlap_distance(q: str, text: str) -> float:
    """Cheap token-overlap distance — lower is better; range [0, 1]."""
    q_terms = {t.lower() for t in q.split() if len(t) > 3}
    t_terms = {t.lower() for t in text.split() if len(t) > 3}
    if not q_terms:
        return 1.0
    overlap = len(q_terms & t_terms) / len(q_terms)
    return 1.0 - overlap


class WikiRetriever:
    """Retrieves against a pre-built DocWiki.

    Strategy:
      1. Score every key metric by query-overlap to its (name/unit/period) triple.
      2. Score every claim by query-overlap to its text.
      3. Pull in chunk evidence referenced by those metric/claim hits.
      4. If fewer than k candidates, top up with NaiveRetriever fallback.
      5. Dedup by chunk_id, sort by distance, return top k.
    """

    def __init__(self, *, wiki: DocWiki, force_local: bool = False):
        self.wiki = wiki
        self.fallback = NaiveRetriever(force_local=force_local)

    async def retrieve(
        self, query: str, doc: StructuredDoc, k: int = 8,
    ) -> list[Evidence]:
        chunk_by_id = {c.id: c for c in doc.chunks}
        hits: list[Evidence] = []

        for m in self.wiki.key_metrics_table.values():
            c = chunk_by_id.get(m.chunk_id)
            if c is None:
                continue
            label = f"{m.name} {m.unit or ''} {m.period or ''}"
            hits.append(Evidence(
                chunk_id=c.id, text=c.text, page=c.page, bboxes=c.bboxes,
                score=_overlap_distance(query, label), source="wiki.metric",
            ))

        for entry in self.wiki.entries:
            for cl in entry.claims:
                for cid in cl.evidence_chunks:
                    c = chunk_by_id.get(cid)
                    if c is None:
                        continue
                    hits.append(Evidence(
                        chunk_id=c.id, text=c.text, page=c.page, bboxes=c.bboxes,
                        score=_overlap_distance(query, cl.text),
                        source="wiki.claim",
                    ))

        if len(hits) < k:
            for e in await self.fallback.retrieve(query, doc, k=k - len(hits)):
                hits.append(e)  # source stays as "chunk.vector"

        dedup: dict[str, Evidence] = {}
        for e in hits:
            prev = dedup.get(e.chunk_id)
            if prev is None:
                dedup[e.chunk_id] = e
                continue
            # Prefer wiki-sourced evidence over naive fallback; among same-tier
            # sources, keep the lower-score (better) hit.
            prev_is_wiki = prev.source.startswith("wiki.")
            cur_is_wiki = e.source.startswith("wiki.")
            if cur_is_wiki and not prev_is_wiki:
                dedup[e.chunk_id] = e
            elif prev_is_wiki and not cur_is_wiki:
                continue
            elif prev.score > e.score:
                dedup[e.chunk_id] = e
        return sorted(dedup.values(), key=lambda x: x.score)[:k]
