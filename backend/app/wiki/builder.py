from __future__ import annotations
import asyncio, gzip
from pathlib import Path
from ..llm import llm
from ..logging import log
from ..parser.schema import StructuredDoc, Section, Chunk
from ..settings import settings
from .schema import (
    DocWiki, DocWikiRollup, SectionWikiEntry, SectionIndexItem,
    WIKI_SCHEMA_VERSION,
)

SECTION_CONCURRENCY = 4


def wiki_path_for(doc_id: str, version: int = WIKI_SCHEMA_VERSION) -> Path:
    return settings.wikis_dir / f"{doc_id}__v{version}.json.gz"


async def _build_section(section: Section, chunks: list[Chunk]) -> SectionWikiEntry:
    chunk_lines = "\n".join(
        f"[{c.id}] (p.{c.page}) {c.text[:600]}" for c in chunks[:12]
    )
    prompt = (
        f"You are analysing a section of a financial filing.\n\n"
        f"Section title: {section.title}\n\n"
        f"Chunks (cite any evidence by chunk id):\n{chunk_lines}\n\n"
        "Extract: a concise 3-5 sentence summary, named entities, notable claims "
        "(each with evidence_chunks), quantitative metrics (with chunk_id), and a list "
        "of questions this section can answer. Do not invent; only use what's present."
    )
    entry = await llm.structured(
        messages=[{"role": "user", "content": prompt}],
        schema=SectionWikiEntry,
        max_tokens=1500,
    )
    # the model may omit section_id; enforce it
    entry.section_id = section.id
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

    rollup_prompt = (
        "Given these section summaries, write a 3-5 sentence overview of the document, "
        "then return JSON with:\n"
        "  - overview (str)\n"
        "  - key_metrics_table: object mapping metric name to "
        "{name, value, unit, period, chunk_id} — include only the 3-6 most important "
        "metrics in the document.\n\n"
        + "\n".join(f"- {s.title}: {s.summary}" for s in section_index)
    )
    rollup = await llm.structured(
        messages=[{"role": "user", "content": rollup_prompt}],
        schema=DocWikiRollup,
        max_tokens=1500,
    )

    wiki = DocWiki(
        doc_id=doc.doc_id,
        overview=rollup.overview,
        section_index=section_index,
        entries=entries,
        key_metrics_table=rollup.key_metrics_table,
    )
    path = wiki_path_for(doc.doc_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as f:
        f.write(wiki.model_dump_json())
    log.info("wiki.built", doc_id=doc.doc_id, sections=len(entries))
    return wiki


def load_wiki(doc_id: str, version: int = WIKI_SCHEMA_VERSION) -> DocWiki | None:
    p = wiki_path_for(doc_id, version)
    if not p.exists():
        return None
    with gzip.open(p, "rt") as f:
        return DocWiki.model_validate_json(f.read())
