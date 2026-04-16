import type { Cell } from "../api/types";

export function CellRenderer({ cell }: { cell: Cell }) {
  if (!cell.answer_json)
    return <span className="text-[var(--color-muted)]">—</span>;
  const { value, shape } = cell.answer_json;
  const str = typeof value === "string" ? value : JSON.stringify(value);
  switch (shape) {
    case "percentage":
    case "number":
    case "currency":
      return (
        <span className="font-[var(--font-mono)] tabular-nums text-right">{str}</span>
      );
    case "list": {
      const items = Array.isArray(value) ? (value as unknown[]) : [value];
      return (
        <span>
          {items.slice(0, 2).map((x) => String(x)).join(" · ")}
          {items.length > 2 && (
            <span className="text-[var(--color-muted)]"> +{items.length - 2}</span>
          )}
        </span>
      );
    }
    case "table":
      return (
        <span className="text-[var(--color-muted)]">
          table ({(value as unknown[])?.length ?? 0} rows)
        </span>
      );
    default:
      return (
        <span className="truncate">
          {str.length > 180 ? str.slice(0, 180) + "…" : str}
        </span>
      );
  }
}
