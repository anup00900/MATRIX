from ..llm import llm
from ..retriever.types import Evidence
from .types import DraftAnswer


def _evidence_block(evidence: list[Evidence]) -> str:
    return "\n".join(
        f"[{e.chunk_id}] (p.{e.page}, src={e.source}) {e.text[:500]}"
        for e in evidence[:20]
    )


async def draft(
    *, prompt: str, sub_questions: list[str], evidence: list[Evidence],
    shape_hint: str,
) -> DraftAnswer:
    msg = (
        "Answer the user prompt using ONLY the evidence below. "
        "Every factual claim must cite at least one chunk id. "
        f"Return JSON with fields `answer` (shape: {shape_hint}), "
        "`citations` (list of chunk ids), and `reasoning_trace` (array of short strings).\n\n"
        f"Prompt: {prompt}\n\n"
        "Sub-questions:\n- " + "\n- ".join(sub_questions) + "\n\n"
        f"Evidence:\n{_evidence_block(evidence)}"
    )
    return await llm.structured(
        messages=[{"role": "user", "content": msg}],
        schema=DraftAnswer,
        max_tokens=1500,
    )
