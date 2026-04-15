import pytest
from pathlib import Path
from app.parser.pdf import parse_pdf
from app.parser import pdf as pdf_mod
from app.retriever.index import build_index
from app.retriever.naive import NaiveRetriever

PAGES_MD = [
    "## Item 1. Business\n\nApple Inc. designs and sells consumer electronics.",
    "## Item 1A. Risk Factors\n\nSupply chain concentration in East Asia is a material risk.",
    "## Item 7. MD&A\n\nRevenue for fiscal 2023 was $383.3 billion, up 2.8% YoY.",
]

@pytest.mark.asyncio
async def test_naive_retrieval(monkeypatch):
    call = {"i": 0}
    async def fake_vision(*, system, user_text, image_b64_png, **kw):
        i = call["i"]; call["i"] += 1
        return PAGES_MD[i % len(PAGES_MD)]
    monkeypatch.setattr(pdf_mod.llm, "vision_chat", fake_vision)

    doc = await parse_pdf(Path("tests/fixtures/tiny.pdf"))
    await build_index(doc, force_local=True)
    r = NaiveRetriever(force_local=True)
    ev = await r.retrieve("revenue figures fiscal 2023", doc, k=3)
    assert ev
    # at least one of the top hits should be the revenue page
    assert any("383" in e.text or "2.8" in e.text or "Revenue" in e.text for e in ev)
