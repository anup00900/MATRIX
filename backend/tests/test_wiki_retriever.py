import pytest
from pathlib import Path
from app.parser.pdf import parse_pdf
from app.parser import pdf as pdf_mod
from app.retriever.index import build_index
from app.retriever.wiki import WikiRetriever
from app.wiki.schema import (
    DocWiki, SectionWikiEntry, SectionIndexItem, Claim, Metric,
)

PAGES_MD = [
    "## Item 1. Business\n\nApple Inc. designs and sells consumer electronics.",
    "## Item 1A. Risk Factors\n\nSupply chain concentration in East Asia is a material risk.",
    "## Item 7. MD&A\n\nRevenue for fiscal 2023 was $383.3 billion, up 2.8% YoY.",
]


@pytest.mark.asyncio
async def test_wiki_retriever_prefers_metric_hit(monkeypatch):
    call = {"i": 0}
    async def fake_vision(*, system, user_text, image_b64_png, **kw):
        i = call["i"]; call["i"] += 1
        return PAGES_MD[i % len(PAGES_MD)]
    monkeypatch.setattr(pdf_mod.llm, "vision_chat", fake_vision)

    doc = await parse_pdf(Path("tests/fixtures/tiny.pdf"))
    await build_index(doc, force_local=True)

    # pick the chunk on the MD&A page as the metric evidence
    md_a_chunk = [c for c in doc.chunks if "383" in c.text or "Revenue" in c.text][0]
    revenue_metric = Metric(
        name="revenue", value=383.3, unit="USD_billions",
        period="FY2023", chunk_id=md_a_chunk.id,
    )
    section_id = next(s.id for s in doc.sections if "Item 7" in s.title)
    wiki = DocWiki(
        doc_id=doc.doc_id, overview="stub",
        section_index=[SectionIndexItem(id=s.id, title=s.title) for s in doc.sections],
        entries=[SectionWikiEntry(
            section_id=section_id,
            summary="revenue grew",
            claims=[Claim(text="Revenue grew 2.8% YoY", evidence_chunks=[md_a_chunk.id])],
            metrics=[revenue_metric],
        )],
        key_metrics_table={"revenue": revenue_metric},
    )

    r = WikiRetriever(wiki=wiki, force_local=True)
    ev = await r.retrieve("revenue fiscal 2023", doc, k=3)
    assert ev
    top = ev[0]
    assert top.chunk_id == md_a_chunk.id
    assert top.source in {"wiki.metric", "wiki.claim"}


@pytest.mark.asyncio
async def test_wiki_retriever_falls_back_to_chunks_when_wiki_empty(monkeypatch):
    call = {"i": 0}
    async def fake_vision(*, system, user_text, image_b64_png, **kw):
        i = call["i"]; call["i"] += 1
        return PAGES_MD[i % len(PAGES_MD)]
    monkeypatch.setattr(pdf_mod.llm, "vision_chat", fake_vision)

    doc = await parse_pdf(Path("tests/fixtures/tiny.pdf"))
    await build_index(doc, force_local=True)

    empty_wiki = DocWiki(
        doc_id=doc.doc_id, overview="",
        section_index=[SectionIndexItem(id=s.id, title=s.title) for s in doc.sections],
        entries=[],
        key_metrics_table={},
    )
    r = WikiRetriever(wiki=empty_wiki, force_local=True)
    ev = await r.retrieve("revenue fiscal 2023", doc, k=3)
    assert ev, "fallback should still return chunk hits"
    assert all(e.source == "chunk.vector" for e in ev)
