import { useEffect, useMemo, useState } from "react";
import { X, RotateCw, ChevronDown, ChevronRight } from "lucide-react";
import { api } from "../api/client";
import type { Citation } from "../api/types";
import { cn } from "../lib/utils";
import { useGrid } from "../store/grid";
import { CellRenderer } from "./CellRenderer";
import { PdfView } from "./PdfView";

const CONFIDENCE_DOTS: Record<string, number> = { high: 3, medium: 2, low: 1 };

export function FocusPane() {
  const { view, focused, focus, upsertCell } = useGrid();
  const [activeCite, setActiveCite] = useState(0);
  const [traceOpen, setTraceOpen] = useState(false);

  useEffect(() => {
    setActiveCite(0);
    setTraceOpen(false);
  }, [focused]);

  const cell = view?.cells.find((c) => c.id === focused) ?? null;

  const citations: Citation[] = cell?.citations_json ?? [];
  const cite = citations[activeCite];
  const row = cell ? view?.rows.find((r) => r.id === cell.row_id) : undefined;
  const documentId = row?.document_id ?? null;
  const pdfUrl = documentId ? api.pdfUrl(documentId) : "";

  const highlight = useMemo<[number, number, number, number] | undefined>(() => {
    const bbox = cite?.bboxes?.[0]?.bbox;
    if (!bbox || bbox.length !== 4) return undefined;
    return [bbox[0], bbox[1], bbox[2], bbox[3]];
  }, [cite]);

  if (!focused || !view) return null;
  if (!cell) return null;

  const confidenceDots = CONFIDENCE_DOTS[cell.confidence ?? ""] ?? 0;

  return (
    <div className="w-[44%] border-l border-[var(--color-border)] bg-[var(--color-canvas)] flex flex-col min-w-0">
      <div className="h-11 px-4 flex items-center justify-between border-b border-[var(--color-border)] shrink-0">
        <div className="flex items-center gap-2 text-[11px] font-[var(--font-mono)] text-[var(--color-muted)]">
          <span>trace</span>
          <span className="text-[var(--color-text)]">{cell.id.slice(-10)}</span>
        </div>
        <div className="flex gap-1">
          <button
            onClick={async () => {
              await api.rerunCell(cell.id);
              upsertCell({ id: cell.id, status: "queued" });
            }}
            className="px-2 py-1 text-[11px] border border-[var(--color-border)] rounded
                       hover:bg-[var(--color-surface)] transition flex items-center gap-1"
          >
            <RotateCw className="w-3 h-3" /> rerun
          </button>
          <button
            onClick={() => focus(null)}
            aria-label="Close"
            className="p-1 text-[var(--color-muted)] hover:text-[var(--color-text)] rounded hover:bg-[var(--color-surface)]"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="p-4 space-y-5 overflow-auto">
        <section>
          <div className="text-[10px] text-[var(--color-muted)] uppercase tracking-wide mb-1">
            Answer
          </div>
          <div className="text-xl font-[var(--font-ui)] min-h-[1.75rem]">
            {cell.status === "done" ? (
              <CellRenderer cell={cell} />
            ) : (
              <span className="text-[var(--color-muted)] text-[13px]">{cell.status}…</span>
            )}
          </div>
          <div className="mt-2 flex items-center gap-3 text-[11px] text-[var(--color-muted)] font-[var(--font-mono)]">
            <span className="flex items-center gap-1">
              conf
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className={cn(
                    "h-1.5 w-1.5 rounded-full",
                    i < confidenceDots
                      ? "bg-[var(--color-accent-done)]"
                      : "bg-[var(--color-border)]",
                  )}
                />
              ))}
            </span>
            <span>·</span>
            <span>{cell.latency_ms}ms</span>
            <span>·</span>
            <span>{cell.tokens_used}tok</span>
            <span>·</span>
            <span>{cell.retriever_mode ?? "—"}</span>
          </div>
        </section>

        {citations.length > 0 && (
          <section>
            <div className="text-[10px] text-[var(--color-muted)] uppercase tracking-wide mb-2">
              Citations · {citations.length}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {citations.map((c, i) => (
                <button
                  key={`${c.chunk_id}-${i}`}
                  onClick={() => setActiveCite(i)}
                  className={cn(
                    "px-2 py-1 text-[11px] font-[var(--font-mono)] rounded border transition",
                    i === activeCite
                      ? "border-[var(--color-accent-streaming)] text-[var(--color-accent-streaming)] bg-[var(--color-accent-streaming)]/10"
                      : "border-[var(--color-border)] text-[var(--color-muted)] hover:text-[var(--color-text)]",
                  )}
                >
                  [{c.chunk_id.slice(-4)}] p.{c.page}
                </button>
              ))}
            </div>
            {cite && (
              <div className="mt-3 text-[12px] bg-[var(--color-surface)] p-3 rounded border border-[var(--color-border)] leading-relaxed">
                {cite.snippet}
              </div>
            )}
          </section>
        )}

        {cite && pdfUrl && (
          <section>
            <div className="text-[10px] text-[var(--color-muted)] uppercase tracking-wide mb-2">
              Source · page {cite.page}
            </div>
            <PdfView url={pdfUrl} page={cite.page} highlight={highlight} />
          </section>
        )}

        <section>
          <button
            onClick={() => setTraceOpen((o) => !o)}
            className="flex items-center gap-1 text-[10px] uppercase tracking-wide text-[var(--color-muted)] hover:text-[var(--color-text)]"
          >
            {traceOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            Reasoning trace
          </button>
          {traceOpen && <TraceView cellId={cell.id} />}
        </section>

        {cell.error && (
          <section className="p-3 rounded border border-[var(--color-accent-fail)]/40 bg-[var(--color-accent-fail)]/10 text-[12px] text-[var(--color-accent-fail)] font-[var(--font-mono)]">
            {cell.error}
          </section>
        )}
      </div>
    </div>
  );
}

function TraceView({ cellId }: { cellId: string }) {
  // The trace blob is not currently served by the API; show a placeholder line.
  // Future enhancement: expose GET /api/cells/{id}/trace to fetch gzipped trace.
  return (
    <pre className="mt-2 text-[11px] font-[var(--font-mono)] text-[var(--color-muted)] whitespace-pre-wrap leading-relaxed">
      Reasoning trace for {cellId.slice(-10)} is persisted on the backend.{"\n"}
      (Trace viewer: pending /api/cells/:id/trace endpoint.)
    </pre>
  );
}
