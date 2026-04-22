from __future__ import annotations
import gzip, json, re, time
from typing import Awaitable, Callable
from ulid import ULID
from ..llm import llm
from ..logging import log
from ..parser.schema import StructuredDoc
from ..retriever.types import Retriever, Evidence
from ..settings import settings
from ..wiki.schema import DocWiki
from .decompose import decompose
from .draft import draft as draft_step
from .verify import verify as verify_step
from .types import CellResult, Citation, Confidence


def _relevant_snippet(chunk_text: str, prompt: str, answer: object, max_len: int = 500) -> str:
    """For table chunks, return the header + matching row(s) instead of the first N chars."""
    lines = chunk_text.splitlines()
    table_lines = [l for l in lines if l.strip().startswith("|")]

    # Not a table — plain text snippet
    if len(table_lines) < 3:
        return chunk_text[:max_len]

    # Identify header (first non-separator | line)
    sep_re = re.compile(r"^\s*\|[\s\-|]+\|\s*$")
    header_row: str | None = None
    for l in table_lines:
        if not sep_re.match(l):
            header_row = l
            break

    # Build search terms from prompt + answer
    answer_str = str(answer).lower()
    search_terms = {
        t.lower() for src in (prompt, answer_str)
        for t in re.split(r"\W+", src) if len(t) > 2
    }

    matching: list[str] = []
    for l in table_lines:
        if sep_re.match(l) or l == header_row:
            continue
        if any(term in l.lower() for term in search_terms):
            matching.append(l)

    if matching:
        parts = ([header_row] if header_row else []) + matching[:4]
        result = "\n".join(parts)
        return result[:max_len]

    return chunk_text[:max_len]


def _full_page_context(doc: StructuredDoc, evidence: list[Evidence]) -> str | None:
    """Include complete page markdown for pages referenced in evidence.
    Critical for table-heavy docs where a single chunk might miss rows.
    """
    page_nos = sorted({e.page for e in evidence})
    page_by_no = {p.page_no: p for p in doc.pages}
    blocks: list[str] = []
    for pno in page_nos[:6]:
        p = page_by_no.get(pno)
        if p and p.markdown.strip():
            blocks.append(f"=== COMPLETE PAGE {pno} CONTENT ===\n{p.markdown}")
    return "\n\n".join(blocks) if blocks else None


def _query_wiki_facts(query: str, wiki: DocWiki | None) -> str | None:
    """Return a text block of wiki metrics relevant to the query, for injection into draft."""
    if not wiki or not wiki.key_metrics_table:
        return None
    q_terms = {t.lower() for t in query.split() if len(t) > 2}
    hits: list[str] = []
    for key, m in wiki.key_metrics_table.items():
        label = f"{m.name} {key}".lower()
        if any(t in label for t in q_terms):
            unit = f" {m.unit}" if m.unit else ""
            period = f" ({m.period})" if m.period else ""
            hits.append(f"  [{m.chunk_id}] {m.name}: {m.value}{unit}{period}")
    return "\n".join(hits) if hits else None

StateCallback = Callable[[str, dict | None], Awaitable[None]]


async def _noop(state: str, data: dict | None = None) -> None:
    return


async def run_cell(
    *, prompt: str, doc: StructuredDoc, retriever: Retriever,
    retriever_mode: str, shape_hint: str = "text",
    section_index: list[dict] | None = None,
    wiki: DocWiki | None = None,
    on_state: StateCallback = _noop,
) -> CellResult:
    trace_id = str(ULID())
    t0 = time.time()
    tokens_at_start = llm.cost_tokens

    await on_state("retrieving", None)
    plan = await decompose(
        prompt=prompt,
        doc_meta=doc.meta.model_dump(),
        section_index=section_index or [],
        shape_hint=shape_hint,
    )

    evidence: list[Evidence] = []
    seen_ids: set[str] = set()
    for sq in plan.sub_questions:
        for e in await retriever.retrieve(sq, doc, k=6):
            if e.chunk_id not in seen_ids:
                seen_ids.add(e.chunk_id)
                evidence.append(e)

    # Build wiki facts block for high-confidence numerical grounding
    wiki_facts = _query_wiki_facts(prompt, wiki)
    # Include full page markdown for retrieved pages (prevents table row truncation)
    full_pages = _full_page_context(doc, evidence)

    await on_state("drafting", None)
    dr = await draft_step(
        prompt=prompt,
        sub_questions=plan.sub_questions,
        evidence=evidence,
        shape_hint=plan.expected_answer_shape,
        wiki_facts=wiki_facts,
        full_page_context=full_pages,
    )

    await on_state("verifying", None)
    notes = await verify_step(draft=dr, retriever=retriever, doc=doc)

    revisions: list[dict] = []
    if any(n.status in {"contradicted", "missing"} for n in notes):
        problems = "\n".join(
            f"- {n.claim} :: {n.status} :: {n.note}" for n in notes
        )
        fresh: list[Evidence] = []
        for n in notes:
            if n.status != "supported":
                for e in await retriever.retrieve(n.claim, doc, k=3):
                    if e.chunk_id not in seen_ids:
                        seen_ids.add(e.chunk_id)
                        fresh.append(e)
        revised = await draft_step(
            prompt=f"{prompt}\n\nVerifier notes:\n{problems}",
            sub_questions=plan.sub_questions,
            evidence=evidence + fresh,
            shape_hint=plan.expected_answer_shape,
            wiki_facts=wiki_facts,
            full_page_context=full_pages,
        )
        notes2 = await verify_step(draft=revised, retriever=retriever, doc=doc)
        revisions.append({
            "draft": revised.model_dump(),
            "verifier_notes": [n.model_dump() for n in notes2],
        })
        supported2 = sum(1 for n in notes2 if n.status == "supported")
        confidence = (
            "high" if supported2 == len(notes2)
            else "medium" if supported2 >= len(notes2) * 0.6
            else "low"
        )
        dr = revised
        notes = notes2
    else:
        confidence = "high"

    chunk_by_id = {c.id: c for c in doc.chunks}
    citations: list[Citation] = []
    seen_citations: set[str] = set()
    for cid in dr.citations:
        if cid in seen_citations:
            continue
        c = chunk_by_id.get(cid)
        if c is None:
            continue
        seen_citations.add(cid)
        citations.append(Citation(
            chunk_id=cid, page=c.page,
            snippet=_relevant_snippet(c.text, prompt, dr.answer),
            bboxes=[b.model_dump() for b in c.bboxes],
        ))

    trace = {
        "plan": plan.model_dump(),
        "evidence": [e.model_dump() for e in evidence],
        "draft": dr.model_dump(),
        "verifier_notes": [n.model_dump() for n in notes],
        "revisions": revisions,
    }
    settings.traces_dir.mkdir(parents=True, exist_ok=True)
    trace_path = settings.traces_dir / f"{trace_id}.json.gz"
    with gzip.open(trace_path, "wt") as f:
        f.write(json.dumps(trace))

    latency_ms = int((time.time() - t0) * 1000)
    tokens_used = llm.cost_tokens - tokens_at_start
    log.info("cell.done", trace_id=trace_id,
             retriever_mode=retriever_mode, confidence=confidence,
             latency_ms=latency_ms, tokens_used=tokens_used)

    return CellResult(
        answer=dr.answer,
        answer_shape=plan.expected_answer_shape,
        citations=citations,
        confidence=confidence,
        tokens_used=tokens_used,
        latency_ms=latency_ms,
        retriever_mode=retriever_mode,
        trace_id=trace_id,
        trace=trace,
    )
