import pytest
from app.parser.meta import extract_doc_meta
from app.parser.schema import StructuredDoc, Page, DocMeta

@pytest.mark.asyncio
async def test_meta_extraction(monkeypatch):
    from app.parser import meta as m
    async def fake_structured(*, messages, schema, **kw):
        return DocMeta(company="Apple Inc.", filing_type="10-K", period_end="2023-09-30")
    monkeypatch.setattr(m.llm, "structured", fake_structured)
    doc = StructuredDoc(doc_id="x", n_pages=1, pages=[
        Page(page_no=1, markdown="# Apple Inc.\n\nAnnual Report on Form 10-K for fiscal 2023",
             width=612, height=792)
    ], sections=[], chunks=[])
    out = await extract_doc_meta(doc)
    assert out.company == "Apple Inc." and out.filing_type == "10-K"
