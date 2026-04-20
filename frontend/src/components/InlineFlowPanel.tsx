import { X } from "lucide-react";
import { FlowOverlay } from "./FlowOverlay";
import { useGrid } from "../store/grid";
import type { CellStatus } from "../api/types";

interface Props {
  cellId: string | null;
  onClose: () => void;
}

const STATUS_DOT: Record<CellStatus, string> = {
  idle: "bg-zinc-500",
  queued: "bg-zinc-500",
  retrieving: "bg-[var(--color-accent-streaming)] animate-pulse",
  drafting: "bg-[var(--color-accent-streaming)] animate-pulse",
  verifying: "bg-[var(--color-accent-verify)] animate-pulse",
  done: "bg-[var(--color-accent-done)]",
  stale: "bg-[var(--color-accent-stale)]",
  failed: "bg-[var(--color-accent-fail)]",
};

export function InlineFlowPanel({ cellId, onClose }: Props) {
  const cell = useGrid((s) => {
    if (!cellId || !s.view) return undefined;
    return s.view.cells.find((c) => c.id === cellId);
  });
  const status: CellStatus = cell?.status ?? "idle";

  return (
    <div className="w-[300px] flex-shrink-0 border-l border-[var(--color-border)] flex flex-col h-full">
      {/* panel header */}
      <div className="h-9 flex items-center justify-between px-3 border-b border-[var(--color-border)] bg-[var(--color-surface)]/80 backdrop-blur flex-shrink-0">
        <div className="flex items-center gap-2 text-[11px] font-[var(--font-mono)]">
          <span className="text-[var(--color-accent-streaming)]">⬡</span>
          <span className="text-[var(--color-muted)]">3D Pipeline</span>
          {cell && (
            <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT[status]}`} />
          )}
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded text-[var(--color-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-surface-2)] transition"
          aria-label="Close 3D panel"
        >
          <X className="w-3 h-3" />
        </button>
      </div>

      {/* scene */}
      <div className="flex-1 relative overflow-hidden">
        <FlowOverlay cellId={cellId} onClose={onClose} variant="panel" />
      </div>
    </div>
  );
}
