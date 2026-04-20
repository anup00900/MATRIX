import { useEffect, useRef, useState } from "react";
import { api } from "./api/client";
import { AskBar } from "./components/AskBar";
import { CommandBar } from "./components/CommandBar";
import { FocusPane } from "./components/FocusPane";
import { IngestFlowOverlay } from "./components/IngestFlowOverlay";
import { IngestProgress } from "./components/IngestProgress";
import { InlineFlowPanel } from "./components/InlineFlowPanel";
import { Matrix } from "./components/Matrix";
import { Sidebar } from "./components/Sidebar";
import { SynthesisDock } from "./components/SynthesisDock";
import { TopBar } from "./components/TopBar";
import { useGrid } from "./store/grid";
import type { Session } from "./store/grid";
import { TEMPLATES } from "./templates";
import "./index.css";

export default function App() {
  const [gridId, setGridId] = useState<string | null>(null);
  const {
    setView, upsertCell, setWorkspace, focused, upsertIngest,
    show3D, toggle3D, addSession,
  } = useGrid();
  const workspaceId = useGrid((s) => s.workspaceId);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [flowCellId, setFlowCellId] = useState<string | null>(null);
  const [ingestFlowDocId, setIngestFlowDocId] = useState<string | null>(null);
  const [boot, setBoot] = useState<"idle" | "booting" | "ready" | "error">("idle");
  const [bootErr, setBootErr] = useState<string>("");
  // useRef prevents React StrictMode from double-firing the boot effect
  const booted = useRef(false);

  // Boot: create first workspace+grid if none exists
  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    (async () => {
      setBoot("booting");
      try {
        const ws = await api.createWorkspace("Demo");
        setWorkspace(ws.id);
        const g = await api.createGrid(ws.id, "Financials", "wiki");
        setGridId(g.id);
        addSession({ workspaceId: ws.id, gridId: g.id, name: "Financials", createdAt: Date.now() });
        setBoot("ready");
      } catch (e) {
        setBootErr(String(e));
        setBoot("error");
      }
    })();
  }, [boot, setWorkspace, addSession]);

  // Workspace SSE: ingest progress
  useEffect(() => {
    if (!workspaceId) return;
    const url = `http://127.0.0.1:8000/api/workspaces/${workspaceId}/stream`;
    const es = new EventSource(url);
    es.addEventListener("document", (ev: MessageEvent) => {
      const p = JSON.parse(ev.data);
      upsertIngest({
        document_id: p.document_id,
        filename: p.filename,
        sha: p.sha,
        stage: p.stage,
        page: p.page,
        of: p.of,
        n_pages: p.n_pages,
        sections: p.sections,
        error: p.error,
      });
    });
    return () => es.close();
  }, [workspaceId, upsertIngest]);

  // Grid SSE: cell updates
  useEffect(() => {
    if (!gridId) return;
    (async () => setView(await api.getGrid(gridId)))();
    const es = new EventSource(api.streamUrl(gridId));
    es.addEventListener("cell", (ev: MessageEvent) => {
      const p = JSON.parse(ev.data);
      upsertCell({
        id: p.cell_id,
        status: p.state,
        ...(p.answer !== undefined ? { answer_json: p.answer } : {}),
        ...(p.citations !== undefined ? { citations_json: p.citations } : {}),
        ...(p.confidence !== undefined ? { confidence: p.confidence } : {}),
      });
      if (["retrieving", "drafting", "verifying"].includes(p.state)) {
        setFlowCellId((cur) => cur ?? p.cell_id);
      }
    });
    return () => es.close();
  }, [gridId, setView, upsertCell]);

  // Keyboard shortcuts
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setCmdOpen(true);
      }
      if (e.key === "Escape") {
        if (cmdOpen) setCmdOpen(false);
        else if (ingestFlowDocId) setIngestFlowDocId(null);
        else if (flowCellId) setFlowCellId(null);
        else if (focused) useGrid.getState().focus(null);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [cmdOpen, flowCellId, focused, ingestFlowDocId]);

  // --- Session handlers ---

  const handleNewSession = async () => {
    try {
      const ws = await api.createWorkspace("Session");
      setWorkspace(ws.id);
      const name = `Session ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
      const g = await api.createGrid(ws.id, name, "wiki");
      setGridId(g.id);
      addSession({ workspaceId: ws.id, gridId: g.id, name, createdAt: Date.now() });
    } catch (e) {
      console.error("Failed to create session:", e);
    }
  };

  const handleSwitchSession = (s: Session) => {
    setFlowCellId(null);
    setWorkspace(s.workspaceId);
    setGridId(s.gridId);
  };

  const handleUseTemplate = async (key: string) => {
    if (!gridId) return;
    const cols = TEMPLATES[key as keyof typeof TEMPLATES];
    if (!cols) return;
    for (const c of cols) await api.addColumn(gridId, c.prompt, c.shape);
    setView(await api.getGrid(gridId));
  };

  // --- Render ---

  if (boot === "error") {
    return (
      <div className="h-full flex items-center justify-center p-8">
        <div className="max-w-md text-center space-y-2">
          <div className="text-[var(--color-accent-fail)] text-lg">Cannot reach backend</div>
          <div className="text-[var(--color-muted)] text-[12px] font-[var(--font-mono)] break-all">{bootErr}</div>
          <div className="text-[var(--color-muted)] text-[12px]">
            Start it with <kbd className="px-1 py-0.5 border border-[var(--color-border)] rounded font-[var(--font-mono)]">make backend</kbd>.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <TopBar
        onCommand={() => setCmdOpen(true)}
        show3D={show3D}
        onToggle3D={toggle3D}
      />
      <AskBar gridId={gridId} />
      <IngestProgress onOpen3D={(id) => setIngestFlowDocId(id)} />

      {/* Three-panel body */}
      <div className="flex-1 flex min-h-0 overflow-hidden">
        {/* Left: icon rail + flyout */}
        <Sidebar
          activeGridId={gridId}
          onNewSession={handleNewSession}
          onSwitchSession={handleSwitchSession}
          onUseTemplate={handleUseTemplate}
        />

        {/* Center: grid + focus pane */}
        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex-1 min-h-0 flex overflow-hidden">
            <div className="flex-1 min-w-0 overflow-auto">
              <Matrix />
            </div>
            {focused && <FocusPane onOpenFlow={(id) => setFlowCellId(id)} />}
          </div>
          <SynthesisDock gridId={gridId} />
        </div>

        {/* Right: inline 3D panel */}
        {show3D && (
          <InlineFlowPanel
            cellId={flowCellId}
            onClose={toggle3D}
          />
        )}
      </div>

      <CommandBar
        open={cmdOpen}
        onClose={() => setCmdOpen(false)}
        gridId={gridId}
        onOpenFlow={() => {
          const liveFocus = useGrid.getState().focused;
          setFlowCellId(liveFocus ?? flowCellId);
          if (!show3D) toggle3D();
        }}
      />

      {/* Full-screen overlays (kept for ingest flow only) */}
      {ingestFlowDocId && (
        <IngestFlowOverlay documentId={ingestFlowDocId} onClose={() => setIngestFlowDocId(null)} />
      )}
    </div>
  );
}
