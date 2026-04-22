from __future__ import annotations
import re
from pydantic import BaseModel
from ..llm import llm
from ..retriever.types import Retriever
from ..parser.schema import StructuredDoc
from .types import DraftAnswer, VerifierNote


class _VerifierOut(BaseModel):
    notes: list[VerifierNote]


def _verifier_evidence(text: str, claim: str, max_len: int = 1200) -> str:
    """For table chunks, surface the header + rows matching the claim instead of the first N chars."""
    lines = text.splitlines()
    table_lines = [l for l in lines if l.strip().startswith("|")]
    sep_re = re.compile(r"^\s*\|[\s\-|]+\|\s*$")

    if len(table_lines) < 3:
        return text[:max_len]

    header_row = next((l for l in table_lines if not sep_re.match(l)), None)
    search_terms = {t.lower() for t in re.split(r"\W+", claim) if len(t) > 2}

    matching = [
        l for l in table_lines
        if not sep_re.match(l) and l != header_row
        and any(term in l.lower() for term in search_terms)
    ]

    if matching:
        parts = ([header_row] if header_row else []) + matching[:5]
        result = "\n".join(parts)
        return result[:max_len]

    return text[:max_len]


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
        evs = await retriever.retrieve(claim, doc, k=4)
        block = "\n".join(
            f"[{e.chunk_id}] (p.{e.page})\n{_verifier_evidence(e.text, claim)}"
            for e in evs
        )
        msg = (
            "Decide whether the evidence supports, contradicts, or does not contain the claim.\n\n"
            f"Claim: {claim}\n\nEvidence:\n{block}\n\n"
            "For numerical claims: if the exact number appears in the evidence for the right entity, "
            "it is 'supported'. Only mark 'missing' if the evidence genuinely has no relevant data.\n\n"
            "Return JSON: {\"notes\": [{\"claim\": \"...\", \"status\": \"supported|contradicted|missing\", \"note\": \"...\"}]}"
        )
        out = await llm.structured(
            messages=[{"role": "user", "content": msg}],
            schema=_VerifierOut,
            max_tokens=400,
        )
        notes.extend(out.notes)
    return notes
