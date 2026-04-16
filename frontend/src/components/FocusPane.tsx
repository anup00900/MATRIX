import { useGrid } from "../store/grid";

export function FocusPane() {
  const { view, focused, focus } = useGrid();
  if (!focused || !view) return null;
  const cell = view.cells.find((c) => c.id === focused);
  if (!cell) return null;
  return (
    <div className="w-[44%] border-l border-[--color-border] bg-[--color-canvas] p-4 overflow-auto">
      <button
        className="text-[--color-muted] text-[11px] hover:text-[--color-text]"
        onClick={() => focus(null)}
      >
        close
      </button>
      <h3 className="mt-2 font-[--font-ui] text-lg">Cell</h3>
      <pre className="mt-3 text-[11px] font-[--font-mono] whitespace-pre-wrap text-[--color-muted]">
        {JSON.stringify(cell, null, 2)}
      </pre>
    </div>
  );
}
