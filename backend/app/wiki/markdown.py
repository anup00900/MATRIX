from __future__ import annotations
from ..parser.schema import StructuredDoc
from .schema import DocWiki, Metric


def _fmt_value(m: Metric) -> str:
    """Render a metric value with its unit for table display."""
    val = m.value if isinstance(m.value, str) else f"{m.value}"
    if m.unit:
        return f"{val} {m.unit}"
    return val


def _escape_pipe(s: str) -> str:
    """Escape pipes in a markdown-table cell."""
    return s.replace("|", "\\|")


def wiki_to_markdown(wiki: DocWiki, doc: StructuredDoc | None = None) -> str:
    """Render a DocWiki as a fully-readable markdown report.

    The output covers the overview, every section's summary + questions +
    metrics + claims + entities, and a flat document-wide metrics table.
    Nothing is truncated.
    """
    chunk_page = {c.id: c.page for c in doc.chunks} if doc else {}
    section_by_id = {s.id: s for s in (doc.sections if doc else [])}

    out: list[str] = []
    out.append(f"# Document Wiki — `{wiki.doc_id}`")
    out.append("")
    out.append(f"**Schema version:** {wiki.wiki_schema_version}")
    if doc:
        out.append(
            f"**Pages:** {doc.n_pages}  "
            f"**Sections:** {len(doc.sections)}  "
            f"**Chunks:** {len(doc.chunks)}"
        )
    out.append(
        f"**Total metrics indexed:** {len(wiki.key_metrics_table)}  "
        f"**Total claims:** {sum(len(e.claims) for e in wiki.entries)}  "
        f"**Total entities:** {sum(len(e.entities) for e in wiki.entries)}"
    )
    out.append("")

    out.append("## Overview")
    out.append("")
    out.append(wiki.overview.strip() or "(no overview)")
    out.append("")

    out.append("## Section index")
    out.append("")
    out.append("| # | Section | Pages | Summary |")
    out.append("|---|---|---|---|")
    for i, item in enumerate(wiki.section_index, start=1):
        sec = section_by_id.get(item.id)
        page_range = f"{sec.page_start}–{sec.page_end}" if sec else "?"
        summary = _escape_pipe(item.summary.replace("\n", " ").strip())
        out.append(f"| {i} | {_escape_pipe(item.title)} | {page_range} | {summary} |")
    out.append("")

    out.append("## Sections")
    out.append("")
    for entry in wiki.entries:
        sec = section_by_id.get(entry.section_id)
        title = sec.title if sec else entry.section_id
        page_range = f"pages {sec.page_start}–{sec.page_end}" if sec else ""
        out.append(f"### {title}")
        if page_range:
            out.append(f"*{page_range}*")
        out.append("")
        out.append(f"**Summary.** {entry.summary.strip()}")
        out.append("")

        if entry.questions_answered:
            out.append("**Questions this section answers:**")
            for q in entry.questions_answered:
                out.append(f"- {q}")
            out.append("")

        if entry.metrics:
            out.append(f"**Metrics ({len(entry.metrics)}):**")
            out.append("")
            out.append("| # | Name | Value | Unit | Period | Page | Chunk |")
            out.append("|---|---|---|---|---|---|---|")
            for i, m in enumerate(entry.metrics, start=1):
                value = m.value if isinstance(m.value, str) else f"{m.value}"
                page = chunk_page.get(m.chunk_id, "")
                out.append(
                    f"| {i} "
                    f"| {_escape_pipe(m.name)} "
                    f"| {_escape_pipe(value)} "
                    f"| {_escape_pipe(m.unit or '')} "
                    f"| {_escape_pipe(m.period or '')} "
                    f"| {page} "
                    f"| `{m.chunk_id[:12]}…` |"
                )
            out.append("")

        if entry.claims:
            out.append(f"**Claims ({len(entry.claims)}):**")
            for cl in entry.claims:
                page_tags = ", ".join(
                    f"p.{chunk_page.get(cid)}" for cid in cl.evidence_chunks
                    if chunk_page.get(cid) is not None
                )
                tag = f" [{page_tags}]" if page_tags else ""
                out.append(f"- ({cl.confidence:.2f}) {cl.text}{tag}")
            out.append("")

        if entry.entities:
            out.append(f"**Entities ({len(entry.entities)}):**")
            out.append("")
            out.append("| Name | Type | Mentions |")
            out.append("|---|---|---|")
            for ent in entry.entities:
                pages = sorted({
                    chunk_page.get(cid) for cid in ent.mentions
                    if chunk_page.get(cid) is not None
                })
                page_str = ", ".join(f"p.{p}" for p in pages) if pages else ""
                out.append(
                    f"| {_escape_pipe(ent.name)} "
                    f"| {_escape_pipe(ent.type)} "
                    f"| {page_str} |"
                )
            out.append("")

        out.append("---")
        out.append("")

    out.append("## All metrics — document-wide")
    out.append("")
    out.append(f"Total: **{len(wiki.key_metrics_table)}** metrics.")
    out.append("")
    out.append("| Key | Name | Value | Unit | Period | Page | Chunk |")
    out.append("|---|---|---|---|---|---|---|")
    for key, m in wiki.key_metrics_table.items():
        value = m.value if isinstance(m.value, str) else f"{m.value}"
        page = chunk_page.get(m.chunk_id, "")
        out.append(
            f"| `{_escape_pipe(key)}` "
            f"| {_escape_pipe(m.name)} "
            f"| {_escape_pipe(value)} "
            f"| {_escape_pipe(m.unit or '')} "
            f"| {_escape_pipe(m.period or '')} "
            f"| {page} "
            f"| `{m.chunk_id[:12]}…` |"
        )
    out.append("")

    return "\n".join(out)
