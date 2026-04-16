import { motion } from "framer-motion";
import type { Cell as TCell } from "../api/types";
import { cn } from "../lib/utils";
import { useGrid } from "../store/grid";
import { CellRenderer } from "./CellRenderer";

const DOT: Record<string, string> = {
  idle: "bg-zinc-700",
  queued: "bg-zinc-500",
  retrieving: "bg-[var(--color-accent-streaming)] animate-pulse",
  drafting: "bg-[var(--color-accent-streaming)] animate-pulse",
  verifying: "bg-[var(--color-accent-verify)] animate-pulse",
  done: "bg-[var(--color-accent-done)]",
  stale: "bg-[var(--color-accent-stale)]",
  failed: "bg-[var(--color-accent-fail)]",
};

const STREAMING = new Set(["queued", "retrieving", "drafting", "verifying"]);

export function Cell({ cell }: { cell: TCell }) {
  const focus = useGrid((s) => s.focus);
  const focused = useGrid((s) => s.focused);
  return (
    <div
      onClick={() => focus(cell.id)}
      className={cn(
        "relative h-9 px-2 flex items-center gap-2 cursor-pointer",
        "hover:bg-[var(--color-surface-2)] text-[13px] border-r border-[var(--color-border)]",
        focused === cell.id && "bg-[var(--color-surface-2)] ring-1 ring-inset ring-[var(--color-accent-streaming)]/60",
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", DOT[cell.status] ?? "bg-zinc-700")} />
      <div className="flex-1 min-w-0 truncate">
        <CellRenderer cell={cell} />
      </div>
      {STREAMING.has(cell.status) && (
        <motion.div
          className="absolute bottom-0 left-0 h-[2px] bg-[var(--color-accent-streaming)]"
          initial={{ width: "10%" }}
          animate={{ width: "90%" }}
          transition={{ duration: 1.6, repeat: Infinity, repeatType: "reverse" }}
        />
      )}
    </div>
  );
}
