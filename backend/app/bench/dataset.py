from __future__ import annotations
import hashlib, os
from pathlib import Path
import httpx
from datasets import load_dataset
from ..settings import settings
from ..logging import log


# Where to grab PDFs from. FinanceBench ships PDFs in the Patronus repo.
FINBENCH_PDF_BASE = os.environ.get(
    "FINBENCH_PDF_BASE",
    "https://github.com/patronus-ai/financebench/raw/main/pdfs",
)


def load_questions(split: str = "train", limit: int | None = None):
    ds = load_dataset("PatronusAI/financebench", split=split)
    if limit:
        ds = ds.select(range(min(limit, len(ds))))
    return [dict(row) for row in ds]


def normalise_question(row: dict) -> dict:
    """Map heterogeneous FinanceBench fields to a stable shape.

    Returns {question, answer, doc_name, gold_pages: list[int], evidence_text}
    Missing fields become empty strings / empty lists.
    """
    question = row.get("question") or row.get("prompt") or ""
    answer = row.get("answer") or row.get("gold_answer") or ""

    # doc name: the filename that maps to the source PDF
    doc_name = (
        row.get("doc_name")
        or row.get("document_name")
        or row.get("financebench_doc_name")
        or row.get("document")
        or ""
    )
    if doc_name and not doc_name.lower().endswith(".pdf"):
        doc_name = f"{doc_name}.pdf"

    # gold pages
    pages = row.get("page_number") or row.get("evidence_page_number")
    if isinstance(pages, int):
        gold_pages = [pages]
    elif isinstance(pages, list):
        gold_pages = [int(p) for p in pages if isinstance(p, (int, str)) and str(p).isdigit()]
    elif isinstance(pages, str) and pages.isdigit():
        gold_pages = [int(pages)]
    else:
        gold_pages = []

    # try evidence list (some schemas ship it nested)
    if not gold_pages:
        ev = row.get("evidence") or []
        if isinstance(ev, list):
            for e in ev:
                if isinstance(e, dict):
                    p = e.get("page") or e.get("page_number")
                    if isinstance(p, int):
                        gold_pages.append(p)

    evidence_text = row.get("evidence_text") or ""
    if not evidence_text:
        ev = row.get("evidence") or []
        if isinstance(ev, list):
            parts = [
                e.get("text", "") if isinstance(e, dict) else str(e) for e in ev
            ]
            evidence_text = "\n".join(p for p in parts if p)

    return {
        "question": question,
        "answer": answer,
        "doc_name": doc_name,
        "gold_pages": gold_pages,
        "evidence_text": evidence_text,
    }


def _sha(b: bytes) -> str:
    h = hashlib.sha256(); h.update(b); return h.hexdigest()


async def fetch_pdf(doc_name: str) -> Path:
    """Download (or reuse cached) PDF by doc_name. Content-addressable.

    Attempts URL-encoded path first, falls back to raw. Raises on failure.
    """
    if not doc_name:
        raise ValueError("empty doc_name")
    url = f"{FINBENCH_PDF_BASE}/{doc_name}"
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as c:
        r = await c.get(url)
        if r.status_code != 200:
            raise RuntimeError(f"PDF download {r.status_code} for {doc_name} at {url}")
        sha = _sha(r.content)
        target = settings.pdfs_dir / f"{sha}.pdf"
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(r.content)
        log.info("bench.pdf.ready", doc_name=doc_name, sha=sha[:8], bytes=len(r.content))
        return target
