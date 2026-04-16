import { useEffect, useState } from "react";
import { api } from "./api/client";
import { CommandBar } from "./components/CommandBar";
import { FocusPane } from "./components/FocusPane";
import { Matrix } from "./components/Matrix";
import { SynthesisDock } from "./components/SynthesisDock";
import { TopBar } from "./components/TopBar";
import { useGrid } from "./store/grid";
import "./index.css";

export default function App() {
  const [gridId, setGridId] = useState<string | null>(null);
  const { setView, upsertCell, setWorkspace, focused } = useGrid();
  const [cmdOpen, setCmdOpen] = useState(false);
  const [boot, setBoot] = useState<"idle" | "booting" | "ready" | "error">("idle");
  const [bootErr, setBootErr] = useState<string>("");

  useEffect(() => {
    if (boot !== "idle") return;
    (async () => {
      setBoot("booting");
      try {
        const ws = await api.createWorkspace("Demo");
        setWorkspace(ws.id);
        const g = await api.createGrid(ws.id, "Financials", "wiki");
        setGridId(g.id);
        setBoot("ready");
      } catch (e) {
        setBootErr(String(e));
        setBoot("error");
      }
    })();
  }, [boot, setWorkspace]);

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
    });
    return () => es.close();
  }, [gridId, setView, upsertCell]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setCmdOpen(true);
      }
      if (e.key === "Escape") {
        if (cmdOpen) setCmdOpen(false);
        else if (focused) useGrid.getState().focus(null);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  if (boot === "error") {
    return (
      <div className="h-full flex items-center justify-center p-8">
        <div className="max-w-md text-center space-y-2">
          <div className="text-[--color-accent-fail] text-lg">Cannot reach backend</div>
          <div className="text-[--color-muted] text-[12px] font-[--font-mono] break-all">{bootErr}</div>
          <div className="text-[--color-muted] text-[12px]">
            Start it with <kbd className="px-1 py-0.5 border border-[--color-border] rounded font-[--font-mono]">make backend</kbd>.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <TopBar onCommand={() => setCmdOpen(true)} />
      <div className="flex-1 flex min-h-0">
        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex-1 min-h-0 overflow-auto">
            <Matrix />
          </div>
          <SynthesisDock gridId={gridId} />
        </div>
        {focused && <FocusPane />}
      </div>
      <CommandBar open={cmdOpen} onClose={() => setCmdOpen(false)} gridId={gridId} />
    </div>
  );
}
