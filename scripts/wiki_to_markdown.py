"""Render a document's wiki as markdown to stdout.

Usage (from the backend dir, with the project venv activated):
    python ../scripts/wiki_to_markdown.py <document_id_or_doc_id>

Document IDs (from the documents table) AND raw doc_ids (sha256 hashes) both work.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlmodel import Session  # noqa: E402
from app.parser.schema import StructuredDoc  # noqa: E402
from app.storage.db import engine  # noqa: E402
from app.storage.models import Document  # noqa: E402
from app.wiki.builder import load_wiki  # noqa: E402
from app.wiki.markdown import wiki_to_markdown  # noqa: E402


def resolve(identifier: str) -> tuple[StructuredDoc, str] | None:
    """Resolve either a Document.id or a raw doc_id (sha256). Returns (parsed, doc_id)."""
    with Session(engine) as s:
        d = s.get(Document, identifier)
        if d is not None and d.parsed_path:
            parsed = StructuredDoc.model_validate_json(Path(d.parsed_path).read_text())
            return parsed, parsed.doc_id

    # Treat the identifier as a raw doc_id by scanning the parsed dir.
    parsed_dir = Path(__file__).resolve().parents[1] / "backend" / "storage" / "parsed"
    candidate = parsed_dir / f"{identifier}.json"
    if candidate.exists():
        parsed = StructuredDoc.model_validate_json(candidate.read_text())
        return parsed, parsed.doc_id
    return None


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python scripts/wiki_to_markdown.py <document_id_or_doc_id>", file=sys.stderr)
        return 2
    ident = sys.argv[1]
    resolved = resolve(ident)
    if resolved is None:
        print(f"could not resolve identifier: {ident}", file=sys.stderr)
        return 1
    parsed, doc_id = resolved
    wiki = load_wiki(doc_id)
    if wiki is None:
        print(f"no wiki found for doc_id={doc_id}; reingest the document first", file=sys.stderr)
        return 1
    print(wiki_to_markdown(wiki, parsed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
