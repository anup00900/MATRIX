import pytest
from pathlib import Path
from app.parser.pdf import parse_pdf
from app.parser import pdf as pdf_mod
from app.retriever.index import build_index
from app.retriever.naive import NaiveRetriever
from app.agent.runner import run_cell
from app.agent.types import (
    DecompositionPlan, DraftAnswer, VerifierNote,
)
from app.agent import decompose as dec_mod
from app.agent import draft as draft_mod
from app.agent import verify as ver_mod

PAGES_MD = [
    "## Item 1. Business\n\nApple Inc. designs and sells consumer electronics.",
    "## Item 1A. Risk Factors\n\nSupply chain concentration in East Asia is a material risk.",
    "## Item 7. MD&A\n\nRevenue for fiscal 2023 was $383.3 billion, up 2.8% YoY.",
]


@pytest.mark.asyncio
async def test_run_cell_happy_path(monkeypatch, tmp_path):
    from app import settings as s_mod
    monkeypatch.setattr(s_mod.settings, "storage_root", tmp_path)
    s_mod.settings.traces_dir.mkdir(parents=True, exist_ok=True)

    call = {"i": 0}
    async def fake_vision(*, system, user_text, image_b64_png, **kw):
        i = call["i"]; call["i"] += 1
        return PAGES_MD[i % len(PAGES_MD)]
    monkeypatch.setattr(pdf_mod.llm, "vision_chat", fake_vision)

    doc = await parse_pdf(Path("tests/fixtures/tiny.pdf"))
    await build_index(doc, force_local=True)
    retriever = NaiveRetriever(force_local=True)

    md_a_chunk = [c for c in doc.chunks if "383" in c.text or "Revenue" in c.text][0]

    async def fake_decompose(**kw):
        return DecompositionPlan(
            sub_questions=["fiscal 2023 revenue"],
            expected_answer_shape="percentage",
        )
    async def fake_draft(**kw):
        return DraftAnswer(
            answer="2.8%",
            citations=[md_a_chunk.id],
            reasoning_trace=["Revenue grew 2.8% YoY in fiscal 2023."],
        )
    async def fake_verify(**kw):
        return [VerifierNote(claim="Revenue grew 2.8%", status="supported")]

    monkeypatch.setattr(dec_mod, "decompose", fake_decompose)
    monkeypatch.setattr(draft_mod, "draft", fake_draft)
    monkeypatch.setattr(ver_mod, "verify", fake_verify)
    # runner.py imports the helpers by name — monkeypatch those bindings too
    from app.agent import runner as runner_mod
    monkeypatch.setattr(runner_mod, "decompose", fake_decompose)
    monkeypatch.setattr(runner_mod, "draft_step", fake_draft)
    monkeypatch.setattr(runner_mod, "verify_step", fake_verify)

    states: list[str] = []
    async def on_state(state, data=None):
        states.append(state)

    res = await run_cell(
        prompt="Revenue YoY",
        doc=doc,
        retriever=retriever,
        retriever_mode="naive",
        shape_hint="percentage",
        section_index=[{"id": s.id, "title": s.title} for s in doc.sections],
        on_state=on_state,
    )

    assert res.answer == "2.8%"
    assert res.answer_shape == "percentage"
    assert res.confidence == "high"
    assert res.retriever_mode == "naive"
    assert res.citations, "should include citations"
    assert res.citations[0].chunk_id == md_a_chunk.id
    assert res.citations[0].page == md_a_chunk.page
    assert res.citations[0].snippet.strip()
    assert len(res.trace_id) >= 20   # ULID
    assert states == ["retrieving", "drafting", "verifying"]

    # trace file persisted
    from app.settings import settings as _s
    trace_path = _s.traces_dir / f"{res.trace_id}.json.gz"
    assert trace_path.exists()


@pytest.mark.asyncio
async def test_run_cell_revises_once_on_contradiction(monkeypatch, tmp_path):
    from app import settings as s_mod
    monkeypatch.setattr(s_mod.settings, "storage_root", tmp_path)
    s_mod.settings.traces_dir.mkdir(parents=True, exist_ok=True)

    call = {"i": 0}
    async def fake_vision(*, system, user_text, image_b64_png, **kw):
        i = call["i"]; call["i"] += 1
        return PAGES_MD[i % len(PAGES_MD)]
    monkeypatch.setattr(pdf_mod.llm, "vision_chat", fake_vision)

    doc = await parse_pdf(Path("tests/fixtures/tiny.pdf"))
    await build_index(doc, force_local=True)
    retriever = NaiveRetriever(force_local=True)
    md_a_chunk = [c for c in doc.chunks if "383" in c.text or "Revenue" in c.text][0]

    async def fake_decompose(**kw):
        return DecompositionPlan(
            sub_questions=["fiscal 2023 revenue"],
            expected_answer_shape="percentage",
        )

    draft_calls = {"n": 0}
    async def fake_draft(**kw):
        draft_calls["n"] += 1
        return DraftAnswer(
            answer="2.8%",
            citations=[md_a_chunk.id],
            reasoning_trace=["Revenue grew 2.8% YoY in fiscal 2023."],
        )

    verify_calls = {"n": 0}
    async def fake_verify(**kw):
        verify_calls["n"] += 1
        if verify_calls["n"] == 1:
            return [VerifierNote(claim="c", status="contradicted", note="mismatch")]
        return [VerifierNote(claim="c", status="supported")]

    from app.agent import runner as runner_mod
    monkeypatch.setattr(runner_mod, "decompose", fake_decompose)
    monkeypatch.setattr(runner_mod, "draft_step", fake_draft)
    monkeypatch.setattr(runner_mod, "verify_step", fake_verify)

    res = await run_cell(
        prompt="Revenue YoY",
        doc=doc, retriever=retriever, retriever_mode="naive",
        shape_hint="percentage",
        section_index=[{"id": s.id, "title": s.title} for s in doc.sections],
    )

    assert draft_calls["n"] == 2, "should revise exactly once"
    assert verify_calls["n"] == 2, "should verify twice (original + revision)"
    assert res.confidence == "high"
    assert res.trace["revisions"], "trace should record the revision"
