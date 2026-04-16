import { useGrid } from "../store/grid";
import { Cell } from "./Cell";

export function Matrix() {
  const v = useGrid((s) => s.view);
  if (!v) return <EmptyState />;
  const { columns, rows, cells } = v;
  if (rows.length === 0 && columns.length === 0) return <EmptyState />;
  const cellAt = (rowId: string, colId: string) =>
    cells.find((c) => c.row_id === rowId && c.column_id === colId);
  const template = `320px repeat(${Math.max(1, columns.length)}, minmax(200px, 1fr))`;
  return (
    <div className="m-4 rounded-lg border border-[var(--color-border)] overflow-auto bg-[var(--color-surface)]">
      <div
        className="grid sticky top-0 bg-[var(--color-surface)] border-b border-[var(--color-border)] z-10"
        style={{ gridTemplateColumns: template }}
      >
        <div className="px-3 h-9 flex items-center text-[var(--color-muted)] text-[11px] uppercase tracking-wide border-r border-[var(--color-border)]">
          Document
        </div>
        {columns.map((c) => (
          <div
            key={c.id}
            className="px-3 h-9 flex items-center gap-2 text-[12px] border-r border-[var(--color-border)]"
          >
            <span className="truncate flex-1">{c.prompt}</span>
            <span className="text-[var(--color-muted)] font-[var(--font-mono)] text-[10px]">
              {c.shape_hint}
            </span>
          </div>
        ))}
      </div>
      {rows.map((row) => (
        <div
          key={row.id}
          className="grid border-b border-[var(--color-border)]"
          style={{ gridTemplateColumns: template }}
        >
          <RowHeader documentId={row.document_id} />
          {columns.map((c) => {
            const cell = cellAt(row.id, c.id);
            return cell ? <Cell key={c.id} cell={cell} /> : (
              <div key={c.id} className="h-9 border-r border-[var(--color-border)]" />
            );
          })}
        </div>
      ))}
    </div>
  );
}

function RowHeader({ documentId }: { documentId: string }) {
  return (
    <div className="px-3 h-9 flex items-center gap-2 text-[13px] border-r border-[var(--color-border)]">
      <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-accent-done)] shrink-0" />
      <span className="font-[var(--font-mono)] text-[11px] text-[var(--color-muted)] truncate">
        {documentId.slice(0, 8)}
      </span>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex-1 flex items-center justify-center p-8">
      <div className="max-w-md text-center space-y-4">
        <div className="text-[var(--color-text)] text-2xl font-[var(--font-ui)]">Start with a PDF</div>
        <div className="text-[var(--color-muted)] text-[13px]">
          Press <kbd className="px-1.5 py-0.5 border border-[var(--color-border)] rounded font-[var(--font-mono)]">⌘K</kbd> to add documents,
          spin up a column, or drop in a template.
        </div>
      </div>
    </div>
  );
}
