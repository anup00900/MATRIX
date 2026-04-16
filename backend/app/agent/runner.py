from __future__ import annotations
import gzip, json, time
from typing import Awaitable, Callable
from ulid import ULID
from ..llm import llm
from ..logging import log
from ..parser.schema import StructuredDoc
from ..retriever.types import Retriever, Evidence
from ..settings import settings
from .decompose import decompose
from .draft import draft as draft_step
from .verify import verify as verify_step
from .types import CellResult, Citation, Confidence

StateCallback = Callable[[str, dict | None], Awaitable[None]]


async def _noop(state: str, data: dict | None = None) -> None:
    return


async def run_cell(
    *, prompt: str, doc: StructuredDoc, retriever: Retriever,
    retriever_mode: str, shape_hint: str = "text",
    section_index: list[dict] | None = None,
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

    await on_state("drafting", None)
    dr = await draft_step(
        prompt=prompt,
        sub_questions=plan.sub_questions,
        evidence=evidence,
        shape_hint=plan.expected_answer_shape,
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
        )
        notes2 = await verify_step(draft=revised, retriever=retriever, doc=doc)
        revisions.append({
            "draft": revised.model_dump(),
            "verifier_notes": [n.model_dump() for n in notes2],
        })
        confidence: Confidence = (
            "high" if all(n.status == "supported" for n in notes2) else "low"
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
            snippet=c.text[:240],
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
