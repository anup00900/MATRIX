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


from app.parser.pdf import _empty_cell_ratio, ChartRegion


def test_empty_cell_ratio_all_empty():
    table = (
        "| Year | Revenue | Net Income |\n"
        "|---|---|---|\n"
        "| FY2022 |  |  |\n"
        "| FY2023 |  |  |\n"
        "| FY2024 |  |  |\n"
    )
    ratio, total, empty = _empty_cell_ratio(table)
    assert total == 6
    assert empty == 6
    assert ratio == 1.0


def test_empty_cell_ratio_all_filled():
    table = (
        "| Year | Revenue | Net Income |\n"
        "|---|---|---|\n"
        "| FY2022 | 27 | 10 |\n"
        "| FY2023 | 27 | 10 |\n"
    )
    ratio, total, empty = _empty_cell_ratio(table)
    assert total == 4
    assert empty == 0
    assert ratio == 0.0


def test_empty_cell_ratio_mixed():
    # 2 data rows × 2 data cells after excluding the row-label column = 4 cells.
    # Empty: middle col on row1 (1) + both data cells on row2 (2) = 3.
    table = (
        "| Year | Revenue | Net Income |\n"
        "|---|---|---|\n"
        "| FY2022 |  | 10 |\n"
        "| FY2023 |  |  |\n"
    )
    ratio, total, empty = _empty_cell_ratio(table)
    assert total == 4
    assert empty == 3
    assert ratio == 0.75


def test_empty_cell_ratio_not_a_table():
    ratio, total, empty = _empty_cell_ratio("Just some prose, no pipes here.")
    assert total == 0
    assert empty == 0
    assert ratio == 0.0


def test_chart_region_dataclass_shape():
    r = ChartRegion(
        page_no=3, chart_index=0,
        line_start=10, line_end=15,
        original_text="| a | b |\n|---|---|\n|  |  |\n",
        kind="empty_cells",
        image_bbox=None,
    )
    assert r.page_no == 3
    assert r.kind == "empty_cells"
    assert r.line_end - r.line_start == 5


from app.parser.schema import Page
from app.parser.pdf import _find_chart_regions


def _make_page(page_no: int, markdown: str) -> Page:
    return Page(page_no=page_no, markdown=markdown, width=612.0, height=792.0, failed=False)


def test_find_chart_regions_detects_empty_cell_table():
    md = (
        "# FINANCIAL HIGHLIGHTS\n"
        "\n"
        "| Year | Revenue | Net Income |\n"
        "|---|---|---|\n"
        "| FY2022 |  |  |\n"
        "| FY2023 |  |  |\n"
        "| FY2024 |  |  |\n"
        "\n"
        "Note: source FY2026 10-K.\n"
    )
    page = _make_page(3, md)
    regions = _find_chart_regions(page)
    assert len(regions) == 1
    r = regions[0]
    assert r.kind == "empty_cells"
    assert r.page_no == 3
    assert r.chart_index == 0
    assert "| FY2022 |" in r.original_text
    assert "# FINANCIAL HIGHLIGHTS" not in r.original_text
    assert "Note: source" not in r.original_text


def test_find_chart_regions_skips_fully_populated_table():
    md = (
        "| Year | Revenue |\n"
        "|---|---|\n"
        "| FY2022 | 27 |\n"
        "| FY2023 | 61 |\n"
    )
    page = _make_page(4, md)
    regions = _find_chart_regions(page)
    assert regions == []


def test_find_chart_regions_multi_region_same_page():
    md = (
        "| Year | Revenue | Net Income |\n"
        "|---|---|---|\n"
        "| FY2022 |  |  |\n"
        "| FY2023 |  |  |\n"
        "\n"
        "Prose line in the middle.\n"
        "\n"
        "| Year | Gross Margin % |\n"
        "|---|---|\n"
        "| FY2022 |  |\n"
        "| FY2023 |  |\n"
    )
    page = _make_page(3, md)
    regions = _find_chart_regions(page)
    assert len(regions) == 2
    assert regions[0].chart_index == 0
    assert regions[1].chart_index == 1
    assert regions[0].line_start < regions[1].line_start


def test_find_chart_regions_coexists_with_real_table():
    md = (
        "| Year | Revenue |\n"
        "|---|---|\n"
        "| FY2022 | 27 |\n"
        "| FY2023 | 61 |\n"
        "\n"
        "Some prose.\n"
        "\n"
        "| Year | Net Income |\n"
        "|---|---|\n"
        "| FY2022 |  |\n"
        "| FY2023 |  |\n"
    )
    page = _make_page(3, md)
    regions = _find_chart_regions(page)
    assert len(regions) == 1
    assert "| Net Income |" in regions[0].original_text
    assert "27" not in regions[0].original_text


from app.parser.pdf import _detect_chart_pages


def test_detect_chart_pages_empty_cell_signature():
    pages = [
        _make_page(1, "# Intro\n\nJust prose, no table.\n"),
        _make_page(2, "| A | B |\n|---|---|\n|  |  |\n|  |  |\n"),
    ]
    image_counts = {1: 0, 2: 0}
    result = _detect_chart_pages(pages, image_counts)
    assert 1 not in result
    assert 2 in result
    assert len(result[2]) == 1
    assert result[2][0].kind == "empty_cells"


def test_detect_chart_pages_image_without_table_signature():
    pages = [
        _make_page(6, "# Selected Financial Chart\n\nThe following chart was included.\n\nSource: 10-K.\n"),
    ]
    image_counts = {6: 1}  # fitz detected an embedded image
    result = _detect_chart_pages(pages, image_counts)
    assert 6 in result
    assert len(result[6]) == 1
    assert result[6][0].kind == "image_no_table"
    r = result[6][0]
    assert r.line_start >= 0
    assert r.line_end >= r.line_start


def test_detect_chart_pages_image_but_has_table_not_flagged():
    pages = [
        _make_page(2, "| A | B |\n|---|---|\n| 1 | 2 |\n"),
    ]
    image_counts = {2: 1}  # image exists but a table was already emitted
    result = _detect_chart_pages(pages, image_counts)
    # Signature 2 requires NO pipes; a populated table disqualifies.
    assert result == {}


def test_detect_chart_pages_no_image_no_table_not_flagged():
    pages = [_make_page(1, "# Heading\n\nSome prose.\n")]
    image_counts = {1: 0}
    result = _detect_chart_pages(pages, image_counts)
    assert result == {}


def test_detect_chart_pages_failed_page_not_flagged():
    p = Page(page_no=5, markdown="", width=612.0, height=792.0, failed=True)
    image_counts = {5: 1}
    result = _detect_chart_pages([p], image_counts)
    assert result == {}


def test_detect_chart_pages_image_no_trailing_newline():
    # Page markdown without a trailing newline — detector must still anchor
    # signature-2 insertion past the last content line. Task 4's splice is
    # responsible for ensuring the preceding line gains a '\n' before the
    # chart block is inserted.
    md = "# Heading\n\nSome prose"  # note: no trailing \n
    pages = [_make_page(6, md)]
    result = _detect_chart_pages(pages, {6: 1})
    assert 6 in result
    r = result[6][0]
    assert r.kind == "image_no_table"
    assert r.line_start == len(md.splitlines())
    assert r.line_end == r.line_start


from app.parser.pdf import _splice_chart_blocks


def test_splice_replaces_empty_cell_region_in_place():
    md = (
        "# FINANCIAL HIGHLIGHTS\n"
        "\n"
        "| Year | Revenue |\n"
        "|---|---|\n"
        "| FY2022 |  |\n"
        "| FY2023 |  |\n"
        "\n"
        "Note: 10-K source.\n"
    )
    page = _make_page(3, md)
    regions = _find_chart_regions(page)
    assert len(regions) == 1
    verified_blocks = {
        (3, 0): (
            "### Annual Revenue\n"
            "**Chart type:** bar\n"
            "\n"
            "| Year | Revenue |\n"
            "|---|---|\n"
            "| FY2022 | 27 |\n"
            "| FY2023 | 61 |\n"
            "\n"
            "**Trend:** up.\n"
        ),
    }
    out_pages = _splice_chart_blocks([page], {3: regions}, verified_blocks)
    new_md = out_pages[0].markdown
    assert "# FINANCIAL HIGHLIGHTS" in new_md
    assert "Note: 10-K source." in new_md
    assert "### Annual Revenue" in new_md
    assert "| FY2022 | 27 |" in new_md
    # Original empty-cell lines are gone.
    assert "| FY2022 |  |" not in new_md


def test_splice_preserves_text_only_pages():
    page = _make_page(1, "# Heading\n\nPure prose.\n")
    out_pages = _splice_chart_blocks([page], {}, {})
    assert out_pages[0].markdown == "# Heading\n\nPure prose.\n"


def test_splice_multiple_regions_reverse_order_safe():
    md = (
        "| Year | A |\n"
        "|---|---|\n"
        "|  |  |\n"
        "|  |  |\n"
        "\n"
        "Middle prose.\n"
        "\n"
        "| Year | B |\n"
        "|---|---|\n"
        "|  |  |\n"
        "|  |  |\n"
    )
    page = _make_page(3, md)
    regions = _find_chart_regions(page)
    assert len(regions) == 2
    verified_blocks = {
        (3, 0): "### Chart A\n| Year | A |\n|---|---|\n| FY2022 | 10 |\n",
        (3, 1): "### Chart B\n| Year | B |\n|---|---|\n| FY2022 | 20 |\n",
    }
    out = _splice_chart_blocks([page], {3: regions}, verified_blocks)
    new_md = out[0].markdown
    assert "### Chart A" in new_md
    assert "### Chart B" in new_md
    assert "Middle prose." in new_md
    # Chart A appears before Chart B (document order preserved).
    assert new_md.index("### Chart A") < new_md.index("Middle prose.")
    assert new_md.index("Middle prose.") < new_md.index("### Chart B")


def test_splice_image_no_table_inserts_at_end():
    md = "# Selected Financial Chart\n\nCaption.\n\nSource: 10-K.\n"
    page = _make_page(6, md)
    region = ChartRegion(
        page_no=6, chart_index=0,
        line_start=len(md.splitlines()),
        line_end=len(md.splitlines()),
        original_text="",
        kind="image_no_table",
    )
    verified_blocks = {(6, 0): "### Cumulative Return\n| Date | NVDA |\n|---|---|\n| 1/31/2021 | 100 |\n"}
    out = _splice_chart_blocks([page], {6: [region]}, verified_blocks)
    new_md = out[0].markdown
    assert "# Selected Financial Chart" in new_md
    assert "Source: 10-K." in new_md
    assert "### Cumulative Return" in new_md
    # Chart block appears after source footnote.
    assert new_md.index("Source: 10-K.") < new_md.index("### Cumulative Return")


def test_splice_missing_verified_block_leaves_region_untouched():
    md = (
        "| Year | A |\n"
        "|---|---|\n"
        "|  |  |\n"
    )
    page = _make_page(3, md)
    regions = _find_chart_regions(page)
    # No verified_blocks supplied for this region.
    out = _splice_chart_blocks([page], {3: regions}, {})
    assert out[0].markdown == md  # unchanged


def test_splice_image_no_table_no_trailing_newline():
    # Page markdown without a trailing newline — splice must ensure the
    # preceding prose line gains a '\n' before the chart block is inserted.
    md = "# Heading\n\nSome prose"  # note: no trailing \n
    page = _make_page(6, md)
    region = ChartRegion(
        page_no=6, chart_index=0,
        line_start=len(md.splitlines()),
        line_end=len(md.splitlines()),
        original_text="",
        kind="image_no_table",
    )
    verified_blocks = {(6, 0): "### Chart\n| A |\n|---|\n| 1 |\n"}
    out = _splice_chart_blocks([page], {6: [region]}, verified_blocks)
    new_md = out[0].markdown
    assert "Some prose" in new_md
    assert "### Chart" in new_md
    # The block must NOT concatenate onto "Some prose" without a newline.
    assert "Some prose### Chart" not in new_md
    # Specifically, prose ends with \n before the chart block.
    assert "Some prose\n### Chart" in new_md


import json as _json
from unittest.mock import AsyncMock, MagicMock
from app.parser.pdf import _extract_charts, CHART_EXTRACT_SYSTEM


def test_chart_extract_system_prompt_contains_required_sections():
    # Sanity check: the prompt must tell the model to read values from the image
    # and to emit the C-format block.
    p = CHART_EXTRACT_SYSTEM
    assert "image" in p.lower()
    assert "every visible data point" in p.lower() or "every data point" in p.lower()
    assert "series" in p.lower()
    assert "trend" in p.lower()
    assert "yoy" in p.lower() or "year-over-year" in p.lower()
    assert "cagr" in p.lower()


def _mock_llm_response(content: str):
    resp = MagicMock()
    msg = MagicMock()
    msg.content = content
    resp.choices = [MagicMock(message=msg)]
    resp.usage = None
    return resp


@pytest.mark.asyncio
async def test_extract_charts_parses_response(monkeypatch):
    # Simulated page: page 3, one empty-cell region.
    page = _make_page(3, "| Year | Revenue |\n|---|---|\n| FY2022 |  |\n")
    regions = _find_chart_regions(page)
    pages_raw = [(3, "b64data", 612.0, 792.0, "Some fitz text")]

    response_json = _json.dumps([{
        "page_no": 3,
        "chart_index": 0,
        "markdown": "### Annual Revenue\n**Chart type:** bar\n\n| Year | Revenue |\n|---|---|\n| FY2022 | 27 |\n",
    }])
    fake_create = AsyncMock(return_value=_mock_llm_response(response_json))
    monkeypatch.setattr(pdf_mod.llm.client.chat.completions, "create", fake_create)

    blocks = await _extract_charts({3: regions}, pages_raw)
    assert (3, 0) in blocks
    assert "### Annual Revenue" in blocks[(3, 0)]
    assert "| FY2022 | 27 |" in blocks[(3, 0)]
    # Exactly one LLM call for one chart page.
    assert fake_create.await_count == 1


@pytest.mark.asyncio
async def test_extract_charts_returns_empty_on_api_error(monkeypatch):
    page = _make_page(3, "| Year | Revenue |\n|---|---|\n| FY2022 |  |\n")
    regions = _find_chart_regions(page)
    pages_raw = [(3, "b64data", 612.0, 792.0, "")]

    async def raising_create(**kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(pdf_mod.llm.client.chat.completions, "create", raising_create)

    blocks = await _extract_charts({3: regions}, pages_raw)
    assert blocks == {}


@pytest.mark.asyncio
async def test_extract_charts_empty_input_skips_llm(monkeypatch):
    called = {"n": 0}
    async def fake_create(**kwargs):
        called["n"] += 1
        return _mock_llm_response("[]")
    monkeypatch.setattr(pdf_mod.llm.client.chat.completions, "create", fake_create)

    blocks = await _extract_charts({}, [])
    assert blocks == {}
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_extract_charts_strips_code_fences(monkeypatch):
    page = _make_page(3, "| Year | Revenue |\n|---|---|\n| FY2022 |  |\n")
    regions = _find_chart_regions(page)
    pages_raw = [(3, "b64data", 612.0, 792.0, "")]

    # Model sometimes wraps JSON in ```json ... ``` — the parser must strip it.
    wrapped = "```json\n" + _json.dumps([{"page_no": 3, "chart_index": 0, "markdown": "### ok\n"}]) + "\n```"
    monkeypatch.setattr(
        pdf_mod.llm.client.chat.completions, "create",
        AsyncMock(return_value=_mock_llm_response(wrapped)),
    )
    blocks = await _extract_charts({3: regions}, pages_raw)
    assert (3, 0) in blocks
    assert "### ok" in blocks[(3, 0)]


from app.parser.pdf import _verify_charts, CHART_VERIFY_SYSTEM


def test_chart_verify_system_prompt_contains_required_sections():
    p = CHART_VERIFY_SYSTEM
    assert "re-read" in p.lower() or "re read" in p.lower()
    assert "count" in p.lower()  # must instruct model to count bars/points
    assert "recompute" in p.lower()  # derived metrics
    assert "minor tick" in p.lower() or "tick" in p.lower()


@pytest.mark.asyncio
async def test_verify_charts_returns_corrected_block(monkeypatch):
    c1_blocks = {
        (3, 0): "### Revenue\n| Year | Revenue |\n|---|---|\n| FY2022 | 99 |\n",
    }
    pages_raw = [(3, "b64data", 612.0, 792.0, "")]

    corrected = "### Revenue\n| Year | Revenue |\n|---|---|\n| FY2022 | 27 |\n"
    response_json = _json.dumps([{
        "page_no": 3, "chart_index": 0, "markdown": corrected,
    }])
    monkeypatch.setattr(
        pdf_mod.llm.client.chat.completions, "create",
        AsyncMock(return_value=_mock_llm_response(response_json)),
    )

    verified = await _verify_charts(c1_blocks, pages_raw)
    assert verified[(3, 0)] == corrected


@pytest.mark.asyncio
async def test_verify_charts_falls_back_to_c1_on_failure(monkeypatch):
    c1_blocks = {(3, 0): "### C1 output"}
    pages_raw = [(3, "b64data", 612.0, 792.0, "")]

    async def raising(**kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(pdf_mod.llm.client.chat.completions, "create", raising)

    verified = await _verify_charts(c1_blocks, pages_raw)
    assert verified[(3, 0)] == "### C1 output"


@pytest.mark.asyncio
async def test_verify_charts_empty_input_skips_llm(monkeypatch):
    called = {"n": 0}
    async def fake(**kwargs):
        called["n"] += 1
        return _mock_llm_response("[]")
    monkeypatch.setattr(pdf_mod.llm.client.chat.completions, "create", fake)

    verified = await _verify_charts({}, [])
    assert verified == {}
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_verify_charts_partial_response_carries_through(monkeypatch):
    # C1 produced two chart blocks on page 3. The verifier's response only
    # contains a correction for chart 0. Chart 1 must carry through its C1
    # block unchanged, and the output dict keys must equal the input keys.
    c1_blocks = {
        (3, 0): "### C1 chart0",
        (3, 1): "### C1 chart1",
    }
    pages_raw = [(3, "b64", 612.0, 792.0, "")]

    response_json = _json.dumps([
        {"page_no": 3, "chart_index": 0, "markdown": "### corrected chart0"},
    ])
    monkeypatch.setattr(
        pdf_mod.llm.client.chat.completions, "create",
        AsyncMock(return_value=_mock_llm_response(response_json)),
    )

    verified = await _verify_charts(c1_blocks, pages_raw)
    assert verified[(3, 0)] == "### corrected chart0"
    assert verified[(3, 1)] == "### C1 chart1"
    assert set(verified.keys()) == {(3, 0), (3, 1)}


@pytest.mark.asyncio
async def test_parse_pdf_end_to_end_with_chart_page(monkeypatch, tmp_path):
    """End-to-end: Pass A emits empty-cell table; Pass C1+C2 fill it."""
    # Build a tiny one-page PDF with NO embedded text (simulating a chart page).
    pdf_path = tmp_path / "tiny_chart.pdf"
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    # No text inserted — mimics a chart-only page.
    doc.save(str(pdf_path))
    doc.close()

    call_sequence = {"n": 0}

    def response_for(call_idx: int) -> str:
        # Pass A: emits empty-cell table.
        if call_idx == 0:
            return _json.dumps([{
                "page_no": 1,
                "markdown": "| Year | Revenue |\n|---|---|\n| FY2022 |  |\n| FY2023 |  |\n",
            }])
        # Pass B: validation — returns the same empty-cell markdown (no fix available).
        if call_idx == 1:
            return _json.dumps([{
                "page_no": 1,
                "markdown": "| Year | Revenue |\n|---|---|\n| FY2022 |  |\n| FY2023 |  |\n",
            }])
        # Pass C1: chart extraction — fills the values.
        if call_idx == 2:
            return _json.dumps([{
                "page_no": 1, "chart_index": 0,
                "markdown": "### Revenue\n**Chart type:** bar\n\n| Year | Revenue |\n|---|---|\n| FY2022 | 27 |\n| FY2023 | 61 |\n\n**Trend:** up.\n",
            }])
        # Pass C2: verification — returns corrected block.
        return _json.dumps([{
            "page_no": 1, "chart_index": 0,
            "markdown": "### Revenue\n**Chart type:** bar\n\n| Year | Revenue |\n|---|---|\n| FY2022 | 27 |\n| FY2023 | 61 |\n\n**Trend:** verified — revenue up.\n",
        }])

    async def fake_create(**kwargs):
        idx = call_sequence["n"]
        call_sequence["n"] += 1
        return _mock_llm_response(response_for(idx))

    monkeypatch.setattr(pdf_mod.llm.client.chat.completions, "create", fake_create)

    result = await parse_pdf(pdf_path)
    assert result.n_pages == 1
    md = result.pages[0].markdown
    # Chart block spliced in; empty-cell skeleton removed.
    assert "### Revenue" in md
    assert "| FY2022 | 27 |" in md
    assert "| FY2023 | 61 |" in md
    assert "verified — revenue up" in md
    assert "| FY2022 |  |" not in md


@pytest.mark.asyncio
async def test_parse_pdf_text_only_page_no_chart_passes(monkeypatch, tmp_path):
    """Text-only page must NOT trigger C1/C2 — only 1 LLM call total (Pass A)."""
    pdf_path = tmp_path / "tiny_text.pdf"
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "## Section One\n\nPure prose, no chart, no empty cells.")
    doc.save(str(pdf_path))
    doc.close()

    calls = {"n": 0}
    async def fake_create(**kwargs):
        calls["n"] += 1
        # Pass A returns clean prose; Pass B skips because no '|' in markdown;
        # detector finds nothing; C1/C2 skip.
        return _mock_llm_response(_json.dumps([{
            "page_no": 1,
            "markdown": "## Section One\n\nPure prose, no chart.\n",
        }]))
    monkeypatch.setattr(pdf_mod.llm.client.chat.completions, "create", fake_create)

    result = await parse_pdf(pdf_path)
    # Only Pass A fires — no '|' in markdown means Pass B skips, detector finds nothing.
    assert calls["n"] == 1
    assert "Pure prose" in result.pages[0].markdown
