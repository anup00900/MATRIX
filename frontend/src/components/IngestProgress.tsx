import { FileText, Eye, Database, BookOpen, CheckCircle2, AlertTriangle, X, Sparkles } from "lucide-react";
import { cn } from "../lib/utils";
import { useGrid, type IngestStage } from "../store/grid";

const STAGE_ORDER: IngestStage[] = ["queued", "parsing", "indexing", "wiki", "ready"];

const STAGE_LABEL: Record<IngestStage, string> = {
  queued: "queued",
  parsing: "vision parsing",
  indexing: "embedding + indexing",
  wiki: "building wiki",
  ready: "ready",
  failed: "failed",
};

const STAGE_ICON: Record<IngestStage, typeof FileText> = {
  queued: FileText,
  parsing: Eye,
  indexing: Database,
  wiki: BookOpen,
  ready: CheckCircle2,
  failed: AlertTriangle,
};

interface Props {
  onOpen3D?: (documentId: string) => void;
}

export function IngestProgress({ onOpen3D }: Props = {}) {
  const ingests = useGrid((s) => s.ingests);
  const clearDone = useGrid((s) => s.clearDoneIngests);
  const entries = Object.values(ingests).sort((a, b) => b.updated_at - a.updated_at);
  if (entries.length === 0) return null;

  const activeCount = entries.filter((e) => e.stage !== "ready" && e.stage !== "failed").length;

  return (
    <div className="border-b border-[var(--color-border)] bg-[var(--color-canvas)] px-4 py-2">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-[var(--color-muted)]">
          <span className={activeCount > 0 ? "text-[var(--color-accent-streaming)]" : ""}>
            Ingest
          </span>
          <span>·</span>
          <span>{entries.length} docs</span>
          {activeCount > 0 && <span>· {activeCount} in flight</span>}
        </div>
        <button
          onClick={clearDone}
          className="text-[10px] uppercase tracking-wider text-[var(--color-muted)] hover:text-[var(--color-text)]"
          title="Hide finished rows"
        >
          clear done
        </button>
      </div>
      <div className="space-y-1.5">
        {entries.map((e) => {
          const doneIdx = STAGE_ORDER.indexOf(e.stage as IngestStage);
          const Icon = STAGE_ICON[e.stage as IngestStage] ?? FileText;
          const isActive = e.stage !== "ready" && e.stage !== "failed";
          const isFailed = e.stage === "failed";
          const pct = e.stage === "ready" ? 100
            : e.page && e.of ? Math.round(((doneIdx + e.page / e.of) / (STAGE_ORDER.length - 1)) * 100)
            : doneIdx >= 0 ? Math.round((doneIdx / (STAGE_ORDER.length - 1)) * 100)
            : 5;
          return (
            <div key={e.document_id} className="flex items-center gap-3 text-[12px]">
              <Icon className={cn(
                "w-3.5 h-3.5 shrink-0",
                isFailed ? "text-[var(--color-accent-fail)]"
                  : isActive ? "text-[var(--color-accent-streaming)] animate-pulse"
                  : "text-[var(--color-accent-done)]",
              )} />
              <span className="truncate max-w-[260px] font-[var(--font-mono)] text-[11px]" title={e.filename}>
                {e.filename}
              </span>
              <div className="flex-1 min-w-0 h-1 rounded-full bg-[var(--color-border)] overflow-hidden">
                <div
                  className={cn(
                    "h-full transition-all duration-300",
                    isFailed ? "bg-[var(--color-accent-fail)]" :
                    e.stage === "ready" ? "bg-[var(--color-accent-done)]" :
                    "bg-[var(--color-accent-streaming)]",
                  )}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="text-[var(--color-muted)] font-[var(--font-mono)] text-[10px] w-40 text-right truncate">
                {isFailed && e.error ? e.error
                  : e.stage === "parsing" && e.page && e.of ? `vision ${e.page}/${e.of} pages`
                  : STAGE_LABEL[e.stage as IngestStage] ?? e.stage}
                {e.stage === "ready" && e.n_pages && ` · ${e.n_pages}pg · ${e.sections}§`}
              </span>
              {onOpen3D && isActive && (
                <button
                  onClick={() => onOpen3D(e.document_id)}
                  className="px-1.5 py-0.5 text-[10px] rounded border border-[var(--color-accent-streaming)]
                             text-[var(--color-accent-streaming)] hover:bg-[var(--color-accent-streaming)]/10
                             flex items-center gap-1"
                  title="Watch ingest in 3D"
                >
                  <Sparkles className="w-2.5 h-2.5" /> 3D
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
