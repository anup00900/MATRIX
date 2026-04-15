import pytest
from pathlib import Path
from app.parser.pdf import parse_pdf
from app.parser import pdf as pdf_mod

@pytest.mark.asyncio
async def test_parse_tiny(monkeypatch):
    pages_md = [
        "## Item 1. Business\n\nApple Inc. designs and sells consumer electronics.",
        "## Item 1A. Risk Factors\n\nSupply chain concentration in East Asia is a material risk.",
        "## Item 7. MD&A\n\nRevenue for fiscal 2023 was $383.3 billion, up 2.8% YoY.",
    ]
    call = {"i": 0}
    async def fake_vision_chat(*, system, user_text, image_b64_png, **kw):
        i = call["i"]; call["i"] += 1
        return pages_md[i % len(pages_md)]
    monkeypatch.setattr(pdf_mod.llm, "vision_chat", fake_vision_chat)

    doc = await parse_pdf(Path("tests/fixtures/tiny.pdf"))
    assert doc.n_pages == 3
    titles = [s.title for s in doc.sections]
    assert any("Item 1." in t for t in titles)
    assert any("Item 7" in t for t in titles)
    assert len(doc.chunks) >= 3
    for c in doc.chunks:
        assert c.bboxes and c.bboxes[0].page >= 1
        assert c.text.strip()
    # vision called exactly once per page
    assert call["i"] == 3
