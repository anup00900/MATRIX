from __future__ import annotations
import asyncio
import hashlib
from pathlib import Path
from sqlmodel import Session
from ..logging import log
from ..parser.pdf import parse_pdf
from ..parser.meta import extract_doc_meta
from ..retriever.index import build_index
from ..settings import settings
from ..storage.db import engine
from ..storage.models import Document
from ..wiki.builder import build_wiki, wiki_path_for
from .events import bus


def _sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256(); h.update(b); return h.hexdigest()


async def _run_pipeline(
    *, doc_id: str, workspace_id: str, filename: str,
    sha: str, pdf_path: Path, build_wiki_stage: bool,
) -> None:
    """Heavy work: parse → index → wiki. Runs as a background task."""
    channel = f"workspace:{workspace_id}"

    async def emit(stage: str, **extra) -> None:
        await bus.publish(channel, {
            "type": "document",
            "document_id": doc_id,
            "filename": filename,
            "sha": sha[:8],
            "stage": stage,
            **extra,
        })

    try:
        with Session(engine) as sess:
            d = sess.get(Document, doc_id); assert d
            d.status = "parsing"; sess.add(d); sess.commit()
        await emit("parsing")

        async def on_page(page_no: int, total: int) -> None:
            await emit("parsing", page=page_no, of=total)

        parsed = await parse_pdf(pdf_path, on_page_done=on_page)
        parsed.meta = await extract_doc_meta(parsed)
        parsed_path = settings.parsed_dir / f"{sha}.json"
        parsed_path.write_text(parsed.model_dump_json())

        with Session(engine) as sess:
            d = sess.get(Document, doc_id); assert d
            d.status = "indexing"
            d.n_pages = parsed.n_pages
            d.meta_json = parsed.meta.model_dump()
            d.parsed_path = str(parsed_path)
            sess.add(d); sess.commit()
        await emit("indexing", n_pages=parsed.n_pages, sections=len(parsed.sections))

        await build_index(parsed)

        wiki_path: str | None = None
        if build_wiki_stage:
            with Session(engine) as sess:
                d = sess.get(Document, doc_id); assert d
                d.status = "wiki"; sess.add(d); sess.commit()
            await emit("wiki", n_sections=len(parsed.sections))
            await build_wiki(parsed)
            wiki_path = str(wiki_path_for(parsed.doc_id))

        with Session(engine) as sess:
            d = sess.get(Document, doc_id); assert d
            d.status = "ready"
            d.wiki_path = wiki_path
            sess.add(d); sess.commit()
        await emit("ready", n_pages=parsed.n_pages, sections=len(parsed.sections))
        log.info("ingest.ready", doc_id=doc_id, sha=sha[:8])
    except Exception as e:
        log.exception("ingest.failed", doc_id=doc_id)
        with Session(engine) as sess:
            d = sess.get(Document, doc_id)
            if d:
                d.status = "failed"
                d.error = str(e)[:500]
                sess.add(d); sess.commit()
        await bus.publish(f"workspace:{workspace_id}", {
            "type": "document",
            "document_id": doc_id,
            "filename": filename,
            "sha": sha[:8],
            "stage": "failed",
            "error": str(e)[:300],
        })


async def ingest_pdf(
    *, workspace_id: str, filename: str, content: bytes,
    build_wiki_stage: bool = True,
) -> str:
    """Create document record immediately, fire pipeline in background, return doc_id right away."""
    sha = _sha256_bytes(content)
    pdf_path = settings.pdfs_dir / f"{sha}.pdf"
    if not pdf_path.exists():
        pdf_path.write_bytes(content)

    with Session(engine) as sess:
        doc_row = Document(
            workspace_id=workspace_id, filename=filename,
            sha256=sha, status="queued",
        )
        sess.add(doc_row); sess.commit(); sess.refresh(doc_row)
        doc_id = doc_row.id

    # Emit queued immediately so the UI shows the banner
    await bus.publish(f"workspace:{workspace_id}", {
        "type": "document",
        "document_id": doc_id,
        "filename": filename,
        "sha": sha[:8],
        "stage": "queued",
    })

    # Fire pipeline as background coroutine — HTTP response returns now
    asyncio.ensure_future(_run_pipeline(
        doc_id=doc_id, workspace_id=workspace_id,
        filename=filename, sha=sha, pdf_path=pdf_path,
        build_wiki_stage=build_wiki_stage,
    ))

    return doc_id
