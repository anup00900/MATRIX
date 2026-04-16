import { Command } from "lucide-react";
import { useGrid } from "../store/grid";

export function TopBar({ onCommand }: { onCommand: () => void }) {
  const v = useGrid((s) => s.view);
  const mode = v?.grid.retriever_mode;
  const modeLabel = mode === "wiki" ? "Wiki" : mode === "isd" ? "ISD" : mode === "naive" ? "Naive" : "—";
  const modeColor =
    mode === "wiki" ? "text-[var(--color-accent-streaming)]" :
    mode === "isd" ? "text-[var(--color-accent-verify)]" :
    "text-[var(--color-muted)]";
  return (
    <div className="h-11 border-b border-[var(--color-border)] px-4 flex items-center gap-4
                    text-[12px] bg-[var(--color-canvas)]/80 backdrop-blur sticky top-0 z-10">
      <div className="font-[var(--font-ui)] text-[var(--color-text)] tracking-tight">◇ Matrix</div>
      <div className="h-3 w-px bg-[var(--color-border)]" />
      <div className="text-[var(--color-muted)]">{v?.grid.name ?? "new grid"}</div>
      <div className="h-3 w-px bg-[var(--color-border)]" />
      <div className="text-[var(--color-muted)] font-[var(--font-mono)]">gpt-4.1</div>
      <div className={`px-1.5 py-0.5 rounded text-[10px] font-[var(--font-mono)] uppercase tracking-wide border border-[var(--color-border)] ${modeColor}`}>
        {modeLabel}
      </div>
      <div className="flex-1" />
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
