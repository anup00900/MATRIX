from pydantic import BaseModel
from ..llm import llm
from ..retriever.types import Retriever
from ..parser.schema import StructuredDoc
from .types import DraftAnswer, VerifierNote


class _VerifierOut(BaseModel):
    notes: list[VerifierNote]


async def verify(
    *, draft: DraftAnswer, retriever: Retriever, doc: StructuredDoc,
) -> list[VerifierNote]:
    claims: list[str] = [
        line.strip() for line in (draft.reasoning_trace or [str(draft.answer)])
        if line and line.strip()
    ]
    if not claims:
        claims = [str(draft.answer)]

    notes: list[VerifierNote] = []
    for claim in claims[:6]:
        evs = await retriever.retrieve(claim, doc, k=3)
        block = "\n".join(
            f"[{e.chunk_id}] (p.{e.page}) {e.text[:400]}" for e in evs
        )
        msg = (
            "Decide whether the following evidence supports, contradicts, or does not "
            f"contain the claim.\n\nClaim: {claim}\n\nEvidence:\n{block}\n\n"
            "Return JSON with `notes` (list of one element) with fields "
            "`claim`, `status` (supported|contradicted|missing), `note`."
        )
        out = await llm.structured(
            messages=[{"role": "user", "content": msg}],
            schema=_VerifierOut,
            max_tokens=400,
        )
        notes.extend(out.notes)
    return notes
