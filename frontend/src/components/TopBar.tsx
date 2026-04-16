import { Command, Download, Activity } from "lucide-react";
import { api } from "../api/client";
import { useGrid } from "../store/grid";

export function TopBar({ onCommand }: { onCommand: () => void }) {
  const v = useGrid((s) => s.view);
  const mode = v?.grid.retriever_mode;
  const modeLabel = mode === "wiki" ? "Wiki" : mode === "isd" ? "ISD" : mode === "naive" ? "Naive" : "—";
  const modeColor =
    mode === "wiki" ? "text-[var(--color-accent-streaming)]" :
    mode === "isd" ? "text-[var(--color-accent-verify)]" :
    "text-[var(--color-muted)]";

  // count cells in each state so the audience sees work in flight
  const activity = useGrid((s) => {
    const out = { retrieving: 0, drafting: 0, verifying: 0, done: 0, failed: 0, total: 0 };
    if (!s.view) return out;
    for (const c of s.view.cells) {
      out.total += 1;
      if (c.status === "retrieving") out.retrieving += 1;
      else if (c.status === "drafting") out.drafting += 1;
      else if (c.status === "verifying") out.verifying += 1;
      else if (c.status === "done") out.done += 1;
      else if (c.status === "failed") out.failed += 1;
    }
    return out;
  });
  const busy = activity.retrieving + activity.drafting + activity.verifying;

  return (
    <div className="h-11 border-b border-[var(--color-border)] px-4 flex items-center gap-3
                    text-[12px] bg-[var(--color-canvas)]/80 backdrop-blur sticky top-0 z-10">
      <div className="font-[var(--font-ui)] text-[var(--color-text)] tracking-tight">◇ Matrix</div>
      <div className="h-3 w-px bg-[var(--color-border)]" />
      <div className="text-[var(--color-muted)]">{v?.grid.name ?? "new grid"}</div>
      <div className="h-3 w-px bg-[var(--color-border)]" />
      <div className="text-[var(--color-muted)] font-[var(--font-mono)]">gpt-4.1</div>
      <div className={`px-1.5 py-0.5 rounded text-[10px] font-[var(--font-mono)] uppercase tracking-wide border border-[var(--color-border)] ${modeColor}`}>
        {modeLabel}
      </div>

      {/* activity indicator */}
      <div className="h-3 w-px bg-[var(--color-border)]" />
      <div className="flex items-center gap-2 font-[var(--font-mono)] text-[11px]">
        <Activity className={`w-3 h-3 ${busy > 0 ? "text-[var(--color-accent-streaming)] animate-pulse" : "text-[var(--color-muted)]"}`} />
        {busy > 0 ? (
          <>
            {activity.retrieving > 0 && (
              <span className="text-[var(--color-accent-streaming)]">{activity.retrieving} retrieving</span>
            )}
            {activity.drafting > 0 && (
              <span className="text-[var(--color-accent-streaming)]">· {activity.drafting} drafting</span>
            )}
            {activity.verifying > 0 && (
              <span className="text-[var(--color-accent-verify)]">· {activity.verifying} verifying</span>
            )}
          </>
        ) : (
          <span className="text-[var(--color-muted)]">idle</span>
        )}
        <span className="text-[var(--color-muted)]">· {activity.done}/{activity.total} done</span>
      </div>

      <div className="flex-1" />

      {v && (
        <a
          href={api.exportCsvUrl(v.grid.id)}
          className="px-2.5 py-1 rounded border border-[var(--color-border)] text-[var(--color-muted)]
                     hover:text-[var(--color-text)] hover:border-[var(--color-muted)] transition
                     flex items-center gap-1.5 font-[var(--font-mono)]"
          title="Export grid as CSV"
        >
          <Download className="w-3 h-3" /> CSV
        </a>
      )}
      <button
        onClick={onCommand}
        className="px-2.5 py-1 rounded border border-[var(--color-border)] text-[var(--color-muted)]
                   hover:text-[var(--color-text)] hover:border-[var(--color-muted)] transition
                   flex items-center gap-1.5 font-[var(--font-mono)]"
        aria-label="Open command palette"
      >
        <Command className="w-3 h-3" /> K
      </button>
    </div>
  );
}
