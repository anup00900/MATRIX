from pydantic import BaseModel

WIKI_SCHEMA_VERSION = 1


class Entity(BaseModel):
    name: str
    type: str            # company | product | person | metric | location | other
    mentions: list[str]  # chunk_ids


class Claim(BaseModel):
    text: str
    evidence_chunks: list[str]
    confidence: float = 0.7


class Metric(BaseModel):
    name: str
    value: float | str
    unit: str | None = None
    period: str | None = None
    chunk_id: str


class SectionWikiEntry(BaseModel):
    section_id: str
    summary: str
    entities: list[Entity] = []
    claims: list[Claim] = []
    metrics: list[Metric] = []
    questions_answered: list[str] = []


class SectionIndexItem(BaseModel):
    id: str
    title: str
    questions_answered: list[str] = []
    summary: str = ""


class DocWikiRollup(BaseModel):
    """What the rollup LLM call returns — just overview + key metrics."""
    overview: str
    key_metrics_table: dict[str, Metric] = {}


class DocWikiOverview(BaseModel):
    """Minimal rollup — just the overview paragraph."""
    overview: str


class SectionWikiLean(BaseModel):
    """Lean section-summary schema — used for the per-section rollup call."""
    summary: str
    questions_answered: list[str] = []


class MetricLLM(BaseModel):
    """LLM-facing metric (chunk_id is filled in code, not by the model)."""
    name: str
    value: float | str
    unit: str | None = None
    period: str | None = None


class ClaimLLM(BaseModel):
    """LLM-facing claim (evidence_chunks filled in code)."""
    text: str
    confidence: float = 0.7


class EntityLLM(BaseModel):
    """LLM-facing entity (mentions filled in code)."""
    name: str
    type: str = "other"


class ChunkExtraction(BaseModel):
    """LLM output for a single chunk — every quantitative value, every factual
    claim, every named entity. No truncation, no early stopping.
    """
    metrics: list[MetricLLM] = []
    claims: list[ClaimLLM] = []
    entities: list[EntityLLM] = []


class DocWiki(BaseModel):
    doc_id: str
    wiki_schema_version: int = WIKI_SCHEMA_VERSION
    overview: str
    section_index: list[SectionIndexItem]
    entries: list[SectionWikiEntry]
    key_metrics_table: dict[str, Metric] = {}
