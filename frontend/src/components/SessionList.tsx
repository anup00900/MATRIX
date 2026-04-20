import { Plus } from "lucide-react";
import type { Session } from "../store/grid";

interface Props {
  sessions: Session[];
  activeGridId: string | null;
  onNewSession: () => void;
  onSwitchSession: (s: Session) => void;
}

function groupByDate(sessions: Session[]): Array<{ label: string; items: Session[] }> {
  const now = Date.now();
  const DAY = 86_400_000;
  const todayStart = now - (now % DAY);
  const yesterdayStart = todayStart - DAY;

  const groups: Record<string, Session[]> = { Today: [], Yesterday: [], Older: [] };
  for (const s of sessions) {
    if (s.createdAt >= todayStart) groups.Today.push(s);
    else if (s.createdAt >= yesterdayStart) groups.Yesterday.push(s);
    else groups.Older.push(s);
  }

  return (["Today", "Yesterday", "Older"] as const)
    .filter((k) => groups[k].length > 0)
    .map((k) => ({ label: k, items: groups[k] }));
}

export function SessionList({ sessions, activeGridId, onNewSession, onSwitchSession }: Props) {
  const grouped = groupByDate(sessions);

  return (
    <div className="flex flex-col gap-1 p-3">
      <button
        onClick={onNewSession}
        className="flex items-center gap-2 w-full px-3 py-2 rounded-lg border border-dashed border-[var(--color-border)]
                   text-[11px] text-[var(--color-muted)] hover:border-[var(--color-accent-streaming)]
                   hover:text-[var(--color-accent-streaming)] transition font-[var(--font-mono)]"
      >
        <Plus className="w-3 h-3" />
        New session
      </button>

      {grouped.length === 0 && (
        <div className="text-[11px] text-[var(--color-muted)] text-center py-4 font-[var(--font-mono)]">
          No sessions yet
        </div>
      )}

      {grouped.map(({ label, items }) => (
        <div key={label} className="mt-2">
          <div className="text-[9px] uppercase tracking-widest text-[var(--color-muted)] px-1 mb-1">
            {label}
          </div>
          {items.map((s) => (
            <button
              key={s.gridId}
              onClick={() => onSwitchSession(s)}
              className={`w-full text-left px-3 py-2 rounded-lg text-[12px] transition truncate
                ${s.gridId === activeGridId
                  ? "bg-[var(--color-surface-2)] text-[var(--color-text)]"
                  : "text-[var(--color-muted)] hover:bg-[var(--color-surface)] hover:text-[var(--color-text)]"
                }`}
            >
              {s.name}
            </button>
          ))}
        </div>
      ))}
    </div>
  );
}
