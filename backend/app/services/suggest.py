"""Decompose a natural language prompt into a ranked list of suggested columns
for the matrix grid. Inspired by the manager's variant.
"""
from __future__ import annotations
from pydantic import BaseModel
from ..llm import llm


class SuggestedColumn(BaseModel):
    prompt: str
    shape_hint: str  # text | number | currency | percentage | list | table


class SuggestedColumns(BaseModel):
    columns: list[SuggestedColumn]


SYSTEM = (
    "You are helping an analyst turn a high level question into concrete extraction "
    "columns for a matrix grid over financial filings. Produce 4 to 8 specific, "
    "well scoped column prompts. Each prompt should target a single extractable fact. "
    "Prefer specificity: include the reporting period and unit when useful. "
    "Pick a shape hint from text | number | currency | percentage | list | table."
)


async def suggest_columns(user_prompt: str) -> list[SuggestedColumn]:
    msg = (
        f"User question: {user_prompt}\n\n"
        "Return JSON matching the schema with 4 to 8 concrete column prompts. "
        "Example shape: {columns: [{prompt, shape_hint}, ...]}"
    )
    out = await llm.structured(
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": msg},
        ],
        schema=SuggestedColumns,
        max_tokens=800,
    )
    return out.columns
