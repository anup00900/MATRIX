# Chart-Aware PDF Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `parse_pdf` emit verbose, accurate markdown for pages containing charts — without changing behavior on text-only pages — via two dedicated LLM passes (extract + verify) that fire only when the existing pipeline produces an empty-cell table or leaves a chart-bearing page without a table.

**Architecture:** Four new steps append to the end of `parse_pdf`, after the existing Pass A (`_extract_batch`) and Pass B (`_validate_table_pages`). A post-hoc detector scans Pass B output for two failure signatures (≥30% empty data cells, or embedded image with no table emitted). Detected regions trigger Pass C1 (chart extraction, vision-first) and Pass C2 (chart verification, per-value re-read). A splice function replaces the failed regions in-place while leaving every other line of `Page.markdown` byte-identical.

**Tech Stack:** Python 3.11+, PyMuPDF (`fitz`), Azure OpenAI (`gpt-4.1` via `llm.client.chat.completions.create`), pydantic, pytest with `pytest-asyncio`.

---

## Preconditions

Before starting, verify you can run the existing parser tests:

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC"
cd backend && python -m pytest tests/test_parser.py -v
```

All changes are in two files:

- **Modify:** `backend/app/parser/pdf.py`
- **Modify:** `backend/tests/test_parser.py`

No new files. No schema changes. No frontend changes.

**Reference reading (do not modify during this plan):**
- `backend/app/parser/pdf.py` — existing pipeline. Functions you'll extend or reference: `_render_page` (lines 88–98), `_extract_batch` (101–158), `_validate_table_pages` (161–220), `parse_pdf` (350–416). Prompt constants: `BATCH_SYSTEM` (19–51), `TABLE_VALIDATE_SYSTEM` (54–79).
- `backend/app/parser/schema.py` — `Page`, `Chunk`, `StructuredDoc` pydantic models. Do not change.
- `backend/app/llm.py` — the `llm` singleton; all new calls use `llm.client.chat.completions.create` (matching the pattern already used by `_extract_batch`).

**Testing pattern reference:** `backend/tests/test_parser.py` uses `pytest-asyncio` and `monkeypatch`. The existing test monkeypatches `pdf_mod.llm.vision_chat`; our new code goes direct to `llm.client.chat.completions.create` (matching existing `_extract_batch`), so our tests mock that call.

---

## Task 1: Add `ChartRegion` dataclass and `_empty_cell_ratio` helper

**Files:**
- Modify: `backend/app/parser/pdf.py` — add imports, dataclass, helper
- Modify: `backend/tests/test_parser.py` — add helper tests

**What this task establishes:** A typed record for a detected chart region plus the pure function that measures empty-cell density. The detector in Task 2 reuses this helper.

- [ ] **Step 1: Write the failing tests for `_empty_cell_ratio`**

Append to `backend/tests/test_parser.py`:

```python
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
    # 2 data rows, 3 data cols = 6 cells. 3 empty (middle col on row1, all of row2).
    table = (
        "| Year | Revenue | Net Income |\n"
        "|---|---|---|\n"
        "| FY2022 |  | 10 |\n"
        "| FY2023 |  |  |\n"
    )
    ratio, total, empty = _empty_cell_ratio(table)
    assert total == 6
    assert empty == 3
    assert ratio == 0.5


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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_parser.py::test_empty_cell_ratio_all_empty tests/test_parser.py::test_chart_region_dataclass_shape -v
```

Expected: `ImportError: cannot import name '_empty_cell_ratio' from 'app.parser.pdf'`.

- [ ] **Step 3: Add the dataclass and helper to `pdf.py`**

In `backend/app/parser/pdf.py`, add `dataclass` to the existing `dataclasses` import if absent; otherwise add a new import. Add these definitions just before the `BATCH_SYSTEM` constant (after line 17):

```python
from dataclasses import dataclass
from typing import Literal

EMPTY_CELL_RATIO_THRESHOLD = 0.30


@dataclass
class ChartRegion:
    """A region of page markdown that needs chart-aware re-extraction."""
    page_no: int
    chart_index: int                 # 0-based within the page
    line_start: int                  # 0-based inclusive line index in page markdown
    line_end: int                    # 0-based exclusive
    original_text: str               # the text we will replace
    kind: Literal["empty_cells", "image_no_table"]
    image_bbox: tuple[float, float, float, float] | None = None


def _empty_cell_ratio(table_text: str) -> tuple[float, int, int]:
    """Return (ratio, total_data_cells, empty_data_cells) for a markdown table block.

    - Counts only rows that start (after strip) with '|'.
    - Skips the header row (first such row) and the separator row (contains '---').
    - Treats whitespace-only cells between pipes as empty.
    - Returns (0.0, 0, 0) if fewer than 2 data rows exist.
    """
    rows = [
        ln.strip() for ln in table_text.splitlines()
        if ln.strip().startswith("|")
    ]
    if len(rows) < 3:  # need header + separator + >=1 data row
        return 0.0, 0, 0

    # Drop header (rows[0]) and separator (first row containing '---' after header).
    data_rows: list[str] = []
    seen_sep = False
    for r in rows[1:]:
        if not seen_sep and "---" in r:
            seen_sep = True
            continue
        data_rows.append(r)
    if not data_rows:
        return 0.0, 0, 0

    total = 0
    empty = 0
    for r in data_rows:
        # Split and drop the leading/trailing empty strings from outer pipes.
        parts = [p for p in r.split("|")]
        if parts and parts[0] == "":
            parts = parts[1:]
        if parts and parts[-1] == "":
            parts = parts[:-1]
        # Skip the row label (first cell — usually "FY2022" etc). Data cells are the rest.
        data_cells = parts[1:]
        for c in data_cells:
            total += 1
            if c.strip() == "":
                empty += 1
    if total == 0:
        return 0.0, 0, 0
    return empty / total, total, empty
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_parser.py -k "empty_cell_ratio or chart_region_dataclass" -v
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC"
git add backend/app/parser/pdf.py backend/tests/test_parser.py
git commit -m "feat(parser): add ChartRegion and empty-cell-ratio helper"
```

---

## Task 2: Detect chart regions inside page markdown (`_find_chart_regions`)

**Files:**
- Modify: `backend/app/parser/pdf.py` — add `_find_chart_regions` (signature 1 only)
- Modify: `backend/tests/test_parser.py` — add region-splitting tests

**Design note:** Signature 1 works at the **table block** level, not page level. A page with one real table and one empty-cell table must flag only the empty-cell table. This reuses `_split_into_blocks` (already in `pdf.py`) to find contiguous table blocks, then applies `_empty_cell_ratio` to each.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_parser.py`:

```python
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
    # The sliced region text must contain the empty-cell table only.
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
    # Only the second table (all-empty) must be flagged.
    assert len(regions) == 1
    assert "| Net Income |" in regions[0].original_text
    assert "27" not in regions[0].original_text
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_parser.py -k "find_chart_regions" -v
```

Expected: `ImportError: cannot import name '_find_chart_regions'`.

- [ ] **Step 3: Implement `_find_chart_regions`**

Add after `_empty_cell_ratio` in `pdf.py`:

```python
def _find_chart_regions(page: Page) -> list[ChartRegion]:
    """Scan a page's markdown for table blocks with >=30% empty data cells.

    Signature 1 — empty-cell tables. Signature 2 (image-without-table) is
    handled separately in `_detect_chart_pages` because it requires fitz
    image metadata from the renderer.
    """
    if "|" not in page.markdown:
        return []

    lines = page.markdown.splitlines()
    regions: list[ChartRegion] = []
    chart_index = 0

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped.startswith("|"):
            i += 1
            continue
        # Found the start of a table block; extend while lines stay table-like.
        start = i
        while i < len(lines) and lines[i].strip().startswith("|"):
            i += 1
        end = i  # exclusive
        block_text = "\n".join(lines[start:end]) + "\n"

        ratio, total, _empty = _empty_cell_ratio(block_text)
        if total > 0 and ratio >= EMPTY_CELL_RATIO_THRESHOLD:
            regions.append(ChartRegion(
                page_no=page.page_no,
                chart_index=chart_index,
                line_start=start,
                line_end=end,
                original_text=block_text,
                kind="empty_cells",
                image_bbox=None,
            ))
            chart_index += 1

    return regions
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_parser.py -k "find_chart_regions" -v
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/parser/pdf.py backend/tests/test_parser.py
git commit -m "feat(parser): detect empty-cell table regions on a page"
```

---

## Task 3: Page-level detector with fitz-image signature (`_detect_chart_pages`)

**Files:**
- Modify: `backend/app/parser/pdf.py` — add `_detect_chart_pages`
- Modify: `backend/tests/test_parser.py` — add detector tests

**Design note:** This task also introduces the `page_image_counts: dict[int, int]` parallel map, which `parse_pdf` will populate when rendering pages. We intentionally do NOT extend the `pages_raw` tuple (which would force changes to `_extract_batch` and `_validate_table_pages`) — we keep chart-only state in a separate map.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_parser.py`:

```python
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
    # Insertion anchor points inside the page (line_start < line_end).
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_parser.py -k "detect_chart_pages" -v
```

Expected: `ImportError: cannot import name '_detect_chart_pages'`.

- [ ] **Step 3: Implement `_detect_chart_pages`**

Add after `_find_chart_regions` in `pdf.py`:

```python
def _detect_chart_pages(
    pages: list[Page],
    page_image_counts: dict[int, int],
) -> dict[int, list[ChartRegion]]:
    """Return pages that need chart-aware re-extraction, keyed by page_no.

    Signature 1 — any contiguous |-table block with >= EMPTY_CELL_RATIO_THRESHOLD
    empty data cells (handled by `_find_chart_regions`).
    Signature 2 — page has >= 1 fitz image AND page markdown has no '|' at all
    (chart was not turned into a table by the initial passes).
    """
    out: dict[int, list[ChartRegion]] = {}
    for p in pages:
        if p.failed:
            continue

        regions = _find_chart_regions(p)

        has_image = page_image_counts.get(p.page_no, 0) > 0
        has_any_table = "|" in p.markdown
        if has_image and not has_any_table:
            # Anchor: end of page markdown (append). Future refinement could map
            # fitz image y-coordinate to a specific insertion line.
            n_lines = len(p.markdown.splitlines())
            regions.append(ChartRegion(
                page_no=p.page_no,
                chart_index=len(regions),
                line_start=n_lines,
                line_end=n_lines,
                original_text="",
                kind="image_no_table",
                image_bbox=None,
            ))

        if regions:
            out[p.page_no] = regions

    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_parser.py -k "detect_chart_pages" -v
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/parser/pdf.py backend/tests/test_parser.py
git commit -m "feat(parser): detect chart pages via empty-cell and image-without-table signatures"
```

---

## Task 4: Splice chart blocks into page markdown (`_splice_chart_blocks`)

**Files:**
- Modify: `backend/app/parser/pdf.py` — add `_splice_chart_blocks`
- Modify: `backend/tests/test_parser.py` — add splice tests

**Why this before Pass C1/C2:** Splice is pure (no LLM). Building it now lets us write and verify the two LLM passes against a working in-place rewrite function, without having to mock it later.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_parser.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_parser.py -k "splice" -v
```

Expected: `ImportError: cannot import name '_splice_chart_blocks'`.

- [ ] **Step 3: Implement `_splice_chart_blocks`**

Add to `pdf.py` after `_detect_chart_pages`:

```python
def _splice_chart_blocks(
    pages: list[Page],
    regions_by_page: dict[int, list[ChartRegion]],
    verified_blocks: dict[tuple[int, int], str],
) -> list[Page]:
    """Replace each detected chart region with its verified block.

    Regions missing from `verified_blocks` are left untouched (no regression).
    Multiple regions on the same page are applied bottom-up so line indices stay valid.
    """
    out: list[Page] = []
    for p in pages:
        regions = regions_by_page.get(p.page_no, [])
        if not regions:
            out.append(p)
            continue

        lines = p.markdown.splitlines(keepends=True)
        # Sort descending by line_start so indices remain valid as we mutate.
        for region in sorted(regions, key=lambda r: r.line_start, reverse=True):
            block = verified_blocks.get((p.page_no, region.chart_index))
            if block is None:
                continue
            block_lines = block.splitlines(keepends=True)
            if block_lines and not block_lines[-1].endswith("\n"):
                block_lines[-1] = block_lines[-1] + "\n"
            lines[region.line_start:region.line_end] = block_lines

        new_md = "".join(lines)
        out.append(p.model_copy(update={"markdown": new_md}))
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_parser.py -k "splice" -v
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/parser/pdf.py backend/tests/test_parser.py
git commit -m "feat(parser): splice chart blocks into page markdown in place"
```

---

## Task 5: `CHART_EXTRACT_SYSTEM` prompt and `_extract_charts` (Pass C1)

**Files:**
- Modify: `backend/app/parser/pdf.py` — add prompt constant and Pass C1 function
- Modify: `backend/tests/test_parser.py` — add C1 tests

**Why a separate LLM function:** Matches the existing pattern in `_extract_batch` (direct call to `llm.client.chat.completions.create`). Each chart page gets ONE call with all its detected regions so the model sees the full page context but is instructed to emit `n_regions` chart blocks.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_parser.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_parser.py -k "extract_charts or chart_extract_system" -v
```

Expected: `ImportError: cannot import name '_extract_charts'`.

- [ ] **Step 3: Add the `CHART_EXTRACT_SYSTEM` prompt**

Add after the existing `TABLE_VALIDATE_SYSTEM` constant in `pdf.py`:

```python
# ── Chart extraction prompt (Pass C1) ────────────────────────────────────────
CHART_EXTRACT_SYSTEM = (
    "You are a chart-and-graph-to-markdown extractor.\n"
    "This page contains one or more charts or graphs. The embedded PDF text "
    "does NOT carry the numeric data values — the values are encoded in the "
    "chart image (bar heights, line points, pie slice angles, etc.).\n"
    "Read every data point directly from the page image at 200 DPI.\n\n"

    "━━ COMPLETENESS RULES (hard guarantees) ━━\n\n"
    "  1. You MUST include every visible data point. Count the bars (or line "
    "points, or pie slices) in the image and produce the same count of rows "
    "(or pie entries) in the data table.\n"
    "  2. You MUST include every series shown in the legend. Count the legend "
    "entries and produce the same count of columns in the data table.\n"
    "  3. You MUST include every x-axis tick that carries a data point.\n"
    "  4. If you are uncertain about a value, still include the data point "
    "with your best visual reading — never omit it.\n\n"

    "━━ ACCURACY RULES ━━\n\n"
    "  5. Identify the minor tick increment on the y-axis (e.g., 50 units).\n"
    "  6. Read each bar height or line point by interpolating between ticks. "
    "If a value falls exactly on a tick, use that tick value.\n"
    "  7. Preserve the axis unit. If y-axis label says '$ in billions', the "
    "data table header must say '($B)' or similar.\n"
    "  8. When x-axis values are dates / fiscal years, preserve the exact "
    "formatting as printed on the axis.\n\n"

    "━━ OUTPUT FORMAT — one block per chart, in this exact order ━━\n\n"
    "  `### <chart title as printed on the page>`\n"
    "  `**Chart type:** <grouped bar / stacked bar / line / area / pie / scatter / etc.>`\n"
    "  `**X-axis:** <label> (<range>, <tick unit>)`\n"
    "  `**Y-axis:** <label> (<range>, <tick unit>)`\n"
    "  `**Series:** <comma-separated series names from the legend>`\n"
    "  A markdown data table with one column for the x-axis label and one "
    "column per series. EVERY cell must be filled.\n"
    "  `**Year-over-year changes:**` — per-series absolute and % delta list "
    "(only when x-axis is time-like).\n"
    "  `**CAGR (<start>–<end>):**` — per-series compound annual growth rate "
    "(only when x-axis is time-like with >= 2 periods).\n"
    "  `**Min / Max:**` — per-series minimum and maximum with their x-axis "
    "positions.\n"
    "  `**Series comparison:**` — 1–3 sentences on key cross-series "
    "relationships.\n"
    "  `**Trend:**` — 2–4 sentence paragraph.\n"
    "  `**Key observations:**` — 3–6 bullets.\n"
    "  `**Anomalies / inflection points:**` — callouts or the literal text "
    "'None observed.'\n\n"

    "Return ONLY valid JSON — no markdown fences, no explanation:\n"
    '[{"page_no": <int>, "chart_index": <int starting at 0>, '
    '"markdown": "<complete chart block>"}]'
)
```

- [ ] **Step 4: Implement `_extract_charts`**

Add after the prompt constant:

```python
async def _extract_charts(
    regions_by_page: dict[int, list[ChartRegion]],
    pages_raw: list[tuple[int, str, float, float, str]],
) -> dict[tuple[int, int], str]:
    """Pass C1 — read chart data directly from the page image.

    Returns {(page_no, chart_index): markdown_block}. On any failure for a
    given page, that page's entries are simply absent — the caller leaves the
    original markdown untouched (no regression).
    """
    if not regions_by_page:
        return {}

    raw_by_pno = {pno: (b64, fitz_text) for pno, b64, _, _, fitz_text in pages_raw}

    async def _run_one(page_no: int, regions: list[ChartRegion]) -> dict[tuple[int, int], str]:
        raw = raw_by_pno.get(page_no)
        if raw is None:
            return {}
        b64, fitz_text = raw

        # Build a user message describing what the first-pass saw for each region.
        region_descriptions = []
        for r in regions:
            if r.kind == "empty_cells":
                region_descriptions.append(
                    f"Chart {r.chart_index}: the first-pass emitted the "
                    f"following table with empty data cells — re-read the "
                    f"chart image to fill the values:\n{r.original_text}"
                )
            else:
                region_descriptions.append(
                    f"Chart {r.chart_index}: the first-pass omitted this "
                    f"chart entirely — extract the full chart block from the "
                    f"page image."
                )
        regions_text = "\n\n".join(region_descriptions)

        content: list[dict] = [
            {"type": "text", "text": f"Page {page_no} — {len(regions)} chart(s) to extract."},
            {"type": "text", "text": regions_text},
        ]
        if fitz_text:
            content.append({
                "type": "text",
                "text": (
                    f"[Embedded PDF text for page {page_no} — use for axis "
                    f"labels and legend names, NOT for numeric values]\n"
                    f"{fitz_text}\n[End embedded text]"
                ),
            })
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })

        try:
            resp = await llm.client.chat.completions.create(
                model=llm.deployment,
                temperature=0.0,
                max_tokens=6000,
                messages=[
                    {"role": "system", "content": CHART_EXTRACT_SYSTEM},
                    {"role": "user", "content": content},
                ],
            )
            if resp.usage:
                llm._cost_tokens += resp.usage.total_tokens
            text = (resp.choices[0].message.content or "").strip()
            if text.startswith("```"):
                text = re.sub(r"^```[a-z]*\n?", "", text)
                text = re.sub(r"```\s*$", "", text.strip())
            parsed: list[dict] = json.loads(text)
            out: dict[tuple[int, int], str] = {}
            for item in parsed:
                pno = int(item.get("page_no", page_no))
                cidx = int(item.get("chart_index", 0))
                md = item.get("markdown") or ""
                if md.strip():
                    out[(pno, cidx)] = md
            log.info("parser.chart.c1_done", page=page_no, n_charts=len(out))
            return out
        except Exception as e:
            log.warning("parser.chart.c1_failed", page=page_no, error=str(e)[:300])
            return {}

    sem = asyncio.Semaphore(BATCH_CONCURRENCY)

    async def _guarded(page_no: int, regions: list[ChartRegion]):
        async with sem:
            return await _run_one(page_no, regions)

    results = await asyncio.gather(*(
        _guarded(pno, regs) for pno, regs in regions_by_page.items()
    ))

    merged: dict[tuple[int, int], str] = {}
    for r in results:
        merged.update(r)
    return merged
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_parser.py -k "extract_charts or chart_extract_system" -v
```

Expected: 5 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/parser/pdf.py backend/tests/test_parser.py
git commit -m "feat(parser): add CHART_EXTRACT_SYSTEM prompt and Pass C1"
```

---

## Task 6: `CHART_VERIFY_SYSTEM` prompt and `_verify_charts` (Pass C2)

**Files:**
- Modify: `backend/app/parser/pdf.py` — add prompt constant and Pass C2 function
- Modify: `backend/tests/test_parser.py` — add C2 tests

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_parser.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_parser.py -k "verify_charts or chart_verify_system" -v
```

Expected: `ImportError: cannot import name '_verify_charts'`.

- [ ] **Step 3: Add the `CHART_VERIFY_SYSTEM` prompt**

Add after `CHART_EXTRACT_SYSTEM` in `pdf.py`:

```python
# ── Chart verification prompt (Pass C2) ──────────────────────────────────────
CHART_VERIFY_SYSTEM = (
    "You are a chart-data verifier and corrector.\n"
    "You will receive a page image that contains one or more charts AND a "
    "first-pass markdown block describing each chart. Your job is to audit "
    "the block against the image and correct any mistakes.\n\n"

    "━━ VALUE VERIFICATION (per data point) ━━\n\n"
    "  1. For EACH cell in each data table, re-read the corresponding bar "
    "(or line point, or pie slice) from the image INDEPENDENTLY — do not "
    "anchor on the first-pass value.\n"
    "  2. Identify the minor tick increment on the y-axis.\n"
    "  3. If your independent re-read differs from the first-pass value by "
    "more than one minor tick, correct the value to match your re-read.\n\n"

    "━━ COMPLETENESS VERIFICATION ━━\n\n"
    "  4. Count the bars or points visible in the image. Count the data rows "
    "in the table. If the image has more data points than the table, ADD the "
    "missing rows.\n"
    "  5. Count the series in the legend. Count the data columns in the "
    "table (excluding the x-axis column). If the legend has more series than "
    "the table, ADD the missing columns.\n\n"

    "━━ DERIVED METRIC REFRESH ━━\n\n"
    "  6. After any corrections to the data table, recompute YoY changes, "
    "CAGR, min/max, series comparison, trend, and key observations from the "
    "corrected table. Replace any stale derived values.\n\n"

    "Return ONLY valid JSON — no markdown fences, no explanation. "
    "Return the COMPLETE corrected block (same output format as the input):\n"
    '[{"page_no": <int>, "chart_index": <int>, "markdown": "<corrected block>"}]'
)
```

- [ ] **Step 4: Implement `_verify_charts`**

Add after the prompt constant:

```python
async def _verify_charts(
    c1_blocks: dict[tuple[int, int], str],
    pages_raw: list[tuple[int, str, float, float, str]],
) -> dict[tuple[int, int], str]:
    """Pass C2 — re-read each chart and correct mistakes.

    Returns a dict with the same keys as `c1_blocks`. On failure for any
    page, the C1 block is carried through unchanged (no regression).
    """
    if not c1_blocks:
        return {}

    raw_by_pno = {pno: b64 for pno, b64, _, _, _ in pages_raw}
    # Group C1 blocks by page.
    by_page: dict[int, list[tuple[int, str]]] = {}
    for (pno, cidx), md in c1_blocks.items():
        by_page.setdefault(pno, []).append((cidx, md))

    async def _run_one(page_no: int, charts: list[tuple[int, str]]) -> dict[tuple[int, int], str]:
        b64 = raw_by_pno.get(page_no)
        if b64 is None:
            # No image to verify against — carry through.
            return {(page_no, cidx): md for cidx, md in charts}

        content: list[dict] = [
            {"type": "text", "text": f"Page {page_no} — verify {len(charts)} chart block(s)."},
        ]
        for cidx, md in charts:
            content.append({
                "type": "text",
                "text": f"[Chart {cidx} — first-pass block to verify]\n{md}\n[End chart {cidx}]",
            })
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })

        try:
            resp = await llm.client.chat.completions.create(
                model=llm.deployment,
                temperature=0.0,
                max_tokens=6000,
                messages=[
                    {"role": "system", "content": CHART_VERIFY_SYSTEM},
                    {"role": "user", "content": content},
                ],
            )
            if resp.usage:
                llm._cost_tokens += resp.usage.total_tokens
            text = (resp.choices[0].message.content or "").strip()
            if text.startswith("```"):
                text = re.sub(r"^```[a-z]*\n?", "", text)
                text = re.sub(r"```\s*$", "", text.strip())
            parsed: list[dict] = json.loads(text)
            corrected: dict[tuple[int, int], str] = {}
            for item in parsed:
                pno = int(item.get("page_no", page_no))
                cidx = int(item.get("chart_index", 0))
                md = item.get("markdown") or ""
                if md.strip():
                    corrected[(pno, cidx)] = md
            # Any chart we failed to verify carries through its C1 block.
            out: dict[tuple[int, int], str] = {}
            for cidx, md in charts:
                key = (page_no, cidx)
                out[key] = corrected.get(key, md)
            log.info(
                "parser.chart.c2_done",
                page=page_no,
                n_charts=len(charts),
                n_corrected=sum(1 for (_, cidx), m in corrected.items() if m != dict(charts).get(cidx)),
            )
            return out
        except Exception as e:
            log.warning("parser.chart.c2_failed", page=page_no, error=str(e)[:300])
            return {(page_no, cidx): md for cidx, md in charts}

    sem = asyncio.Semaphore(BATCH_CONCURRENCY)

    async def _guarded(page_no: int, charts: list[tuple[int, str]]):
        async with sem:
            return await _run_one(page_no, charts)

    results = await asyncio.gather(*(
        _guarded(pno, charts) for pno, charts in by_page.items()
    ))
    merged: dict[tuple[int, int], str] = {}
    for r in results:
        merged.update(r)
    return merged
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_parser.py -k "verify_charts or chart_verify_system" -v
```

Expected: 4 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/parser/pdf.py backend/tests/test_parser.py
git commit -m "feat(parser): add CHART_VERIFY_SYSTEM prompt and Pass C2"
```

---

## Task 7: Wire chart passes into `parse_pdf`

**Files:**
- Modify: `backend/app/parser/pdf.py` — extend `parse_pdf` with the four new steps
- Modify: `backend/tests/test_parser.py` — add end-to-end test

**Design note:** We populate `page_image_counts` in the same loop that renders pages. The `mu.close()` call in `parse_pdf` happens AFTER we've already captured all the info we need.

- [ ] **Step 1: Write the failing end-to-end test**

Append to `backend/tests/test_parser.py`:

```python
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
        resp = _mock_llm_response(response_for(idx))
        return resp

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
    """Text-only page must NOT trigger C1/C2 — only 2 LLM calls total."""
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
        # Pass A returns clean prose; Pass B is skipped (no pipes in markdown).
        return _mock_llm_response(_json.dumps([{
            "page_no": 1,
            "markdown": "## Section One\n\nPure prose, no chart.\n",
        }]))
    monkeypatch.setattr(pdf_mod.llm.client.chat.completions, "create", fake_create)

    result = await parse_pdf(pdf_path)
    # Only Pass A fires — no '|' in markdown means Pass B skips, detector finds nothing.
    assert calls["n"] == 1
    assert "Pure prose" in result.pages[0].markdown
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && python -m pytest tests/test_parser.py::test_parse_pdf_end_to_end_with_chart_page -v
```

Expected: the chart block is not in the output because the C1/C2 pipeline is not yet wired.

- [ ] **Step 3: Wire the new steps into `parse_pdf`**

In `backend/app/parser/pdf.py`, find the existing `parse_pdf` function (around line 350). Make two edits:

**Edit A — capture `page_image_counts` during page render.** Replace the render loop (currently lines 364–373) with:

```python
    pages_raw: list[tuple[int, str, float, float, str]] = []
    page_image_counts: dict[int, int] = {}
    for i in range(total):
        b64, w, h, fitz_text = _render_page(mu[i])
        pages_raw.append((i + 1, b64, w, h, fitz_text))
        page_image_counts[i + 1] = len(mu[i].get_images(full=True))
        if save_images_dir is not None:
            save_images_dir.mkdir(parents=True, exist_ok=True)
            img_path = save_images_dir / f"{i + 1:03d}.png"
            if not img_path.exists():
                img_path.write_bytes(base64.b64decode(b64))
    mu.close()
```

**Edit B — append chart passes.** Find the line `pages = await _validate_table_pages(pages, pages_raw)` (currently line 396). After that line (and BEFORE `sections = _detect_sections(pages)` on line 398), insert:

```python
    # ── Chart-aware pipeline (Passes C1 + C2) ────────────────────────────
    regions_by_page = _detect_chart_pages(pages, page_image_counts)
    if regions_by_page:
        log.info(
            "parser.chart.detected",
            pages=list(regions_by_page.keys()),
            total_regions=sum(len(v) for v in regions_by_page.values()),
        )
        c1_blocks = await _extract_charts(regions_by_page, pages_raw)
        verified = await _verify_charts(c1_blocks, pages_raw)
        pages = _splice_chart_blocks(pages, regions_by_page, verified)
        log.info("parser.chart.spliced", n_blocks=len(verified))
```

- [ ] **Step 4: Run the end-to-end tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_parser.py::test_parse_pdf_end_to_end_with_chart_page tests/test_parser.py::test_parse_pdf_text_only_page_no_chart_passes -v
```

Expected: both tests pass.

- [ ] **Step 5: Run the full parser test suite to confirm no regressions**

```bash
cd backend && python -m pytest tests/test_parser.py -v
```

Expected: all tests pass. If the pre-existing `test_parse_tiny` still passes, we are good.

- [ ] **Step 6: Commit**

```bash
git add backend/app/parser/pdf.py backend/tests/test_parser.py
git commit -m "feat(parser): wire chart-aware passes into parse_pdf"
```

---

## Task 8: Manual verification against the NVIDIA excerpt

**Files:** none (manual verification only)

This step is a live sanity check. It is not automated because it hits Azure OpenAI and the cost is non-trivial.

- [ ] **Step 1: Confirm Azure creds are set**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC/backend"
python -c "from app.settings import settings; print('OK' if settings.azure_openai_api_key else 'MISSING')"
```

Expected: `OK`.

- [ ] **Step 2: Run the parser on the NVIDIA excerpt**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC/backend"
python - <<'PY'
import asyncio
from pathlib import Path
from app.parser.pdf import parse_pdf

async def main():
    doc = await parse_pdf(Path("../samples/NVIDIA_FY2026_10K_Excerpt.pdf"))
    for p in doc.pages:
        if p.page_no in (3, 6):
            print(f"--- page {p.page_no} ---")
            print(p.markdown)
            print()

asyncio.run(main())
PY
```

- [ ] **Step 3: Verify the expected content**

For page 3 (Financial Highlights with grouped bar + gross margin charts):
- The output must contain `### ` chart headings for both charts.
- Every `(year, series)` cell must be non-empty (no `|  |` patterns).
- The `**Trend:**`, `**Key observations:**`, and derived-metric sections must be present.

For page 6 (5-year cumulative return line chart):
- The output must contain a data table with at least six x-axis dates (`1/31/2021`, `1/30/2022`, `1/29/2023`, `1/28/2024`, `1/26/2025`, `1/25/2026`).
- The table must have columns for all three series: `NVIDIA Corporation`, `S&P 500`, `Nasdaq 100`.

If any of the above is missing, file an issue with the page's raw C1 and C2 output (look in logs for `parser.chart.c1_done` / `parser.chart.c2_done`) — the prompt likely needs tightening for the specific failure mode observed.

- [ ] **Step 4: No commit needed** — this task produces no code changes.

---

## Spec coverage summary

| Spec section | Task(s) | Status |
|---|---|---|
| Detection — empty-cell signature | 1, 2, 3 | Covered |
| Detection — image-without-table signature | 3 | Covered |
| Pass C1 prompt + call | 5 | Covered |
| Pass C2 prompt + call | 6 | Covered |
| Splice (in-place, reverse-order, signature-2 insert) | 4 | Covered |
| `parse_pdf` pipeline wiring | 7 | Covered |
| Error handling (C1/C2 fallbacks, no-regression) | 5, 6, 7 | Covered |
| Observability (`parser.chart.*` log events) | 5, 6, 7 | Covered |
| Zero schema changes | all | Enforced — no edits to `schema.py` |
| NVIDIA 10-K integration check | 8 | Covered (manual) |

Spec tests list (8 items) maps to automated tests as follows:

1. Detector: empty-cell signature → Task 3 `test_detect_chart_pages_empty_cell_signature` (+ Task 2 unit tests).
2. Detector: image-without-table signature → Task 3 `test_detect_chart_pages_image_without_table_signature`.
3. Detector: normal doc → Task 3 `test_detect_chart_pages_no_image_no_table_not_flagged`.
4. Splice: in-place replacement → Task 4 `test_splice_replaces_empty_cell_region_in_place`.
5. Splice: reverse order for multi-region → Task 4 `test_splice_multiple_regions_reverse_order_safe`.
6. C1 failure fallthrough → Task 5 `test_extract_charts_returns_empty_on_api_error` + Task 7 end-to-end.
7. C2 failure fallthrough → Task 6 `test_verify_charts_falls_back_to_c1_on_failure`.
8. Integration: NVIDIA 10-K → Task 8 (manual verification).
