import { useState } from "react";
import { Sparkles, Plus, X, Loader2 } from "lucide-react";
import { api } from "../api/client";
import { useGrid } from "../store/grid";
import { cn } from "../lib/utils";

type Shape = "text" | "number" | "currency" | "percentage" | "list" | "table";

interface Suggestion {
  prompt: string;
  shape_hint: Shape;
}

export function AskBar({ gridId }: { gridId: string | null }) {
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [err, setErr] = useState("");
  const refresh = async () => {
    if (!gridId) return;
    const v = await api.getGrid(gridId);
    useGrid.getState().setView(v);
  };

  const suggest = async () => {
    if (!gridId || !prompt.trim()) return;
    setErr("");
    setLoading(true);
    try {
      const res = await api.suggestColumns(gridId, prompt);
      setSuggestions(res.columns as Suggestion[]);
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  };

  const addOne = async (s: Suggestion) => {
    if (!gridId) return;
    await api.addColumn(gridId, s.prompt, s.shape_hint);
    setSuggestions((arr) => arr.filter((x) => x !== s));
    await refresh();
  };

  const addAll = async () => {
    if (!gridId) return;
    for (const s of suggestions) await api.addColumn(gridId, s.prompt, s.shape_hint);
    setSuggestions([]);
    setPrompt("");
    await refresh();
  };

  return (
    <div className="border-b border-[var(--color-border)] bg-[var(--color-surface)]/50 backdrop-blur px-4 py-3">
      <div className="flex items-center gap-2">
        <Sparkles className="w-3.5 h-3.5 text-[var(--color-accent-streaming)] shrink-0" />
        <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted)] shrink-0">
          Ask the grid
        </div>
        <input
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              suggest();
            }
          }}
          placeholder='e.g. "give me a financial summary" or "what are the material risks"'
          className={cn(
            "flex-1 min-w-0 bg-transparent outline-none text-[13px]",
            "placeholder:text-[var(--color-muted)]",
          )}
        />
        <button
          onClick={suggest}
          disabled={loading || !prompt.trim() || !gridId}
          className={cn(
            "px-3 py-1.5 text-[11px] rounded border transition flex items-center gap-1.5",
            "border-[var(--color-accent-streaming)] text-[var(--color-accent-streaming)]",
            "hover:bg-[var(--color-accent-streaming)]/10",
            "disabled:opacity-40 disabled:cursor-not-allowed",
          )}
        >
          {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
          {loading ? "thinking…" : "suggest columns"}
        </button>
      </div>

      {err && (
        <div className="mt-2 text-[11px] text-[var(--color-accent-fail)] font-[var(--font-mono)]">
          {err}
        </div>
      )}

      {suggestions.length > 0 && (
        <div className="mt-3 space-y-2">
          <div className="flex items-center justify-between">
            <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted)]">
              Suggested columns · {suggestions.length}
            </div>
            <div className="flex gap-1">
              <button
                onClick={addAll}
                className="px-2 py-1 text-[11px] rounded border border-[var(--color-accent-done)]
                           text-[var(--color-accent-done)] hover:bg-[var(--color-accent-done)]/10"
              >
                add all
              </button>
              <button
                onClick={() => setSuggestions([])}
                className="px-2 py-1 text-[11px] rounded border border-[var(--color-border)]
                           text-[var(--color-muted)] hover:text-[var(--color-text)]"
              >
                dismiss
              </button>
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {suggestions.map((s, i) => (
              <div
                key={i}
                className={cn(
                  "group flex items-center gap-2 pl-3 pr-1 py-1 rounded-full border",
                  "border-[var(--color-border)] bg-[var(--color-canvas)]",
                  "text-[12px] hover:border-[var(--color-accent-streaming)] transition",
                )}
              >
                <span className="truncate max-w-[360px]">{s.prompt}</span>
                <span className="text-[10px] font-[var(--font-mono)] text-[var(--color-muted)]">
                  {s.shape_hint}
                </span>
                <button
                  onClick={() => addOne(s)}
                  className="p-1 rounded-full hover:bg-[var(--color-surface)]"
                  title="Add this column"
                >
                  <Plus className="w-3 h-3 text-[var(--color-accent-done)]" />
                </button>
                <button
                  onClick={() => setSuggestions((arr) => arr.filter((_, j) => j !== i))}
                  className="p-1 rounded-full hover:bg-[var(--color-surface)]"
                  title="Dismiss"
                >
                  <X className="w-3 h-3 text-[var(--color-muted)]" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
