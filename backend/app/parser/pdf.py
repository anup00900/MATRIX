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
    for i in range(total):
        b64, w, h, fitz_text = _render_page(mu[i])
        pages_raw.append((i + 1, b64, w, h, fitz_text))
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
