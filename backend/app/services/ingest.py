from __future__ import annotations
import hashlib
from sqlmodel import Session
from ..logging import log
from ..parser.pdf import parse_pdf
from ..parser.meta import extract_doc_meta
from ..retriever.index import build_index
from ..settings import settings
from ..storage.db import engine
from ..storage.models import Document
from ..wiki.builder import build_wiki, wiki_path_for


def _sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256(); h.update(b); return h.hexdigest()


async def ingest_pdf(
    *, workspace_id: str, filename: str, content: bytes,
    build_wiki_stage: bool = True,
) -> str:
    sha = _sha256_bytes(content)
    pdf_path = settings.pdfs_dir / f"{sha}.pdf"
    if not pdf_path.exists():
        pdf_path.write_bytes(content)

    with Session(engine) as sess:
        doc_row = Document(
            workspace_id=workspace_id, filename=filename,
            sha256=sha, status="parsing",
        )
        sess.add(doc_row); sess.commit(); sess.refresh(doc_row)
        doc_id = doc_row.id

    try:
        parsed = await parse_pdf(pdf_path)
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

        await build_index(parsed)

        wiki_path: str | None = None
        if build_wiki_stage:
            with Session(engine) as sess:
                d = sess.get(Document, doc_id); assert d
                d.status = "wiki"; sess.add(d); sess.commit()
            await build_wiki(parsed)
            wiki_path = str(wiki_path_for(parsed.doc_id))

        with Session(engine) as sess:
            d = sess.get(Document, doc_id); assert d
            d.status = "ready"
            d.wiki_path = wiki_path
            sess.add(d); sess.commit()
        log.info("ingest.ready", doc_id=doc_id, sha=sha[:8])
        return doc_id
    except Exception as e:
        log.exception("ingest.failed", doc_id=doc_id)
        with Session(engine) as sess:
            d = sess.get(Document, doc_id)
            if d:
                d.status = "failed"
                d.error = str(e)[:500]
                sess.add(d); sess.commit()
        raise
