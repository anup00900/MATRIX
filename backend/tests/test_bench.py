import json
import pytest
from pathlib import Path


def test_normalise_plan_schema():
    from app.bench.dataset import normalise_question
    row = {
        "question": "What was revenue?",
        "answer": "$383.3B",
        "doc_name": "AAPL_2023_10K",
        "page_number": 42,
        "evidence_text": "Revenue was 383.3 billion.",
    }
    q = normalise_question(row)
    assert q["doc_name"].endswith(".pdf")
    assert q["gold_pages"] == [42]
    assert q["evidence_text"].startswith("Revenue")


def test_normalise_nested_evidence():
    from app.bench.dataset import normalise_question
    row = {
        "question": "Q",
        "answer": "A",
        "doc_name": "X.pdf",
        "evidence": [{"page": 5, "text": "e1"}, {"page": 6, "text": "e2"}],
    }
    q = normalise_question(row)
    assert q["gold_pages"] == [5, 6]
    assert "e1" in q["evidence_text"] and "e2" in q["evidence_text"]


def test_page_match_tolerance():
    from app.bench.run import _page_match
    # exact match
    r, p = _page_match([42], [42])
    assert r == 1.0 and p == 1.0
    # ±1 tolerance
    r, p = _page_match([43], [42])
    assert r == 1.0 and p == 1.0
    # miss
    r, p = _page_match([50], [42])
    assert r == 0.0 and p == 0.0
    # empty cited
    r, p = _page_match([], [42])
    assert r == 0.0 and p == 0.0


def test_report_markdown(tmp_path):
    from app.bench.run import report
    p = tmp_path / "naive.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in [
        {"verdict": "correct", "page_recall": 1.0, "page_precision": 1.0,
         "latency_ms": 1000, "tokens": 500},
        {"verdict": "incorrect", "page_recall": 0.0, "page_precision": 0.0,
         "latency_ms": 2000, "tokens": 700},
        {"error": "boom"},
    ]))
    out = tmp_path / "report.md"
    text = report({"naive": p}, out)
    assert "| naive | 1 | 0 | 1 | 1 |" in text
    assert out.exists()


@pytest.mark.asyncio
async def test_run_mode_end_to_end(monkeypatch, tmp_path):
    # Isolate storage
    from app import settings as s_mod
    monkeypatch.setattr(s_mod.settings, "storage_root", tmp_path)
    for d in (s_mod.settings.pdfs_dir, s_mod.settings.parsed_dir,
              s_mod.settings.vectors_dir, s_mod.settings.wikis_dir,
              s_mod.settings.traces_dir, s_mod.settings.db_path.parent):
        d.mkdir(parents=True, exist_ok=True)

    # Fake dataset
    from app.bench import run as run_mod
    from app.bench import dataset as ds_mod
    def fake_load(limit=None, split="train"):
        return [
            {"question": "What was revenue?", "answer": "$383.3B",
             "doc_name": "x.pdf", "page_number": 3,
             "evidence_text": "Revenue 383.3B"},
        ]
    monkeypatch.setattr(ds_mod, "load_questions", fake_load)
    monkeypatch.setattr(run_mod, "load_questions", fake_load)

    # Fake PDF fetch → point at the tiny fixture
    real_fixture = Path("tests/fixtures/tiny.pdf").resolve()
    async def fake_fetch_pdf(doc_name: str):
        return real_fixture
    monkeypatch.setattr(run_mod, "fetch_pdf", fake_fetch_pdf)

    # Fake the heavy pipeline stages
    from app.parser.schema import StructuredDoc, Section, Chunk, Bbox, DocMeta, Page
    fake_doc = StructuredDoc(
        doc_id="fake-doc",
        n_pages=1,
        meta=DocMeta(company="Apple", filing_type="10-K"),
        pages=[Page(page_no=1, markdown="## Item 7\nRevenue 383.3B", width=612, height=792)],
        sections=[Section(id="s1", title="Item 7", level=2, page_start=1, page_end=1, text="Revenue 383.3B")],
        chunks=[Chunk(id="c1", section_id="s1", page=3, text="Revenue 383.3B",
                      token_count=4, bboxes=[Bbox(page=3, bbox=(0,0,612,792))])],
    )
    async def fake_parse_pdf(path): return fake_doc
    async def fake_meta(doc): return DocMeta(company="Apple", filing_type="10-K")
    async def fake_build_index(doc, **kw): return None
    async def fake_build_wiki(doc): return None
    monkeypatch.setattr(run_mod, "parse_pdf", fake_parse_pdf)
    monkeypatch.setattr(run_mod, "extract_doc_meta", fake_meta)
    monkeypatch.setattr(run_mod, "build_index", fake_build_index)
    monkeypatch.setattr(run_mod, "build_wiki", fake_build_wiki)
    monkeypatch.setattr(run_mod, "load_wiki", lambda doc_id: None)  # force ISD/naive paths

    # Fake retriever so we don't touch embeddings
    class FakeRet:
        async def retrieve(self, query, doc, k=8):
            from app.retriever.types import Evidence
            c = doc.chunks[0]
            return [Evidence(chunk_id=c.id, text=c.text, page=c.page,
                             bboxes=c.bboxes, score=0.1, source="chunk.vector")]
    monkeypatch.setattr(run_mod, "_make_retriever", lambda mode, parsed: FakeRet())

    # Fake run_cell to avoid the agent's own LLM calls
    from app.agent.types import CellResult, Citation
    async def fake_run_cell(**kw):
        return CellResult(
            answer="$383.3B",
            answer_shape="text",
            citations=[Citation(chunk_id="c1", page=3, snippet="Revenue 383.3B",
                                 bboxes=[{"page": 3, "bbox": [0, 0, 612, 792]}])],
            confidence="high",
            tokens_used=123,
            latency_ms=456,
            retriever_mode=kw["retriever_mode"],
            trace_id="t-1",
            trace={},
        )
    monkeypatch.setattr(run_mod, "run_cell", fake_run_cell)

    # Fake judge
    async def fake_chat(messages, **kw): return "correct"
    monkeypatch.setattr(run_mod.llm, "chat", fake_chat)

    out = tmp_path / "results"
    results = await run_mod.run_mode(mode="naive", limit=1, out_dir=out)
    assert len(results) == 1
    r = results[0]
    assert r["verdict"] == "correct"
    assert r["page_recall"] == 1.0    # gold=3, cited=3 → exact
    assert r["page_precision"] == 1.0
    assert (out / "naive.jsonl").exists()
