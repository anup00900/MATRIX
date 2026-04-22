# Chart-aware PDF extraction — design

**Date:** 2026-04-22
**Author:** anup.roy
**Status:** Draft (awaiting implementation plan)
**Scope:** `backend/app/parser/pdf.py`

## Problem

When a PDF page contains a chart rendered as an embedded image (bar chart, line chart, pie chart, scatter, etc.), the current ingestion pipeline emits markdown with empty data cells or omits the chart entirely.

Two observed failure modes on the NVIDIA FY2026 10-K excerpt:

1. **Empty-cell skeleton** (page 3, "Financial Highlights" — grouped bar chart of Revenue vs Net Income, and bar chart of Gross Margin %). The extraction produced correct headers and row labels (`FY2022`, `FY2023`, …) but every data cell came out as `|  |`.
2. **Chart omitted entirely** (page 6, "Selected Financial Chart" — line chart comparing NVIDIA vs S&P 500 vs Nasdaq 100 over 5 years). The extracted markdown kept only the page title, the intro sentence, and the source footnote. No table. No data.

## Root cause

In `backend/app/parser/pdf.py`:

- `_render_page` (lines 88–98) renders each page at 200 DPI and separately extracts embedded PDF text via `fitz.get_text("text")`. For charts, embedded text contains the title, axis labels, legend, and footnote — but not the bar heights / line points (those are vector/raster graphics, no underlying text).
- `BATCH_SYSTEM` (lines 19–51) instructs GPT-4.1:
  - Rule 4: *"Numbers: verbatim from embedded text."*
  - Rule 2: *"Use an empty cell `| |` for merged/blank cells. Never omit a column."*
- The model follows the prompt literally: it builds the correct table skeleton from text it can see (years, series names) and leaves data cells blank because the numeric values are not in the embedded text.
- `TABLE_VALIDATE_SYSTEM` (lines 54–79) cross-checks cells against embedded text — also cannot rescue chart values for the same reason.

This is a prompt/pipeline design limitation, not a model failure. Vision is explicitly disallowed as a source for numeric values.

## Goals

1. When a page contains a chart, the extracted markdown must contain every data point visible in the chart, with accuracy driven by a dedicated two-pass verification.
2. The markdown block for a chart must be verbose and standalone — someone reading it next to the page image should gain information they would otherwise miss looking at just the chart.
3. No regression on text-only documents. The existing two-pass pipeline (Pass A + Pass B) is untouched and continues to run exactly as it does today.
4. No schema changes. `StructuredDoc`, `Page`, `Section`, `Chunk` remain byte-compatible with the current code.
5. Chart values appear as first-class numbers in the markdown — no `~`, no `*`, no footnotes, no inline "read from chart" annotations. When rendered side-by-side with the page image, the markdown reads as a clean authoritative rendering.

## Non-goals

- Handling non-chart images (logos, product photos, headshots, diagrams). Those remain untouched.
- Extracting structure from scanned documents (OCR fallback). Out of scope.
- Changing chunking, section detection, retrieval, or synthesis.
- Changing the model (we continue to use `gpt-4.1` via `llm.deployment`).

## Design — "Overlay" approach

Four new steps are appended to `parse_pdf`, running after the existing Pass A (`_extract_batch`) and Pass B (`_validate_table_pages`). They are gated by a detector that fires only on pages showing the chart-extraction failure signature, so text-only documents bypass the new machinery entirely.

### Pipeline

```
parse_pdf()
 ├─ for each page: _render_page  → (b64, fitz_text)               [UNCHANGED]
 ├─ Pass A:  _extract_batch       → Page.markdown v1              [UNCHANGED]
 ├─ Pass B:  _validate_table_pages → Page.markdown v2             [UNCHANGED]
 │
 ├─ NEW:  _detect_chart_pages(pages, pages_raw)
 │          → {page_no: [ChartRegion, ...]}
 │
 ├─ NEW:  _extract_charts(chart_pages, pages_raw)      ← Pass C1
 │          → {(page_no, chart_index): ChartBlock}
 │
 ├─ NEW:  _verify_charts(c1_blocks, pages_raw)         ← Pass C2
 │          → {(page_no, chart_index): ChartBlock}
 │
 ├─ NEW:  _splice_chart_blocks(pages, regions, verified_blocks)
 │          → pages with chart regions replaced in place
 │
 ├─ _detect_sections(pages)                                       [UNCHANGED]
 └─ _chunk_text()                                                 [UNCHANGED]
```

### Step 1 — Detection (`_detect_chart_pages`)

Input: `list[Page]` from Pass B, plus `pages_raw` to access fitz image metadata.

For each page, mark it as chart-bearing if EITHER:

- **Signature 1 — empty-cell table.** The page markdown contains a contiguous `|`-block where `empty_data_cells / total_data_cells >= 0.30`. "Data cells" excludes the header row and the separator row. "Empty" means the cell is whitespace-only after stripping.
- **Signature 2 — image with no table.** `fitz.Page.get_images(full=True)` returns at least one image on the page AND the page markdown contains no `|` character at all.

Multiple chart regions per page are supported. A `ChartRegion` records:

```python
@dataclass
class ChartRegion:
    page_no: int
    chart_index: int          # 0-based within the page
    line_start: int           # 0-based line index in page markdown
    line_end: int             # exclusive
    original_text: str        # the region we will replace
    kind: Literal["empty_cells", "image_no_table"]
    image_bbox: tuple[float, float, float, float] | None
                              # from fitz get_image_rects; used for insertion anchor in Signature 2
```

For Signature 2 (no table emitted), `line_start`/`line_end` point to the insertion position — defaulting to end-of-page markdown but preferring the position right after the caption/title associated with the image (best-effort heuristic: the nearest heading line whose y-coordinate in the rendered page is immediately above the image bbox; if ambiguous, append at end-of-page).

### Step 2 — Pass C1: chart extraction (`_extract_charts`)

For each page that has at least one chart region, send a dedicated call to GPT-4.1 with:

- The full page image (base64 PNG, same 200 DPI render that Pass A used).
- The embedded fitz text (useful for reading axis labels and legends even though not data values).
- A description of how many charts were detected and what they appear to be (from Signature 1 we already have the row/column labels the model extracted).

Prompt (`CHART_EXTRACT_SYSTEM`) encodes:

- **Ground truth inversion:** "This page contains one or more charts or graphs. Embedded PDF text does NOT carry the numeric data values. Read every data point directly from the page image."
- **Completeness (hard rule):** "You MUST include every visible data point. You MUST include every series shown in the legend. You MUST include every tick mark on the x-axis that has an associated data value. If you are uncertain about a value, still include the data point with your best visual reading — never omit it."
- **Accuracy rules:** "Identify the minor tick increment on the y-axis. Read each bar height or line point by interpolating between ticks. Preserve the axis unit (e.g., `$ billions`, `%`). If a value falls exactly on a tick, use that tick value."
- **Output format (C-format):** for each chart, emit a markdown block containing in order:
  - `### <chart title as printed>`
  - `**Chart type:** <grouped bar / stacked bar / line / area / pie / scatter / etc.>`
  - `**X-axis:** <label> (<range>, <tick unit>)`
  - `**Y-axis:** <label> (<range>, <tick unit>)`
  - `**Series:** <comma-separated series names from the legend>`
  - A markdown data table with one column per series and one row per x-axis point. Every cell must be filled.
  - `**Year-over-year changes:**` — per-series list of absolute and percentage YoY deltas (only when x-axis is time-like).
  - `**CAGR (<start>–<end>):**` — per-series compound annual growth rate when applicable.
  - `**Min / Max:**` — per-series minimum and maximum values with their x-axis positions.
  - `**Series comparison:**` — key cross-series relationships (e.g., "Revenue exceeds Net Income in every period; the gap widens over time").
  - `**Trend:**` — 2–4 sentence paragraph.
  - `**Key observations:**` — 3–6 bullets.
  - `**Anomalies / inflection points:**` — callouts or "None observed."
- **Return shape:** `[{page_no, chart_index, region_marker, markdown}, ...]` as JSON, no fences.

Call config: `temperature=0.0`, `max_tokens=6000`, one page per call (effective `BATCH_SIZE=1`) to maximize per-chart attention. Concurrency reuses the existing semaphore pattern.

### Step 3 — Pass C2: chart verification (`_verify_charts`)

For each chart produced by Pass C1, send a follow-up call with:

- The same page image.
- The C1-generated chart block as the subject of verification.

Prompt (`CHART_VERIFY_SYSTEM`) encodes:

- **Per-value re-read:** "For EACH data point in the data table, independently re-read the corresponding bar or point from the image. If your re-read differs from the table value by more than one minor tick, correct the value."
- **Completeness re-check:** "Count the bars or points visible in the image. Count the rows in the data table. If the image has more data points than the table, add them. Do the same for series — if the legend shows more series than the table's columns, add the missing columns."
- **Recompute derived metrics:** "After any corrections to the data table, recompute YoY changes, CAGR, min/max, and series comparison. Correct any stale derived values."
- **Return shape:** same JSON as C1, with corrected `markdown`.

Call config: `temperature=0.0`, `max_tokens=6000`, one chart per call.

### Step 4 — Splice (`_splice_chart_blocks`)

For each chart region:

- **Signature 1 (empty-cell table):** replace lines `[line_start, line_end)` in the page markdown with the verified chart block.
- **Signature 2 (image with no table):** insert the verified chart block at the computed anchor line.

Preserve one blank line before and after the inserted block. All other lines in `Page.markdown` — headings, prose, real tables, footnotes — remain byte-identical.

Multiple regions per page are applied in reverse order (bottom-up) so line indices stay valid during splicing.

## Error handling

- **C1 JSON parse failure / API error** — skip chart passes for that page; keep the existing (Pass B) markdown. Zero regression vs today's behavior.
- **C2 JSON parse failure / API error** — splice C1's output. Log a warning; the page is still strictly better than today.
- **C1 returns fewer chart blocks than regions detected** — splice the ones we have; leave unmatched regions unchanged. Log a warning with region counts.
- **C1 returns more chart blocks than regions detected** — trust C1 (it may have seen a chart the detector missed). Append the extras at end-of-page.
- **`Page.failed`** stays false if Pass A succeeded. A chart-pass failure does not fail the page.
- **Cost containment** — if a pathological doc has >20 chart pages, log a `parser.chart.high_volume` warning. No hard cap for the POC.

## Observability

New log events (via existing `..logging.log`):

- `parser.chart.detected` — fields: `page_no`, `n_regions`, `kinds` (list).
- `parser.chart.c1_done` — fields: `page_no`, `n_charts`, `tokens`.
- `parser.chart.c2_corrections` — fields: `page_no`, `chart_index`, `n_values_changed`, `n_points_added`, `n_series_added`. This event directly measures how often C2 catches a miss, which is the success metric for the "no missing information" guarantee.
- `parser.chart.spliced` — fields: `page_no`, `n_regions_replaced`.
- `parser.chart.skipped` — fields: `page_no`, `reason`.

Token costs accumulate into the existing `llm._cost_tokens` counter.

## Performance

- Clean text-only documents: zero extra LLM calls. Detector returns empty; new pipeline steps no-op.
- Chart-bearing documents: 2 extra calls per chart page (C1 + C2). Each call is bounded by `max_tokens=6000`.
- End-to-end latency increase on an NVIDIA 10-K-like document (typically 2–4 chart pages): roughly 5–10 seconds added, parallelizable via the same semaphore pattern Pass A/B use.

## Testing

New unit tests (add to `backend/tests/test_parser.py`):

1. **Detector: empty-cell signature** — synthetic page markdown with a 6-row × 4-col table where 50% of data cells are empty → detected as one chart region.
2. **Detector: image-without-table signature** — fixture with fitz image present and no `|` in markdown → detected as one chart region.
3. **Detector: normal doc** — fixture page with a real fully-populated table → not detected.
4. **Splice: in-place replacement** — given a page with `heading + empty-cell-table + prose`, splicing preserves heading and prose byte-identically.
5. **Splice: reverse order for multi-region** — two regions on one page, line indices stay valid.
6. **C1 failure fallthrough** — mocked LLM raises → page markdown equals Pass B output.
7. **C2 failure fallthrough** — mocked C1 succeeds, C2 raises → spliced block equals C1 output.

Integration test:

8. Run `parse_pdf` against `samples/NVIDIA_FY2026_10K_Excerpt.pdf`. Assert that page 3's markdown contains non-empty numeric values for every (year × series) cell in the Revenue / Net Income / Gross Margin tables, and that page 6 contains a populated data table with at least the six x-axis dates (`1/31/2021` through `1/25/2026`) and all three series (`NVIDIA Corporation`, `S&P 500`, `Nasdaq 100`).

## Files changed

- `backend/app/parser/pdf.py` — add detector, C1 prompt constant, C2 prompt constant, `_extract_charts`, `_verify_charts`, `_splice_chart_blocks`, and the four new pipeline steps at the end of `parse_pdf`.
- `backend/tests/test_parser.py` — eight new tests per the list above.

No changes to `schema.py`, `services/ingest.py`, retriever, synthesizer, or any frontend code.

## Out of scope / deferred

- LLM-based chart detection (current design uses the B post-hoc detector; can upgrade to a classifier later if we see false negatives — charts whose first-pass markdown comes back non-empty but wrong).
- Cropping the chart region out of the page before sending to C1/C2. Current design sends the full page image; if chart accuracy on dense pages needs improvement, we can add bbox cropping later.
- Persisting a per-cell provenance flag (`source: chart_vision` vs `embedded_text`) in the schema. Explicitly ruled out during brainstorming — markdown values are first-class regardless of origin.
