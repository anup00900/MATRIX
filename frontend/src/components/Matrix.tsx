import { useState, useRef, useCallback } from "react";
import { X, Upload } from "lucide-react";
import { api } from "../api/client";
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
          <ColumnHeader key={c.id} colId={c.id} prompt={c.prompt} shapeHint={c.shape_hint} />
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

function ColumnHeader({ colId, prompt, shapeHint }: { colId: string; prompt: string; shapeHint: string }) {
  const [deleting, setDeleting] = useState(false);
  const removeColumn = useGrid((s) => s.removeColumn);

  const handleDelete = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (deleting) return;
    setDeleting(true);
    try {
      await api.deleteColumn(colId);
      removeColumn(colId);
    } catch {
      setDeleting(false);
    }
  };

  return (
    <div className="group px-3 h-9 flex items-center gap-2 text-[12px] border-r border-[var(--color-border)]">
      <span className="truncate flex-1">{prompt}</span>
      <span className="text-[var(--color-muted)] font-[var(--font-mono)] text-[10px]">
        {shapeHint}
      </span>
      <button
        onClick={handleDelete}
        disabled={deleting}
        className="opacity-0 group-hover:opacity-100 p-0.5 rounded text-[var(--color-muted)]
                   hover:text-[var(--color-accent-fail)] hover:bg-[var(--color-surface-2)]
                   transition disabled:opacity-30"
        title="Delete column"
      >
        <X className="w-3 h-3" />
      </button>
    </div>
  );
}

function RowHeader({ documentId }: { documentId: string }) {
  const name = useGrid((s) => s.docNames[documentId]);
  const display = name
    ? name.replace(/\.pdf$/i, "")
    : documentId.slice(0, 8);
  return (
    <div className="px-3 h-9 flex items-center gap-2 text-[13px] border-r border-[var(--color-border)]">
      <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-accent-done)] shrink-0" />
      <span className="text-[12px] text-[var(--color-text)] truncate" title={name}>
        {display}
      </span>
    </div>
  );
}

function EmptyState() {
  const workspaceId = useGrid((s) => s.workspaceId);
  const gridId = useGrid((s) => s.view?.grid.id ?? null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const uploadFiles = useCallback(async (files: File[]) => {
    if (!workspaceId || !gridId || files.length === 0) return;
    setUploading(true);
    setError("");
    try {
      for (const f of files) {
        const up = await api.uploadDocument(workspaceId, f);
        await api.addRow(gridId, up.document_id);
      }
      const v = await api.getGrid(gridId);
      useGrid.getState().setView(v);
    } catch (e) {
      setError(String(e));
    } finally {
      setUploading(false);
    }
  }, [workspaceId, gridId]);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const files = Array.from(e.dataTransfer.files).filter(f => f.type === "application/pdf");
    uploadFiles(files);
  }, [uploadFiles]);

  return (
    <div className="flex-1 flex items-center justify-center p-8">
      <div className="max-w-sm w-full text-center space-y-4">
        <div className="text-[var(--color-text)] text-xl font-[var(--font-ui)]">Start with a PDF</div>

        {/* Drop zone */}
        <div
          onClick={() => fileRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`border-2 border-dashed rounded-xl p-10 cursor-pointer transition-colors select-none
            ${dragging
              ? "border-[var(--color-accent-streaming)] bg-[var(--color-accent-streaming)]/5"
              : "border-[var(--color-border)] hover:border-[var(--color-accent-streaming)]/50 hover:bg-[var(--color-surface)]"
            }`}
        >
          <Upload className={`w-8 h-8 mx-auto mb-3 transition-colors ${dragging ? "text-[var(--color-accent-streaming)]" : "text-[var(--color-muted)]"}`} />
          {uploading ? (
            <div className="text-[var(--color-accent-streaming)] text-[13px] font-[var(--font-mono)] animate-pulse">uploading…</div>
          ) : (
            <>
              <div className="text-[var(--color-text)] text-[13px] font-medium">Drop PDFs here or click to browse</div>
              <div className="text-[var(--color-muted)] text-[11px] mt-1">Also available via <kbd className="px-1 py-0.5 border border-[var(--color-border)] rounded font-[var(--font-mono)] text-[10px]">⌘K</kbd> → Add documents</div>
            </>
          )}
        </div>

        {error && (
          <div className="text-[var(--color-accent-fail)] text-[11px] font-[var(--font-mono)] break-all">{error}</div>
        )}

        <input
          ref={fileRef}
          type="file"
          accept="application/pdf"
          multiple
          className="hidden"
          onChange={(e) => uploadFiles(Array.from(e.target.files ?? []))}
        />
      </div>
    </div>
  );
}
