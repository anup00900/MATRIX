from __future__ import annotations
import asyncio, base64, hashlib, io, re
from pathlib import Path
import fitz, tiktoken
from PIL import Image
from ulid import ULID
from ..llm import llm
from ..logging import log
from .schema import StructuredDoc, Page, Section, Chunk, Bbox, DocMeta

ENCODER = tiktoken.get_encoding("cl100k_base")
HEADING_RE = re.compile(r"^#{1,4}\s+(?P<title>.+)$")
ITEM_RE = re.compile(r"^(Item\s+\d+[A-Z]?\.?|Part\s+[IVX]+)", re.IGNORECASE)
PAGE_CONCURRENCY = 4
RENDER_DPI = 150  # ~1700px wide for letter paper, plenty for vision

VISION_SYSTEM = (
    "You are a PDF page-to-markdown converter for financial filings (10-K, 10-Q, earnings). "
    "Convert the page image to clean GitHub-flavored markdown. "
    "Preserve heading hierarchy with #, ##, ###. "
    "Render tables as markdown tables with aligned columns. "
    "Keep numeric values and units exactly as printed. "
    "Preserve bullet/numbered lists. "
    "Do NOT add commentary, explanations, or invent content not visible. "
    "If the page has no extractable content, return an empty string."
)
VISION_USER = "Convert this page to clean markdown. Output ONLY the markdown, nothing else."

def _sha256(path: Path) -> str:
    h = hashlib.sha256(); h.update(path.read_bytes()); return h.hexdigest()

def _render_page_b64(page: "fitz.Page", dpi: int = RENDER_DPI) -> tuple[str, float, float]:
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii"), float(page.rect.width), float(page.rect.height)

async def _extract_page_markdown(page: "fitz.Page", page_no: int) -> Page:
    try:
        b64, w, h = _render_page_b64(page)
        md = await llm.vision_chat(system=VISION_SYSTEM, user_text=VISION_USER,
                                   image_b64_png=b64, max_tokens=4000)
        return Page(page_no=page_no, markdown=md.strip(), width=w, height=h)
    except Exception as e:
        log.warning("parser.vision.failed", page=page_no, error=str(e)[:200])
        return Page(page_no=page_no, markdown="", width=0.0, height=0.0, failed=True)

def _detect_sections(pages: list[Page]) -> list[Section]:
    sections: list[Section] = []
    cur_title: str | None = None
    cur_start = 1
    cur_text: list[str] = []
    for p in pages:
        for line in p.markdown.splitlines():
            ln = line.strip()
            m = HEADING_RE.match(ln)
            if not m: continue
            heading_text = m.group("title").strip()
            # prefer Item / Part headings; fall back to top-level # headings
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

def _chunk_text(section_id: str | None, page: int, text: str,
                bbox: tuple[float, float, float, float],
                target_tokens: int = 500, overlap: int = 50) -> list[Chunk]:
    tokens = ENCODER.encode(text)
    if not tokens: return []
    out: list[Chunk] = []
    i = 0
    while i < len(tokens):
        window = tokens[i : i + target_tokens]
        out.append(Chunk(
            id=str(ULID()), section_id=section_id, page=page,
            text=ENCODER.decode(window), token_count=len(window),
            bboxes=[Bbox(page=page, bbox=bbox)],
        ))
        if i + target_tokens >= len(tokens): break
        i += target_tokens - overlap
    return out

async def parse_pdf(
    path: Path,
    *,
    on_page_done=None,  # async callable (page_no, total) -> None, optional progress hook
) -> StructuredDoc:
    """Vision-based PDF parser. Renders each page, sends to gpt-4.1 vision,
    receives markdown, then stitches into a StructuredDoc.

    If on_page_done is provided it's awaited after every page-level vision call
    so callers can surface progress events to the UI.
    """
    doc_id = _sha256(path)
    mu = fitz.open(path)
    total = len(mu)
    sem = asyncio.Semaphore(PAGE_CONCURRENCY)
    async def guarded(pg, idx):
        async with sem:
            p = await _extract_page_markdown(pg, idx)
            if on_page_done is not None:
                try: await on_page_done(idx, total)
                except Exception: pass
            return p
    pages = await asyncio.gather(*(guarded(mu[i], i + 1) for i in range(total)))

    sections = _detect_sections(pages)
    section_by_page: dict[int, str] = {}
    for s in sections:
        for pn in range(s.page_start, s.page_end + 1):
            section_by_page[pn] = s.id   # last-wins: later sections override earlier on boundary pages

    chunks: list[Chunk] = []
    for p in pages:
        if not p.markdown.strip(): continue
        bbox = (0.0, 0.0, p.width or 612.0, p.height or 792.0)
        chunks.extend(_chunk_text(section_by_page.get(p.page_no), p.page_no,
                                  p.markdown, bbox))
    return StructuredDoc(
        doc_id=doc_id, n_pages=len(pages),
        pages=pages, sections=sections, chunks=chunks,
    )
