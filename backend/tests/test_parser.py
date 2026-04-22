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
