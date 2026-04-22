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
