from __future__ import annotations
import asyncio, base64, hashlib, io, json, re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
import fitz, tiktoken
from PIL import Image
from ulid import ULID
from ..llm import llm
from ..logging import log
from .schema import StructuredDoc, Page, Section, Chunk, Bbox, DocMeta

ENCODER = tiktoken.get_encoding("cl100k_base")
HEADING_RE = re.compile(r"^#{1,4}\s+(?P<title>.+)$")
ITEM_RE = re.compile(r"^(Item\s+\d+[A-Z]?\.?|Part\s+[IVX]+)", re.IGNORECASE)
BATCH_SIZE = 2          # 2 pages per call → more tokens available per page
BATCH_CONCURRENCY = 5
RENDER_DPI = 200        # sharp rendering for dense tables and small numbers

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
    - Treats the first cell of each data row as a row label and excludes it from
      the count. A 2-column table therefore has 1 data cell per row; a 1-column
      table has 0 data cells and will never be flagged.
    - Treats whitespace-only cells between pipes as empty.
    - Returns (0.0, 0, 0) if fewer than 2 data rows exist or no data cells remain
      after excluding row labels.
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
        parts = r.split("|")
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


def _splice_chart_blocks(
    pages: list[Page],
    regions_by_page: dict[int, list[ChartRegion]],
    verified_blocks: dict[tuple[int, int], str],
) -> list[Page]:
    """Replace each detected chart region with its verified block.

    Regions missing from `verified_blocks` are left untouched (no regression).
    Multiple regions on the same page are applied bottom-up so line indices stay valid.

    When `line_start > 0` and the preceding line lacks a trailing newline, this
    function adds one so the inserted chart block does not concatenate directly
    onto the previous line. This matters for signature-2 insertions at end-of-page
    when the source markdown did not end with a newline.
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
            # Ensure the line preceding the insertion point ends with '\n' so
            # the inserted block doesn't concatenate onto existing prose.
            if (
                region.line_start > 0
                and region.line_start <= len(lines)
                and lines[region.line_start - 1]
                and not lines[region.line_start - 1].endswith("\n")
            ):
                lines[region.line_start - 1] = lines[region.line_start - 1] + "\n"
            lines[region.line_start:region.line_end] = block_lines

        new_md = "".join(lines)
        out.append(p.model_copy(update={"markdown": new_md}))
    return out


# ── Extraction prompt ────────────────────────────────────────────────────────
BATCH_SYSTEM = (
    "You are a universal PDF page-to-markdown extractor. "
    "You handle any document type: fee schedules, financial statements, reports, contracts, etc.\n"
    "For each page you receive the page image AND the raw embedded PDF text.\n"
    "The embedded text is GROUND TRUTH for every number — copy values from it verbatim.\n"
    "The image shows visual layout: merged cells, multi-level headers, bold/colored highlights.\n\n"

    "━━ MANDATORY RULES ━━\n\n"

    "RULE 1 — FLATTEN multi-level headers into ONE header row.\n"
    "  If a table has 2 or more header rows, merge them into a single row:\n"
    "  - Join parent label + child label with ' / ' to form one column name.\n"
    "  - Example: parent='Revenue', children='Q1','Q2' → columns 'Revenue / Q1', 'Revenue / Q2'.\n"
    "  - The |---| separator appears EXACTLY ONCE, immediately after this merged header row.\n"
    "  - Never output more than one header row per table.\n\n"

    "RULE 2 — Every data row on EXACTLY ONE LINE. No wrapping.\n"
    "  - Every row must have the same column count as the header.\n"
    "  - Use an empty cell | | for merged/blank cells. Never omit a column.\n\n"

    "RULE 3 — Include EVERY row without exception.\n"
    "  Never skip, merge, or summarise rows.\n\n"

    "RULE 4 — Numbers: verbatim from embedded text.\n"
    "  - Preserve formatting: 1,000,000 not 1000000; 10% not 10; £50 not 50.\n"
    "  - Wrap bold / red / highlighted values in **: **280,000**\n\n"

    "RULE 5 — Non-table text: preserve as-is.\n"
    "  - Headings: #/##/###. Bullets, footnotes, notes: verbatim.\n\n"

    "Return ONLY valid JSON — no markdown fences, no explanation:\n"
    '[{"page_no": <int>, "markdown": "<complete page content>"}]'
)

# ── Validation / correction prompt ───────────────────────────────────────────
TABLE_VALIDATE_SYSTEM = (
    "You are a PDF table structure and accuracy auditor. "
    "Works on any document type — fee tables, financials, reports, etc.\n"
    "For each page you receive:\n"
    "  1. [Embedded text] — raw PDF text; GROUND TRUTH for all numbers.\n"
    "  2. [Extracted markdown] — first-pass output to audit and correct.\n"
    "  3. The page image.\n\n"

    "Audit and fix ALL issues, in this order:\n\n"

    "STRUCTURE (fix first):\n"
    "  A. Multi-row headers → flatten into ONE header row (parent / child label).\n"
    "  B. Wrapped rows → merge any data row split across multiple lines into ONE line.\n"
    "  C. Column count → every row must match the header's column count; add || for missing cells.\n"
    "  D. Separator → |---| appears exactly ONCE, directly after the header row.\n\n"

    "NUMBERS (fix after structure):\n"
    "  E. Cross-check every cell value against the embedded text; fix mismatches.\n"
    "  F. Preserve exact formatting: commas, % signs, currency symbols.\n"
    "  G. Keep ** ** bold markers on highlighted/colored values.\n\n"

    "Do NOT remove any rows, columns, or text content.\n"
    "Return the COMPLETE corrected page markdown.\n\n"
    "Return ONLY valid JSON:\n"
    '[{"page_no": <int>, "markdown": "<corrected page content>"}]'
)

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


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _render_page(page: "fitz.Page", dpi: int = RENDER_DPI) -> tuple[str, float, float, str]:
    """Render page to base64 PNG and also extract embedded text."""
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    # Extract embedded text — empty string for scanned pages
    raw_text = page.get_text("text").strip()
    return b64, float(page.rect.width), float(page.rect.height), raw_text


async def _extract_batch(
    pages_data: list[tuple[int, str, float, float, str]],
) -> list[Page]:
    """Send a batch of page images + embedded text to GPT-4.1 Vision."""
    page_nos = [pno for pno, *_ in pages_data]
    content: list[dict] = []
    for pno, b64, _, _, fitz_text in pages_data:
        content.append({"type": "text", "text": f"Page {pno}:"})
        if fitz_text:
            content.append({
                "type": "text",
                "text": (
                    f"[Embedded PDF text for page {pno} — use for exact numbers]\n"
                    f"{fitz_text}\n"
                    f"[End embedded text]"
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
            max_tokens=max(16000, BATCH_SIZE * 5000),
            messages=[
                {"role": "system", "content": BATCH_SYSTEM},
                {"role": "user", "content": content},
            ],
        )
        if resp.usage:
            llm._cost_tokens += resp.usage.total_tokens
        text = resp.choices[0].message.content or ""
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-z]*\n?", "", text)
            text = re.sub(r"```\s*$", "", text.strip())
        parsed: list[dict] = json.loads(text)
        result_map = {item["page_no"]: item.get("markdown", "") for item in parsed}
    except Exception as e:
        log.warning("parser.batch.failed", pages=page_nos, error=str(e)[:300])
        # Fallback: use fitz embedded text as markdown for failed pages
        result_map = {}
        for pno, _, _, _, fitz_text in pages_data:
            result_map[pno] = fitz_text if fitz_text else ""

    return [
        Page(
            page_no=pno,
            markdown=(result_map.get(pno) or "").strip(),
            width=w,
            height=h,
            failed=(pno not in result_map),
        )
        for pno, _, w, h, _ in pages_data
    ]


async def _validate_table_pages(
    pages: list[Page],
    pages_raw: list[tuple[int, str, float, float, str]],
) -> list[Page]:
    """Second pass: fix table structure (wrapped rows, multi-level headers) + numerical accuracy."""
    raw_by_pno = {pno: (b64, fitz_text) for pno, b64, _, _, fitz_text in pages_raw}
    # Only pages that have at least one table row
    table_pages = [p for p in pages if "|" in p.markdown and not p.failed]
    if not table_pages:
        return pages

    batches = [table_pages[i: i + BATCH_SIZE] for i in range(0, len(table_pages), BATCH_SIZE)]
    sem = asyncio.Semaphore(BATCH_CONCURRENCY)

    async def _validate_batch(batch: list[Page]) -> dict[int, str]:
        async with sem:
            content: list[dict] = []
            for p in batch:
                b64, fitz_text = raw_by_pno.get(p.page_no, ("", ""))
                content.append({"type": "text", "text": f"=== Page {p.page_no} ==="})
                if fitz_text:
                    content.append({"type": "text", "text": f"[Embedded text — ground truth]\n{fitz_text}\n[End embedded text]"})
                content.append({"type": "text", "text": f"[Extracted markdown to validate]\n{p.markdown}\n[End markdown]"})
                if b64:
                    content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
            try:
                resp = await llm.client.chat.completions.create(
                    model=llm.deployment,
                    temperature=0.0,
                    max_tokens=max(12000, len(batch) * 4000),
                    messages=[
                        {"role": "system", "content": TABLE_VALIDATE_SYSTEM},
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
                return {item["page_no"]: item.get("markdown", "") for item in parsed}
            except Exception as e:
                log.warning("parser.validate.failed", error=str(e)[:200])
                return {}

    results = await asyncio.gather(*(_validate_batch(b) for b in batches))
    corrections: dict[int, str] = {}
    for r in results:
        corrections.update(r)

    corrected: list[Page] = []
    for p in pages:
        if p.page_no in corrections and corrections[p.page_no].strip():
            corrected.append(p.model_copy(update={"markdown": corrections[p.page_no]}))
        else:
            corrected.append(p)
    log.info("parser.validate.done", table_pages=len(table_pages), corrected=len(corrections))
    return corrected


def _detect_sections(pages: list[Page]) -> list[Section]:
    """Heading-based section detection with page-level fallback for table-heavy docs."""
    sections = _detect_sections_headings(pages)
    if sections:
        return sections
    # No headings found (e.g. fee tables, single-page data sheets) —
    # fall back to one section per page so wiki/retriever still work.
    result: list[Section] = []
    for p in pages:
        if not p.markdown.strip():
            continue
        result.append(Section(
            id=str(ULID()),
            title=f"Page {p.page_no}",
            level=2,
            page_start=p.page_no,
            page_end=p.page_no,
            text=p.markdown,
        ))
    return result


def _detect_sections_headings(pages: list[Page]) -> list[Section]:
    sections: list[Section] = []
    cur_title: str | None = None
    cur_start = 1
    cur_text: list[str] = []
    for p in pages:
        for line in p.markdown.splitlines():
            ln = line.strip()
            m = HEADING_RE.match(ln)
            if not m:
                continue
            heading_text = m.group("title").strip()
            if ITEM_RE.match(heading_text) or ln.startswith("# "):
                if cur_title is not None:
                    sections.append(Section(
                        id=str(ULID()), title=cur_title, level=2,
                        page_start=cur_start,
                        page_end=max(cur_start, p.page_no - 1),
                        text="\n".join(cur_text),
                    ))
                cur_title = heading_text
                cur_start = p.page_no
                cur_text = []
        if cur_title is not None and p.markdown:
            cur_text.append(p.markdown)
    if cur_title is not None:
        sections.append(Section(
            id=str(ULID()), title=cur_title, level=2,
            page_start=cur_start, page_end=pages[-1].page_no,
            text="\n".join(cur_text),
        ))
    return sections


def _split_into_blocks(text: str) -> list[tuple[str, bool]]:
    """Split markdown text into (block_text, is_table) pairs.
    Table blocks are lines that start with '|'.
    """
    lines = text.splitlines(keepends=True)
    blocks: list[tuple[str, bool]] = []
    current: list[str] = []
    in_table = False

    for line in lines:
        is_table_line = line.strip().startswith("|")
        if is_table_line != in_table:
            if current:
                blocks.append(("".join(current), in_table))
                current = []
            in_table = is_table_line
        current.append(line)

    if current:
        blocks.append(("".join(current), in_table))

    return blocks


def _chunk_text(
    section_id: str | None, page: int, text: str,
    bbox: tuple[float, float, float, float],
    target_tokens: int = 800, overlap: int = 80,
) -> list[Chunk]:
    """Table-aware chunker.

    Keeps markdown table blocks atomic — never splits across a table boundary.
    Long prose blocks use a sliding-window approach with overlap.
    """
    if not text.strip():
        return []

    blocks = _split_into_blocks(text)
    out: list[Chunk] = []

    for block_text, is_table in blocks:
        if not block_text.strip():
            continue
        tokens = ENCODER.encode(block_text)
        if not tokens:
            continue

        if is_table or len(tokens) <= target_tokens:
            # Tables and short blocks → single atomic chunk
            out.append(Chunk(
                id=str(ULID()), section_id=section_id, page=page,
                text=block_text, token_count=len(tokens),
                bboxes=[Bbox(page=page, bbox=bbox)],
            ))
        else:
            # Long prose → sliding window
            i = 0
            while i < len(tokens):
                window = tokens[i: i + target_tokens]
                out.append(Chunk(
                    id=str(ULID()), section_id=section_id, page=page,
                    text=ENCODER.decode(window), token_count=len(window),
                    bboxes=[Bbox(page=page, bbox=bbox)],
                ))
                if i + target_tokens >= len(tokens):
                    break
                i += target_tokens - overlap

    return out


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
                n_corrected=sum(
                    1 for c_idx, c1_md in charts
                    if corrected.get((page_no, c_idx), c1_md) != c1_md
                ),
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


async def parse_pdf(
    path: Path,
    *,
    on_page_done=None,
    save_images_dir: "Path | None" = None,
) -> StructuredDoc:
    """Hybrid PDF parser: renders pages with fitz for vision AND extracts embedded text.
    Sends both to GPT-4.1 Vision for accurate table + number extraction.
    If save_images_dir is set, writes each page PNG there as {page_no:03d}.png.
    """
    doc_id = _sha256(path)
    mu = fitz.open(path)
    total = len(mu)

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

    batches = [pages_raw[i: i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
    sem = asyncio.Semaphore(BATCH_CONCURRENCY)

    async def guarded_batch(batch: list) -> list[Page]:
        async with sem:
            result = await _extract_batch(batch)
            if on_page_done is not None:
                for p in result:
                    try:
                        await on_page_done(p.page_no, total)
                    except Exception:
                        pass
            return result

    batch_results = await asyncio.gather(*(guarded_batch(b) for b in batches))
    pages: list[Page] = sorted(
        (p for batch in batch_results for p in batch),
        key=lambda p: p.page_no,
    )

    # Second pass: fix table structure (wrapped rows, header merging) + validate numbers
    pages = await _validate_table_pages(pages, pages_raw)

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

    sections = _detect_sections(pages)
    section_by_page: dict[int, str] = {}
    for s in sections:
        for pn in range(s.page_start, s.page_end + 1):
            section_by_page[pn] = s.id

    chunks: list[Chunk] = []
    for p in pages:
        if not p.markdown.strip():
            continue
        bbox = (0.0, 0.0, p.width or 612.0, p.height or 792.0)
        chunks.extend(_chunk_text(
            section_by_page.get(p.page_no), p.page_no, p.markdown, bbox,
        ))

    return StructuredDoc(
        doc_id=doc_id, n_pages=len(pages),
        pages=pages, sections=sections, chunks=chunks,
    )
