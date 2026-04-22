from ..llm import llm
from ..retriever.types import Evidence
from .types import DraftAnswer


def _evidence_block(evidence: list[Evidence]) -> str:
    return "\n\n".join(
        f"[{e.chunk_id}] (p.{e.page}, src={e.source})\n{e.text[:2000]}"
        for e in evidence[:30]
    )


async def draft(
    *, prompt: str, sub_questions: list[str], evidence: list[Evidence],
    shape_hint: str, wiki_facts: str | None = None,
    full_page_context: str | None = None,
) -> DraftAnswer:
    wiki_section = (
        f"\n\nWIKI METRICS — pre-extracted facts (high confidence, prefer these for numerical answers):\n{wiki_facts}"
        if wiki_facts else ""
    )
    full_page_section = (
        f"\n\nFULL PAGE CONTENT — complete page text (use this to avoid missing table rows):\n{full_page_context}"
        if full_page_context else ""
    )
    msg = (
        "Answer the user prompt using the evidence and page content below. "
        "When answering from a table, read EVERY row — do not stop at the first match. "
        "Every factual claim must cite at least one chunk id. "
        f"Return JSON with fields `answer` (shape: {shape_hint}), "
        "`citations` (list of chunk ids), and `reasoning_trace` (array of short strings).\n\n"
        f"Prompt: {prompt}\n\n"
        "Sub-questions:\n- " + "\n- ".join(sub_questions) + "\n\n"
        f"Evidence chunks:\n{_evidence_block(evidence)}"
        + wiki_section
        + full_page_section
    )
    return await llm.structured(
        messages=[{"role": "user", "content": msg}],
        schema=DraftAnswer,
        max_tokens=3000,
    )
