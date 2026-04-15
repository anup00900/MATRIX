import pytest
from pathlib import Path
from app.parser.pdf import parse_pdf
from app.parser import pdf as pdf_mod
from app.retriever.index import build_index
from app.retriever.isd import ISDRetriever
from app.retriever import isd as isd_mod

PAGES_MD = [
    "## Item 1. Business\n\nApple Inc. designs and sells consumer electronics.",
    "## Item 1A. Risk Factors\n\nSupply chain concentration in East Asia is a material risk.",
    "## Item 7. MD&A\n\nRevenue for fiscal 2023 was $383.3 billion, up 2.8% YoY.",
]

@pytest.mark.asyncio
async def test_isd_retrieval(monkeypatch):
    call = {"i": 0}
    async def fake_vision(*, system, user_text, image_b64_png, **kw):
        i = call["i"]; call["i"] += 1
        return PAGES_MD[i % len(PAGES_MD)]
    monkeypatch.setattr(pdf_mod.llm, "vision_chat", fake_vision)

    async def fake_structured(*, messages, schema, **kw):
        return schema(queries=["fiscal 2023 revenue", "supply chain risk"])
    monkeypatch.setattr(isd_mod.llm, "structured", fake_structured)

    doc = await parse_pdf(Path("tests/fixtures/tiny.pdf"))
    await build_index(doc, force_local=True)
    r = ISDRetriever(force_local=True)
    ev = await r.retrieve("Summarise financial performance and risks.", doc, k=4)
    assert len(ev) >= 2
