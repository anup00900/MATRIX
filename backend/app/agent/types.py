from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel

AnswerShape = Literal["text", "number", "currency", "percentage", "list", "table"]
Confidence = Literal["high", "medium", "low"]
VerifierStatus = Literal["supported", "contradicted", "missing"]


class Citation(BaseModel):
    chunk_id: str
    page: int
    snippet: str
    bboxes: list           # list of {page, bbox} dicts


class DecompositionPlan(BaseModel):
    sub_questions: list[str]
    expected_answer_shape: AnswerShape
    target_sections: list[str] = []


class DraftAnswer(BaseModel):
    answer: Any
    citations: list[str]                 # chunk_ids
    reasoning_trace: list[str] = []


class VerifierNote(BaseModel):
    claim: str
    status: VerifierStatus
    note: str = ""


class CellResult(BaseModel):
    answer: Any
    answer_shape: AnswerShape
    citations: list[Citation]
    confidence: Confidence
    tokens_used: int = 0
    latency_ms: int = 0
    retriever_mode: str
    trace_id: str
    trace: dict
