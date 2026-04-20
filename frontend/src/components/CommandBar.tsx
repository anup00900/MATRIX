import { Command } from "cmdk";
import { api } from "../api/client";
import { useGrid } from "../store/grid";

export function CommandBar({
  open, onClose, gridId, onOpenFlow,
}: {
  open: boolean;
  onClose: () => void;
  gridId: string | null;
  onOpenFlow: () => void;
}) {
  const refresh = async () => {
    if (!gridId) return;
    const v = await api.getGrid(gridId);
    useGrid.getState().setView(v);
  };
  const wsId = useGrid((s) => s.workspaceId);
  const focused = useGrid((s) => s.focused);
  const anyStreamingCellId = useGrid((s) => {
    if (!s.view) return null;
    const active = s.view.cells.find((c) =>
      ["retrieving", "drafting", "verifying"].includes(c.status),
    );
    if (active) return active.id;
    // fallback: most recent "done" cell
    const done = [...s.view.cells].reverse().find((c) => c.status === "done");
    return done?.id ?? null;
  });
  if (!open || !gridId) return null;

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-start justify-center pt-24 z-50"
      onClick={onClose}
    >
      <div
        className="w-[560px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <Command label="Command palette">
          <Command.Input
            autoFocus
            placeholder="Type a command…"
            className="w-full bg-transparent p-4 outline-none text-[14px] border-b border-[var(--color-border)]"
          />
          <Command.List className="max-h-80 overflow-auto p-1">
            <Command.Empty className="px-3 py-8 text-center text-[var(--color-muted)] text-[12px]">
              Nothing matches.
            </Command.Empty>
            <Command.Group heading="Actions" className="text-[10px] uppercase tracking-wide text-[var(--color-muted)] px-3 py-2">
              <Command.Item
                className="px-3 py-2 rounded data-[selected=true]:bg-[var(--color-surface-2)] cursor-pointer text-[13px]"
                onSelect={async () => {
                  const p = prompt("Column prompt");
                  if (!p) return;
                  const shape = prompt("Shape (text|number|currency|percentage|list|table)", "text") || "text";
                  await api.addColumn(gridId, p, shape);
                  await refresh();
                  onClose();
                }}
              >
                Add column…
              </Command.Item>
              <Command.Item
                className="px-3 py-2 rounded data-[selected=true]:bg-[var(--color-surface-2)] cursor-pointer text-[13px]"
                onSelect={() => {
                  if (!wsId) return;
                  const inp = document.createElement("input");
                  inp.type = "file";
                  inp.accept = "application/pdf";
                  inp.multiple = true;
                  inp.onchange = async () => {
                    const files = Array.from(inp.files ?? []);
                    for (const f of files) {
                      const up = await api.uploadDocument(wsId, f);
                      await api.addRow(gridId, up.document_id);
                    }
                    await refresh();
                    onClose();
                  };
                  inp.click();
                }}
              >
                Add documents…
              </Command.Item>
            </Command.Group>
            <Command.Group heading="Visualization" className="text-[10px] uppercase tracking-wide text-[var(--color-muted)] px-3 py-2">
              <Command.Item
                className="px-3 py-2 rounded data-[selected=true]:bg-[var(--color-surface-2)] cursor-pointer text-[13px]"
                onSelect={() => {
                  const target = focused ?? anyStreamingCellId;
                  if (!target) {
                    alert("No cell to visualize yet. Add a column so a cell starts streaming, then try again.");
                    return;
                  }
                  useGrid.getState().focus(target);
                  onOpenFlow();
                  onClose();
                }}
              >
                Open 3D flow (live pipeline)
              </Command.Item>
              <Command.Item
                className="px-3 py-2 rounded data-[selected=true]:bg-[var(--color-surface-2)] cursor-pointer text-[13px]"
                onSelect={() => {
                  window.open(api.exportCsvUrl(gridId), "_blank");
                  onClose();
                }}
              >
                Export grid as CSV
              </Command.Item>
              <Command.Item
                className="px-3 py-2 rounded data-[selected=true]:bg-[var(--color-surface-2)] cursor-pointer text-[13px]"
                onSelect={() => {
                  window.open(api.exportJsonUrl(gridId), "_blank");
                  onClose();
                }}
              >
                Export grid as JSON
              </Command.Item>
            </Command.Group>
            <Command.Group heading="Retriever" className="text-[10px] uppercase tracking-wide text-[var(--color-muted)] px-3 py-2">
              {(["naive", "isd", "wiki"] as const).map((m) => (
                <Command.Item
                  key={m}
                  className="px-3 py-2 rounded data-[selected=true]:bg-[var(--color-surface-2)] cursor-pointer text-[13px]"
                  onSelect={async () => {
                    await api.setRetriever(gridId, m);
                    await refresh();
                    onClose();
                  }}
                >
                  Switch to: {m}
                </Command.Item>
              ))}
            </Command.Group>
          </Command.List>
        </Command>
      </div>
    </div>
  );
}
