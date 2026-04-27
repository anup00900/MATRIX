from __future__ import annotations
import asyncio, gzip
from pathlib import Path
from ..llm import llm
from ..logging import log
from ..parser.schema import StructuredDoc, Section, Chunk
from ..settings import settings
from .schema import (
    DocWiki, DocWikiOverview, SectionWikiEntry, SectionWikiLean, SectionIndexItem,
    Metric, Claim, Entity, ChunkExtraction,
    WIKI_SCHEMA_VERSION,
)

CHUNK_CONCURRENCY = 8
SECTION_CONCURRENCY = 4

CHUNK_EXTRACT_PROMPT = (
    "Extract every quantitative value, factual claim, and named entity from this "
    "document chunk. Be exhaustive — DO NOT stop early, DO NOT truncate, DO NOT "
    "summarise rows. Every numeric row in every table must be extracted as its "
    "own metric.\n\n"

    "━━ MUST-EXTRACT ITEMS (when present in this chunk) ━━\n"
    "Income-statement bottom-line items: Revenue, Net revenue, Total revenue, "
    "Cost of revenue, Cost of sales, Gross profit, Gross margin, Operating "
    "expenses, Operating income, Operating margin, Net income, Net earnings, "
    "Earnings per share / EPS (basic and diluted), Diluted weighted-average "
    "shares, EBITDA, Income before income taxes, Provision for income taxes.\n"
    "Balance-sheet items: Total assets, Total liabilities, Stockholders' equity, "
    "Cash and cash equivalents, Marketable securities, Accounts receivable, "
    "Inventory, Goodwill, Long-term debt.\n"
    "Cash-flow items: Cash from operations, Cash used in investing, Cash used "
    "in financing, Capital expenditures, Free cash flow.\n"
    "Per-share / per-period changes: YoY %, QoQ %, CAGR, period-over-period "
    "deltas.\n"
    "ANY other numeric value the chunk discloses (volumes, rates, percentages, "
    "headcount, prices, fees, ratios). When in doubt, include it.\n\n"

    "━━ RULES ━━\n"
    "  1. Each numeric row in a markdown table is a separate metric. Do not "
    "merge rows.\n"
    "  2. Preserve units exactly as printed ('$M', 'million $', '%', 'EPS', "
    "'shares').\n"
    "  3. Preserve period labels exactly as printed (e.g., 'Year Ended Jan 26, "
    "2025', 'Q3 FY2026').\n"
    "  4. If a value appears in both a chart-narrative line AND a data table, "
    "extract it from the table version (the data table is canonical).\n"
    "  5. For claims: each claim is a single self-contained factual statement "
    "grounded in this chunk's text (no inference beyond what is written).\n"
    "  6. For entities: extract company / product / person / location names. "
    "Set type to one of: company, product, person, location, metric, other.\n"
    "  7. Do NOT invent values. If a value is not in the chunk, do not include "
    "it.\n\n"

    "Return JSON matching the schema."
)

SECTION_SUMMARY_PROMPT = (
    "Write a 2-4 sentence summary of this document section, plus a list of "
    "specific questions a reader could answer using this section.\n\n"
    "Section: {title}\n"
    "Pages: {page_start}–{page_end}\n"
    "Total chunks: {n_chunks}\n"
    "Metrics already extracted ({n_metrics}):\n{metric_lines}\n\n"
    "First-chunk preview (for tone/topic):\n{preview}\n\n"
    "Return JSON with 'summary' (string) and 'questions_answered' (list of "
    "strings, 4–8 items)."
)


def wiki_path_for(doc_id: str, version: int = WIKI_SCHEMA_VERSION) -> Path:
    return settings.wikis_dir / f"{doc_id}__v{version}.json.gz"


async def _extract_chunk(chunk: Chunk) -> ChunkExtraction:
    """Run a focused extraction on a single chunk. No truncation."""
    prompt = (
        f"{CHUNK_EXTRACT_PROMPT}\n\n"
        f"━━ CHUNK CONTENT (page {chunk.page}) ━━\n"
        f"{chunk.text}\n"
    )
    try:
        return await llm.structured(
            messages=[{"role": "user", "content": prompt}],
            schema=ChunkExtraction,
            max_tokens=6000,
        )
    except Exception as e:
        log.warning("wiki.chunk.extract_failed", chunk_id=chunk.id, page=chunk.page, error=str(e)[:200])
        return ChunkExtraction()


async def _build_section(section: Section, chunks: list[Chunk]) -> SectionWikiEntry:
    if not chunks:
        return SectionWikiEntry(section_id=section.id, summary="(empty section)")

    # Per-chunk extraction in parallel — every chunk gets full attention.
    sem = asyncio.Semaphore(CHUNK_CONCURRENCY)

    async def guarded(c: Chunk) -> tuple[Chunk, ChunkExtraction]:
        async with sem:
            return c, await _extract_chunk(c)

    pairs = await asyncio.gather(*(guarded(c) for c in chunks))

    # Aggregate per-chunk results into section-level lists, attributing each
    # item to its source chunk.
    metrics: list[Metric] = []
    claims: list[Claim] = []
    entities_by_name: dict[str, Entity] = {}
    for chunk, ext in pairs:
        for m in ext.metrics:
            metrics.append(Metric(
                name=m.name, value=m.value, unit=m.unit, period=m.period,
                chunk_id=chunk.id,
            ))
        for cl in ext.claims:
            claims.append(Claim(
                text=cl.text, confidence=cl.confidence,
                evidence_chunks=[chunk.id],
            ))
        for e in ext.entities:
            key = f"{e.name.strip().lower()}|{e.type.strip().lower()}"
            existing = entities_by_name.get(key)
            if existing is None:
                entities_by_name[key] = Entity(
                    name=e.name, type=e.type, mentions=[chunk.id],
                )
            elif chunk.id not in existing.mentions:
                existing.mentions.append(chunk.id)

    # Section-level rollup: summary + questions, informed by what we extracted.
    metric_lines = "\n".join(
        f"  - {m.name}: {m.value}{(' ' + m.unit) if m.unit else ''}"
        f"{(' (' + m.period + ')') if m.period else ''}"
        for m in metrics[:60]
    ) or "  (none)"
    preview = (chunks[0].text[:1500] + ("…" if len(chunks[0].text) > 1500 else "")) if chunks else ""

    summary_prompt = SECTION_SUMMARY_PROMPT.format(
        title=section.title,
        page_start=section.page_start,
        page_end=section.page_end,
        n_chunks=len(chunks),
        n_metrics=len(metrics),
        metric_lines=metric_lines,
        preview=preview,
    )
    try:
        lean = await llm.structured(
            messages=[{"role": "user", "content": summary_prompt}],
            schema=SectionWikiLean,
            max_tokens=1500,
        )
        summary = lean.summary
        questions = lean.questions_answered
    except Exception as e:
        log.warning("wiki.section.summary_failed", section_id=section.id, error=str(e)[:200])
        summary = f"{section.title} (pages {section.page_start}–{section.page_end})"
        questions = []

    return SectionWikiEntry(
        section_id=section.id,
        summary=summary,
        entities=list(entities_by_name.values()),
        claims=claims,
        metrics=metrics,
        questions_answered=questions,
    )


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

    # Flatten every metric from every section into the document-level table.
    # Use a stable key that includes section title, metric name, and period
    # so two sections can have a "Net income" metric without collision.
    all_metrics: dict[str, Metric] = {}
    for s, e in zip(doc.sections, entries):
        for i, m in enumerate(e.metrics):
            base = f"{s.title}__{m.name}"
            if m.period:
                base = f"{base}__{m.period}"
            key = base.replace(" ", "_").lower()[:120]
            # Deduplicate by appending an index if the key already exists.
            if key in all_metrics:
                key = f"{key}__{i}"
            all_metrics[key] = m

    rollup_prompt = (
        "Write a 4-6 sentence overview of this document based on the section "
        "summaries below. Capture the document type, the entity it describes, "
        "the periods covered, and the most material findings. "
        "Return JSON with a single field: overview (string).\n\n"
        + "\n".join(f"- {s.title}: {e.summary}" for s, e in zip(doc.sections, entries))
    )
    try:
        rollup = await llm.structured(
            messages=[{"role": "user", "content": rollup_prompt}],
            schema=DocWikiOverview,
            max_tokens=800,
        )
        overview = rollup.overview
    except Exception as e:
        log.warning("wiki.overview_failed", error=str(e)[:200])
        overview = f"Document {doc.doc_id} with {len(doc.sections)} sections."

    wiki = DocWiki(
        doc_id=doc.doc_id,
        overview=overview,
        section_index=section_index,
        entries=entries,
        key_metrics_table=all_metrics,
    )
    path = wiki_path_for(doc.doc_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as f:
        f.write(wiki.model_dump_json())
    log.info(
        "wiki.built", doc_id=doc.doc_id,
        sections=len(entries),
        metrics=len(wiki.key_metrics_table),
        claims=sum(len(e.claims) for e in entries),
        entities=sum(len(e.entities) for e in entries),
    )
    return wiki


def load_wiki(doc_id: str, version: int = WIKI_SCHEMA_VERSION) -> DocWiki | None:
    p = wiki_path_for(doc_id, version)
    if not p.exists():
        return None
    with gzip.open(p, "rt") as f:
        return DocWiki.model_validate_json(f.read())
