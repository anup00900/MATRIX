import pytest
from pathlib import Path
from app.parser.pdf import parse_pdf
from app.parser import pdf as pdf_mod
from app.wiki.builder import build_wiki, load_wiki
from app.wiki.schema import (
    DocWiki, SectionWikiLean, DocWikiOverview, ChunkExtraction,
    MetricLLM, ClaimLLM, EntityLLM,
)
from app.wiki import builder as b

PAGES_MD = [
    "## Item 1. Business\n\nApple Inc. designs and sells consumer electronics.",
    "## Item 1A. Risk Factors\n\nSupply chain concentration in East Asia is a material risk.",
    "## Item 7. MD&A\n\nRevenue for fiscal 2023 was $383.3 billion, up 2.8% YoY.",
]


@pytest.mark.asyncio
async def test_build_and_load_wiki(monkeypatch, tmp_path):
    # isolate wiki storage
    from app import settings as s_mod
    monkeypatch.setattr(s_mod.settings, "storage_root", tmp_path)
    s_mod.settings.wikis_dir.mkdir(parents=True, exist_ok=True)

    # vision parser mock
    call = {"i": 0}
    async def fake_vision(*, system, user_text, image_b64_png, **kw):
        i = call["i"]; call["i"] += 1
        return PAGES_MD[i % len(PAGES_MD)]
    monkeypatch.setattr(pdf_mod.llm, "vision_chat", fake_vision)

    doc = await parse_pdf(Path("tests/fixtures/tiny.pdf"))

    # The new builder makes three kinds of structured calls:
    #   - ChunkExtraction (per chunk)
    #   - SectionWikiLean (per section, for summary + questions)
    #   - DocWikiOverview (once, for the document-wide rollup)
    seen_schemas = []

    async def fake_structured(*, messages, schema, **kw):
        seen_schemas.append(schema)
        if schema is ChunkExtraction:
            user = messages[0]["content"] if messages else ""
            # Identify the revenue chunk by content unique to the MD&A page —
            # the prompt preamble itself mentions "Revenue", so we anchor on
            # the dollar figure that only the MD&A chunk contains.
            if "$383.3" in user or "fiscal 2023" in user:
                return ChunkExtraction(
                    metrics=[MetricLLM(
                        name="revenue", value=383.3, unit="USD_billions",
                        period="FY2023",
                    )],
                    claims=[ClaimLLM(text="Revenue grew 2.8% YoY", confidence=0.9)],
                    entities=[EntityLLM(name="Apple Inc.", type="company")],
                )
            return ChunkExtraction()
        if schema is SectionWikiLean:
            return SectionWikiLean(
                summary="a short summary",
                questions_answered=["what is this section about"],
            )
        if schema is DocWikiOverview:
            return DocWikiOverview(overview="an overview across sections")
        raise AssertionError(f"unexpected schema {schema}")

    monkeypatch.setattr(b.llm, "structured", fake_structured)

    wiki = await build_wiki(doc)
    assert isinstance(wiki, DocWiki)
    assert wiki.doc_id == doc.doc_id
    assert len(wiki.entries) == len(doc.sections)

    # section_id is enforced for every entry
    for entry, section in zip(wiki.entries, doc.sections):
        assert entry.section_id == section.id

    # The revenue metric must appear in the document-wide table; the chunk_id
    # must point to the chunk that actually contains the value.
    revenue_keys = [k for k, m in wiki.key_metrics_table.items() if m.name == "revenue"]
    assert revenue_keys, f"revenue metric missing from key_metrics_table: {wiki.key_metrics_table.keys()}"
    rev_metric = wiki.key_metrics_table[revenue_keys[0]]
    rev_chunk = next(c for c in doc.chunks if c.id == rev_metric.chunk_id)
    assert "383" in rev_chunk.text or "Revenue" in rev_chunk.text

    # Claims and entities propagated through to the section entry that owns the
    # revenue chunk.
    rev_entry = next(e for e in wiki.entries if any(m.name == "revenue" for m in e.metrics))
    assert any("YoY" in cl.text for cl in rev_entry.claims)
    assert any(ent.name == "Apple Inc." for ent in rev_entry.entities)

    # Overview survived
    assert wiki.overview.strip()

    # Persistence round-trip
    loaded = load_wiki(doc.doc_id)
    assert loaded is not None
    assert loaded.doc_id == wiki.doc_id
    assert len(loaded.entries) == len(wiki.entries)

    # Per-chunk extraction fired once per chunk; one summary per section; one
    # rollup for the whole document.
    assert seen_schemas.count(ChunkExtraction) == len(doc.chunks)
    assert seen_schemas.count(SectionWikiLean) == len(doc.sections)
    assert seen_schemas.count(DocWikiOverview) == 1
