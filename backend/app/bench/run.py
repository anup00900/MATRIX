from __future__ import annotations
import argparse, asyncio, json, sys, time
from pathlib import Path
from ..llm import llm
from ..logging import log, configure_logging
from ..parser.pdf import parse_pdf
from ..parser.meta import extract_doc_meta
from ..retriever.index import build_index
from ..retriever.naive import NaiveRetriever
from ..retriever.isd import ISDRetriever
from ..retriever.wiki import WikiRetriever
from ..wiki.builder import build_wiki, load_wiki
from ..agent.runner import run_cell
from .dataset import load_questions, normalise_question, fetch_pdf


VALID_MODES = {"naive", "isd", "wiki"}


async def _ensure_doc(doc_name: str, *, want_wiki: bool):
    pdf = await fetch_pdf(doc_name)
    parsed = await parse_pdf(pdf)
    parsed.meta = await extract_doc_meta(parsed)
    await build_index(parsed)
    if want_wiki and load_wiki(parsed.doc_id) is None:
        await build_wiki(parsed)
    return parsed


async def _judge(question: str, gold: str, predicted: str) -> str:
    """LLM-as-judge. Returns one of: correct | partially_correct | incorrect."""
    msg = (
        "Grade an answer against a gold answer. Reply with ONE WORD only: "
        "correct | partially_correct | incorrect.\n\n"
        f"Question: {question}\nGold: {gold}\nPredicted: {predicted}"
    )
    out = await llm.chat(
        messages=[{"role": "user", "content": msg}], max_tokens=10, temperature=0.0,
    )
    verdict = out.strip().lower().split()[0] if out.strip() else "incorrect"
    if verdict not in {"correct", "partially_correct", "incorrect"}:
        return "incorrect"
    return verdict


def _page_match(cited: list[int], gold: list[int], tol: int = 1) -> tuple[float, float]:
    """Return (recall, precision) of cited pages vs gold, with ±tol tolerance."""
    if not gold:
        return 1.0, 1.0 if not cited else 0.0
    if not cited:
        return 0.0, 0.0
    cited_set = set(cited)
    recall_hits = sum(1 for g in gold if any(abs(g - c) <= tol for c in cited))
    precision_hits = sum(1 for c in cited_set if any(abs(c - g) <= tol for g in gold))
    return recall_hits / len(gold), precision_hits / len(cited_set)


def _make_retriever(mode: str, parsed):
    if mode == "naive": return NaiveRetriever()
    if mode == "isd":   return ISDRetriever()
    if mode == "wiki":
        w = load_wiki(parsed.doc_id)
        if w is None:
            raise RuntimeError(f"wiki missing for doc {parsed.doc_id[:8]}")
        return WikiRetriever(wiki=w)
    raise ValueError(mode)


async def run_mode(*, mode: str, limit: int, out_dir: Path, offset: int = 0) -> list[dict]:
    assert mode in VALID_MODES
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = load_questions(limit=limit + offset)[offset:]
    results: list[dict] = []
    # cache parsed docs in-process so we don't re-parse for every question
    doc_cache: dict[str, object] = {}
    for i, row in enumerate(raw):
        q = normalise_question(row)
        try:
            if not q["doc_name"]:
                raise ValueError("no doc_name in row")
            if q["doc_name"] not in doc_cache:
                doc_cache[q["doc_name"]] = await _ensure_doc(
                    q["doc_name"], want_wiki=(mode == "wiki"),
                )
            parsed = doc_cache[q["doc_name"]]
            retriever = _make_retriever(mode, parsed)
            section_index = [{"id": s.id, "title": s.title} for s in parsed.sections]

            res = await run_cell(
                prompt=q["question"],
                doc=parsed, retriever=retriever,
                retriever_mode=mode, shape_hint="text",
                section_index=section_index,
            )
            predicted = res.answer if isinstance(res.answer, str) else json.dumps(res.answer)
            verdict = await _judge(q["question"], q["answer"], predicted)
            cited_pages = sorted({c.page for c in res.citations})
            recall, precision = _page_match(cited_pages, q["gold_pages"])
            results.append({
                "i": i + offset,
                "question": q["question"], "doc": q["doc_name"],
                "gold": q["answer"], "predicted": predicted,
                "verdict": verdict,
                "cited_pages": cited_pages,
                "gold_pages": q["gold_pages"],
                "page_recall": recall, "page_precision": precision,
                "latency_ms": res.latency_ms, "tokens": res.tokens_used,
            })
            log.info("bench.q.done", mode=mode, i=i+offset, verdict=verdict)
        except Exception as e:
            log.exception("bench.q.failed", mode=mode, i=i+offset, err=str(e)[:200])
            results.append({"i": i + offset, "error": str(e)[:500],
                            "question": q.get("question", ""), "doc": q.get("doc_name", "")})
    path = out_dir / f"{mode}.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in results))
    return results


def report(paths: dict[str, Path], out_md: Path) -> str:
    rows = [
        "| Mode | correct | partial | incorrect | errors | page_recall | page_precision | avg_latency(ms) | avg_tokens |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for mode, p in paths.items():
        if not p.exists():
            rows.append(f"| {mode} | — | — | — | — | — | — | — | — |")
            continue
        lines = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
        errs = sum(1 for l in lines if "error" in l and "verdict" not in l)
        good = [l for l in lines if "verdict" in l]
        if not good:
            rows.append(f"| {mode} | 0 | 0 | 0 | {errs} | — | — | — | — |")
            continue
        c = sum(1 for l in good if l["verdict"] == "correct")
        pa = sum(1 for l in good if l["verdict"] == "partially_correct")
        inc = sum(1 for l in good if l["verdict"] == "incorrect")
        pr = sum(l.get("page_recall", 0.0) for l in good) / len(good)
        pp = sum(l.get("page_precision", 0.0) for l in good) / len(good)
        lt = sum(l["latency_ms"] for l in good) / len(good)
        tk = sum(l["tokens"] for l in good) / len(good)
        rows.append(
            f"| {mode} | {c} | {pa} | {inc} | {errs} | {pr:.2f} | {pp:.2f} | {lt:.0f} | {tk:.0f} |"
        )
    content = "\n".join(rows)
    out_md.write_text(content)
    return content


async def main():
    configure_logging()
    ap = argparse.ArgumentParser(description="FinanceBench harness")
    ap.add_argument("--modes", default="naive,isd,wiki",
                    help="comma-separated modes from {naive,isd,wiki}")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--out", default="bench/results/last")
    ap.add_argument("--subset", choices=["smoke", "full"], default="smoke")
    args = ap.parse_args()

    # smoke defaults to 50; full implies larger limit
    if args.subset == "full" and args.limit == 50:
        args.limit = 500

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    for m in modes:
        if m not in VALID_MODES:
            print(f"unknown mode {m}; valid: {VALID_MODES}", file=sys.stderr)
            sys.exit(2)

    out = Path(args.out)
    paths: dict[str, Path] = {}
    for mode in modes:
        print(f"[bench] running mode={mode} limit={args.limit} offset={args.offset} out={out}")
        paths[mode] = out / f"{mode}.jsonl"
        await run_mode(mode=mode, limit=args.limit, out_dir=out, offset=args.offset)

    report_md = out / "report.md"
    text = report(paths, report_md)
    print("\n" + text)


if __name__ == "__main__":
    asyncio.run(main())
