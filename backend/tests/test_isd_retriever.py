import pytest
from pathlib import Path
from app.parser.pdf import parse_pdf
from app.parser import pdf as pdf_mod
from app.retriever.index import build_index
from app.retriever.isd import ISDRetriever, DecompPlan, RerankResult, ChunkScore
from app.retriever import isd as isd_mod

PAGES_MD = [
    "## Item 1. Business\n\nApple Inc. designs and sells consumer electronics.",
    "## Item 1A. Risk Factors\n\nSupply chain concentration in East Asia is a material risk.",
    "## Item 7. MD&A\n\nRevenue for fiscal 2023 was $383.3 billion, up 2.8% YoY.",
]


@pytest.mark.asyncio
async def test_isd_runs_decompose_then_attention_rerank(monkeypatch):
    call = {"i": 0}
    async def fake_vision(*, system, user_text, image_b64_png, **kw):
        i = call["i"]; call["i"] += 1
        return PAGES_MD[i % len(PAGES_MD)]
    monkeypatch.setattr(pdf_mod.llm, "vision_chat", fake_vision)

    doc = await parse_pdf(Path("tests/fixtures/tiny.pdf"))
    await build_index(doc, force_local=True)

    counts = {"decompose": 0, "rerank": 0}

    async def fake_structured(*, messages, schema, **kw):
        if schema is DecompPlan:
            counts["decompose"] += 1
            target = [s.id for s in doc.sections if "Item 7" in s.title]
            return DecompPlan(
                sub_queries=["fiscal 2023 revenue", "supply chain risk"],
                target_section_ids=target,
            )
        if schema is RerankResult:
            counts["rerank"] += 1
            block = messages[-1]["content"]
            scores = []
            for c in doc.chunks:
                if f"[{c.id}]" in block:
                    if "383" in c.text or "Revenue" in c.text:
                        scores.append(ChunkScore(chunk_id=c.id, score=1.0))
                    elif "Supply chain" in c.text:
                        scores.append(ChunkScore(chunk_id=c.id, score=0.7))
                    else:
                        scores.append(ChunkScore(chunk_id=c.id, score=0.1))
            return RerankResult(scores=scores)
        raise AssertionError(f"unexpected schema {schema}")

    monkeypatch.setattr(isd_mod.llm, "structured", fake_structured)

    r = ISDRetriever(force_local=True)
    ev = await r.retrieve("Summarise financial performance and risks.", doc, k=4)

    assert counts["decompose"] == 1
    assert counts["rerank"] == 1
    assert ev
    top = ev[0]
    assert "383" in top.text or "Revenue" in top.text
    for e in ev:
        assert e.source == "chunk.isd"


@pytest.mark.asyncio
async def test_isd_section_targeting_pulls_in_target_chunk(monkeypatch):
    call = {"i": 0}
    async def fake_vision(*, system, user_text, image_b64_png, **kw):
        i = call["i"]; call["i"] += 1
        return PAGES_MD[i % len(PAGES_MD)]
    monkeypatch.setattr(pdf_mod.llm, "vision_chat", fake_vision)

    doc = await parse_pdf(Path("tests/fixtures/tiny.pdf"))
    await build_index(doc, force_local=True)
    target_section_id = next(s.id for s in doc.sections if "Item 7" in s.title)

    async def fake_structured(*, messages, schema, **kw):
        if schema is DecompPlan:
            return DecompPlan(sub_queries=["any"], target_section_ids=[target_section_id])
        if schema is RerankResult:
            return RerankResult(scores=[
                ChunkScore(chunk_id=c.id, score=0.5) for c in doc.chunks
            ])
        raise AssertionError(schema)

    monkeypatch.setattr(isd_mod.llm, "structured", fake_structured)

    r = ISDRetriever(force_local=True)
    ev = await r.retrieve("anything", doc, k=4)
    chunk_section = {c.id: c.section_id for c in doc.chunks}
    in_target = [e for e in ev if chunk_section.get(e.chunk_id) == target_section_id]
    assert in_target, "in-target chunk should make it into top-k"
