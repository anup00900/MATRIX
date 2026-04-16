import { Command } from "lucide-react";
import { useGrid } from "../store/grid";

export function TopBar({ onCommand }: { onCommand: () => void }) {
  const v = useGrid((s) => s.view);
  const mode = v?.grid.retriever_mode;
  const modeLabel = mode === "wiki" ? "Wiki" : mode === "isd" ? "ISD" : mode === "naive" ? "Naive" : "—";
  const modeColor =
    mode === "wiki" ? "text-[--color-accent-streaming]" :
    mode === "isd" ? "text-[--color-accent-verify]" :
    "text-[--color-muted]";
  return (
    <div className="h-11 border-b border-[--color-border] px-4 flex items-center gap-4
                    text-[12px] bg-[--color-canvas]/80 backdrop-blur sticky top-0 z-10">
      <div className="font-[--font-ui] text-[--color-text] tracking-tight">◇ Matrix</div>
      <div className="h-3 w-px bg-[--color-border]" />
      <div className="text-[--color-muted]">{v?.grid.name ?? "new grid"}</div>
      <div className="h-3 w-px bg-[--color-border]" />
      <div className="text-[--color-muted] font-[--font-mono]">gpt-4.1</div>
      <div className={`px-1.5 py-0.5 rounded text-[10px] font-[--font-mono] uppercase tracking-wide border border-[--color-border] ${modeColor}`}>
        {modeLabel}
      </div>
      <div className="flex-1" />
      <button
        onClick={onCommand}
        className="px-2.5 py-1 rounded border border-[--color-border] text-[--color-muted]
                   hover:text-[--color-text] hover:border-[--color-muted] transition
                   flex items-center gap-1.5 font-[--font-mono]"
        aria-label="Open command palette"
      >
        <Command className="w-3 h-3" /> K
      </button>
    </div>
  );
}
