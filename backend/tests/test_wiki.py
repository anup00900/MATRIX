import pytest
from pathlib import Path
from app.parser.pdf import parse_pdf
from app.parser import pdf as pdf_mod
from app.wiki.builder import build_wiki, load_wiki
from app.wiki.schema import (
    DocWiki, SectionWikiEntry, DocWikiRollup, Metric,
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

    # structured mock: section entries + one rollup
    seen_schemas = []
    async def fake_structured(*, messages, schema, **kw):
        seen_schemas.append(schema)
        if schema is SectionWikiEntry:
            return SectionWikiEntry(
                section_id="placeholder",
                summary="a short summary",
                questions_answered=["what is this section about"],
            )
        if schema is DocWikiRollup:
            return DocWikiRollup(
                overview="an overview across sections",
                key_metrics_table={
                    "revenue": Metric(name="revenue", value=383.3, unit="USD_billions",
                                      period="FY2023", chunk_id=doc.chunks[-1].id),
                },
            )
        raise AssertionError(f"unexpected schema {schema}")
    monkeypatch.setattr(b.llm, "structured", fake_structured)

    wiki = await build_wiki(doc)
    assert isinstance(wiki, DocWiki)
    assert wiki.doc_id == doc.doc_id
    assert len(wiki.entries) == len(doc.sections)
    # section_id should be enforced even if the model omitted / stubbed it
    for entry, section in zip(wiki.entries, doc.sections):
        assert entry.section_id == section.id
    assert "revenue" in wiki.key_metrics_table
    assert wiki.overview.strip()

    # persistence round-trip
    loaded = load_wiki(doc.doc_id)
    assert loaded is not None
    assert loaded.doc_id == wiki.doc_id
    assert len(loaded.entries) == len(wiki.entries)

    # exactly one rollup call, one per section for the sections
    assert seen_schemas.count(DocWikiRollup) == 1
    assert seen_schemas.count(SectionWikiEntry) == len(doc.sections)
