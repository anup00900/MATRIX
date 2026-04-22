from __future__ import annotations
import asyncio, gzip
from pathlib import Path
from ..llm import llm
from ..logging import log
from ..parser.schema import StructuredDoc, Section, Chunk
from ..settings import settings
from .schema import (
    DocWiki, DocWikiOverview, SectionWikiEntry, SectionWikiLean, SectionIndexItem, Metric,
    WIKI_SCHEMA_VERSION,
)

SECTION_CONCURRENCY = 4


def wiki_path_for(doc_id: str, version: int = WIKI_SCHEMA_VERSION) -> Path:
    return settings.wikis_dir / f"{doc_id}__v{version}.json.gz"


async def _build_section(section: Section, chunks: list[Chunk]) -> SectionWikiEntry:
    chunk_lines = "\n".join(
        f"[{c.id}] (p.{c.page})\n{c.text[:2000]}" for c in chunks[:12]
    )
    prompt = (
        f"Analyse this document section. It may be a fee schedule, table, financial "
        f"statement, or narrative text.\n\n"
        f"Section: {section.title}\n\n"
        f"Content:\n{chunk_lines}\n\n"
        "Return JSON with:\n"
        "- summary: 2-3 sentences describing what this section contains\n"
        "- metrics: list of ALL quantitative values found. Each metric needs: "
        "name (descriptive label), value (exact number/string), unit (optional), "
        "period (optional), chunk_id. Extract EVERY row — do not stop early.\n"
        "- questions_answered: list of questions this section can answer\n\n"
        "Only extract what is present. Do not invent."
    )
    lean = await llm.structured(
        messages=[{"role": "user", "content": prompt}],
        schema=SectionWikiLean,
        max_tokens=6000,
    )
    entry = SectionWikiEntry(
        section_id=section.id,
        summary=lean.summary,
        metrics=lean.metrics,
        questions_answered=lean.questions_answered,
    )
    return entry


async def build_wiki(doc: StructuredDoc) -> DocWiki:
    chunks_by_section: dict[str, list[Chunk]] = {}
    for c in doc.chunks:
        key = c.section_id or "_"
        chunks_by_section.setdefault(key, []).append(c)

    sem = asyncio.Semaphore(SECTION_CONCURRENCY)

    async def guarded(s: Section) -> SectionWikiEntry:
        async with sem:
            return await _build_section(s, chunks_by_section.get(s.id, []))

    entries: list[SectionWikiEntry] = list(
        await asyncio.gather(*(guarded(s) for s in doc.sections))
    )
    section_index = [
        SectionIndexItem(
            id=s.id, title=s.title,
            questions_answered=e.questions_answered, summary=e.summary,
        )
        for s, e in zip(doc.sections, entries)
    ]

    # Collect all metrics directly from section entries (ground truth from extraction)
    all_metrics: dict[str, "Metric"] = {}
    for s, e in zip(doc.sections, entries):
        for m in e.metrics:
            # Namespaced key: section_title + metric_name, normalised
            key = f"{s.title}__{m.name}".replace(" ", "_").lower()[:80]
            all_metrics[key] = m

    rollup_prompt = (
        "Write a 3-5 sentence overview of this document based on the section summaries below. "
        "Return JSON with a single field: overview (string).\n\n"
        + "\n".join(f"- {s.title}: {e.summary}" for s, e in zip(doc.sections, entries))
    )
    rollup = await llm.structured(
        messages=[{"role": "user", "content": rollup_prompt}],
        schema=DocWikiOverview,
        max_tokens=600,
    )

    wiki = DocWiki(
        doc_id=doc.doc_id,
        overview=rollup.overview,
        section_index=section_index,
        entries=entries,
        key_metrics_table=all_metrics,  # populated from section extractions, not summaries
    )
    path = wiki_path_for(doc.doc_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as f:
        f.write(wiki.model_dump_json())
    log.info("wiki.built", doc_id=doc.doc_id, sections=len(entries),
             metrics=len(wiki.key_metrics_table))
    return wiki


def load_wiki(doc_id: str, version: int = WIKI_SCHEMA_VERSION) -> DocWiki | None:
    p = wiki_path_for(doc_id, version)
    if not p.exists():
        return None
    with gzip.open(p, "rt") as f:
        return DocWiki.model_validate_json(f.read())
