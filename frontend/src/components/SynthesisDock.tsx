import { useState } from "react";
import { ChevronDown, ChevronUp, Sparkles } from "lucide-react";
import { cn } from "../lib/utils";

interface Props {
  gridId: string | null;
}

export function SynthesisDock({ gridId }: Props) {
  const [open, setOpen] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [out, setOut] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const run = async () => {
    if (!gridId || !prompt.trim()) return;
    setErr("");
    setLoading(true);
    try {
      const r = await fetch(
        `http://127.0.0.1:8000/api/grids/${gridId}/synthesize`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ prompt }),
        },
      );
      if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
      const body = await r.json();
      setOut(body.answer ?? "");
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="border-t border-[var(--color-border)] bg-[var(--color-surface)] shrink-0">
      <button
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "w-full px-4 py-2 text-left text-[11px] uppercase tracking-wide",
          "text-[var(--color-muted)] hover:text-[var(--color-text)] flex items-center gap-2",
        )}
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronUp className="w-3 h-3" />}
        <Sparkles className="w-3 h-3" /> Synthesis
      </button>
      {open && (
        <div className="px-4 pb-4 space-y-3">
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Summarise across these rows…"
            className={cn(
              "w-full h-20 p-3 text-[13px] bg-[var(--color-canvas)] rounded",
              "border border-[var(--color-border)] outline-none",
              "focus:border-[var(--color-accent-streaming)] resize-none font-[var(--font-ui)]",
            )}
          />
          <div className="flex items-center gap-2">
            <button
              onClick={run}
              disabled={loading || !prompt.trim()}
              className={cn(
                "px-3 py-1 text-[12px] rounded border transition",
                "border-[var(--color-accent-streaming)] text-[var(--color-accent-streaming)]",
                "hover:bg-[var(--color-accent-streaming)]/10 disabled:opacity-40 disabled:cursor-not-allowed",
              )}
            >
              {loading ? "Synthesising…" : "Run synthesis"}
            </button>
            {err && (
              <span className="text-[var(--color-accent-fail)] text-[11px] font-[var(--font-mono)] truncate">
                {err}
              </span>
            )}
          </div>
          {out && (
            <div className="p-3 bg-[var(--color-canvas)] border border-[var(--color-border)] rounded text-[13px] whitespace-pre-wrap leading-relaxed">
              {out}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
