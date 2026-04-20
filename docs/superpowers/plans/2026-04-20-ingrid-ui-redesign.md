# INGRID UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the product to INGRID, add a Hebbia-style icon-rail sidebar with session history and templates, and move the 3D pipeline view from a full-screen overlay into a collapsible inline right panel.

**Architecture:** Three-panel flex layout — 40px icon rail (always visible) | grid (fills remaining) | optional 300px 3D panel on the right. A flyout panel slides over the grid when a sidebar icon is clicked, showing either session history or templates. Sessions are persisted to `localStorage` via Zustand `persist` middleware; no backend changes required.

**Tech Stack:** React 18, TypeScript, Zustand 5 (with `persist`), Three.js, Tailwind CSS, Vite, pnpm

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `frontend/src/store/grid.ts` | Modify | Add `sessions`, `sidebarView`, `show3D`, actions; wrap store with `persist` |
| `frontend/index.html` | Modify | `<title>INGRID</title>` |
| `frontend/src/components/TopBar.tsx` | Modify | Rename brand text; add `[⬡ 3D]` toggle button |
| `frontend/src/components/CommandBar.tsx` | Modify | Remove Templates group |
| `frontend/src/components/FlowOverlay.tsx` | Modify | Add `variant?: 'overlay' \| 'panel'` prop to support inline rendering |
| `frontend/src/components/InlineFlowPanel.tsx` | Create | Right-panel wrapper hosting `FlowOverlay` in `panel` mode |
| `frontend/src/components/TemplateList.tsx` | Create | Three template cards with "Use template" action |
| `frontend/src/components/SessionList.tsx` | Create | Session rows grouped by Today/Yesterday + "New session" button |
| `frontend/src/components/Sidebar.tsx` | Create | 40px icon rail + flyout panel controller |
| `frontend/src/App.tsx` | Modify | Three-panel layout; `onNewSession` / `onSwitchSession` handlers |

---

## Task 1: Extend the Zustand store

**Files:**
- Modify: `frontend/src/store/grid.ts`

Add three new pieces of state: `sessions` (persisted to localStorage), `sidebarView` (which flyout is open), and `show3D` (inline 3D panel toggle). Use Zustand's `persist` middleware to automatically save/load `sessions`.

- [ ] **Step 1: Replace the full content of `frontend/src/store/grid.ts`**

```typescript
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Cell, GridView } from "../api/types";

export type IngestStage =
  | "queued"
  | "parsing"
  | "indexing"
  | "wiki"
  | "ready"
  | "failed";

export interface IngestProgress {
  document_id: string;
  filename: string;
  sha: string;
  stage: IngestStage;
  page?: number;
  of?: number;
  n_pages?: number;
  sections?: number;
  error?: string;
  updated_at: number;
}

export interface Session {
  workspaceId: string;
  gridId: string;
  name: string;
  createdAt: number; // unix ms
}

export type SidebarView = "sessions" | "templates" | null;

interface State {
  view: GridView | null;
  workspaceId: string | null;
  focused: string | null;
  ingests: Record<string, IngestProgress>;
  sessions: Session[];
  sidebarView: SidebarView;
  show3D: boolean;

  setWorkspace: (id: string) => void;
  setView: (v: GridView) => void;
  upsertCell: (c: Partial<Cell> & { id: string }) => void;
  focus: (cellId: string | null) => void;
  upsertIngest: (p: Partial<IngestProgress> & { document_id: string }) => void;
  clearDoneIngests: () => void;
  addSession: (s: Session) => void;
  setSidebarView: (v: SidebarView) => void;
  toggleSidebarView: (v: "sessions" | "templates") => void;
  toggle3D: () => void;
}

export const useGrid = create<State>()(
  persist(
    (set) => ({
      view: null,
      workspaceId: null,
      focused: null,
      ingests: {},
      sessions: [],
      sidebarView: null,
      show3D: false,

      setWorkspace: (id) => set({ workspaceId: id }),
      setView: (v) => set({ view: v }),
      upsertCell: (c) =>
        set((s) => {
          if (!s.view) return s;
          const cells = s.view.cells.map((x) => (x.id === c.id ? { ...x, ...c } : x));
          return { view: { ...s.view, cells } };
        }),
      focus: (cellId) => set({ focused: cellId }),
      upsertIngest: (p) =>
        set((s) => {
          const prev = s.ingests[p.document_id];
          const merged: IngestProgress = {
            document_id: p.document_id,
            filename: p.filename ?? prev?.filename ?? "(uploading…)",
            sha: p.sha ?? prev?.sha ?? "",
            stage: (p.stage as IngestStage) ?? prev?.stage ?? "queued",
            page: p.page ?? prev?.page,
            of: p.of ?? prev?.of,
            n_pages: p.n_pages ?? prev?.n_pages,
            sections: p.sections ?? prev?.sections,
            error: p.error ?? prev?.error,
            updated_at: Date.now(),
          };
          return { ingests: { ...s.ingests, [p.document_id]: merged } };
        }),
      clearDoneIngests: () =>
        set((s) => {
          const next: Record<string, IngestProgress> = {};
          for (const [k, v] of Object.entries(s.ingests)) {
            if (v.stage !== "ready" && v.stage !== "failed") next[k] = v;
          }
          return { ingests: next };
        }),
      addSession: (s) =>
        set((st) => ({ sessions: [s, ...st.sessions] })),
      setSidebarView: (v) => set({ sidebarView: v }),
      toggleSidebarView: (v) =>
        set((s) => ({ sidebarView: s.sidebarView === v ? null : v })),
      toggle3D: () => set((s) => ({ show3D: !s.show3D })),
    }),
    {
      name: "ingrid-storage",
      partialize: (s) => ({ sessions: s.sessions }),
    },
  ),
);
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC/frontend"
PATH="$HOME/.local/node22/bin:$PATH" pnpm exec tsc --noEmit
```

Expected: no errors (or only pre-existing errors unrelated to this file).

- [ ] **Step 3: Commit**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC"
git add frontend/src/store/grid.ts
git commit -m "feat(store): add sessions, sidebarView, show3D state with localStorage persist"
```

---

## Task 2: Branding — rename Matrix → INGRID

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/src/components/TopBar.tsx` (brand text only — TopBar gets more changes in Task 3)

- [ ] **Step 1: Update `frontend/index.html` title**

Replace:
```html
<title>frontend</title>
```
With:
```html
<title>INGRID</title>
```

- [ ] **Step 2: Update brand text in `frontend/src/components/TopBar.tsx`**

Find line:
```tsx
<div className="font-[var(--font-ui)] text-[var(--color-text)] tracking-tight">◇ Matrix</div>
```

Replace with:
```tsx
<div className="font-[var(--font-ui)] text-[var(--color-text)] tracking-tight">◇ INGRID</div>
```

- [ ] **Step 3: Verify**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC/frontend"
PATH="$HOME/.local/node22/bin:$PATH" pnpm exec tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC"
git add frontend/index.html frontend/src/components/TopBar.tsx
git commit -m "feat(brand): rename Matrix → INGRID in title and topbar"
```

---

## Task 3: Add 3D toggle button to TopBar

**Files:**
- Modify: `frontend/src/components/TopBar.tsx`

TopBar needs two new props (`show3D`, `onToggle3D`) and renders a `[⬡ 3D]` button next to the existing CSV button.

- [ ] **Step 1: Replace the full content of `frontend/src/components/TopBar.tsx`**

```tsx
import { Command, Download, Activity } from "lucide-react";
import { api } from "../api/client";
import { useGrid } from "../store/grid";

interface Props {
  onCommand: () => void;
  show3D: boolean;
  onToggle3D: () => void;
}

export function TopBar({ onCommand, show3D, onToggle3D }: Props) {
  const v = useGrid((s) => s.view);
  const mode = v?.grid.retriever_mode;
  const modeLabel = mode === "wiki" ? "Wiki" : mode === "isd" ? "ISD" : mode === "naive" ? "Naive" : "—";
  const modeColor =
    mode === "wiki" ? "text-[var(--color-accent-streaming)]" :
    mode === "isd" ? "text-[var(--color-accent-verify)]" :
    "text-[var(--color-muted)]";

  const cells = useGrid((s) => s.view?.cells);
  const activity = { retrieving: 0, drafting: 0, verifying: 0, done: 0, failed: 0, total: 0 };
  for (const c of cells ?? []) {
    activity.total += 1;
    if (c.status === "retrieving") activity.retrieving += 1;
    else if (c.status === "drafting") activity.drafting += 1;
    else if (c.status === "verifying") activity.verifying += 1;
    else if (c.status === "done") activity.done += 1;
    else if (c.status === "failed") activity.failed += 1;
  }
  const busy = activity.retrieving + activity.drafting + activity.verifying;

  return (
    <div className="h-11 border-b border-[var(--color-border)] px-4 flex items-center gap-3
                    text-[12px] bg-[var(--color-canvas)]/80 backdrop-blur sticky top-0 z-10">
      <div className="font-[var(--font-ui)] text-[var(--color-text)] tracking-tight">◇ INGRID</div>
      <div className="h-3 w-px bg-[var(--color-border)]" />
      <div className="text-[var(--color-muted)]">{v?.grid.name ?? "new grid"}</div>
      <div className="h-3 w-px bg-[var(--color-border)]" />
      <div className="text-[var(--color-muted)] font-[var(--font-mono)]">gpt-4.1</div>
      <div className={`px-1.5 py-0.5 rounded text-[10px] font-[var(--font-mono)] uppercase tracking-wide border border-[var(--color-border)] ${modeColor}`}>
        {modeLabel}
      </div>

      <div className="h-3 w-px bg-[var(--color-border)]" />
      <div className="flex items-center gap-2 font-[var(--font-mono)] text-[11px]">
        <Activity className={`w-3 h-3 ${busy > 0 ? "text-[var(--color-accent-streaming)] animate-pulse" : "text-[var(--color-muted)]"}`} />
        {busy > 0 ? (
          <>
            {activity.retrieving > 0 && (
              <span className="text-[var(--color-accent-streaming)]">{activity.retrieving} retrieving</span>
            )}
            {activity.drafting > 0 && (
              <span className="text-[var(--color-accent-streaming)]">· {activity.drafting} drafting</span>
            )}
            {activity.verifying > 0 && (
              <span className="text-[var(--color-accent-verify)]">· {activity.verifying} verifying</span>
            )}
          </>
        ) : (
          <span className="text-[var(--color-muted)]">idle</span>
        )}
        <span className="text-[var(--color-muted)]">· {activity.done}/{activity.total} done</span>
      </div>

      <div className="flex-1" />

      {v && (
        <a
          href={api.exportCsvUrl(v.grid.id)}
          className="px-2.5 py-1 rounded border border-[var(--color-border)] text-[var(--color-muted)]
                     hover:text-[var(--color-text)] hover:border-[var(--color-muted)] transition
                     flex items-center gap-1.5 font-[var(--font-mono)]"
          title="Export grid as CSV"
        >
          <Download className="w-3 h-3" /> CSV
        </a>
      )}

      <button
        onClick={onToggle3D}
        className={`px-2.5 py-1 rounded border transition flex items-center gap-1.5 font-[var(--font-mono)]
          ${show3D
            ? "border-[var(--color-accent-streaming)] text-[var(--color-accent-streaming)] bg-[var(--color-accent-streaming)]/10"
            : "border-[var(--color-border)] text-[var(--color-muted)] hover:text-[var(--color-text)] hover:border-[var(--color-muted)]"
          }`}
        title="Toggle 3D pipeline view"
        aria-pressed={show3D}
      >
        ⬡ 3D
      </button>

      <button
        onClick={onCommand}
        className="px-2.5 py-1 rounded border border-[var(--color-border)] text-[var(--color-muted)]
                   hover:text-[var(--color-text)] hover:border-[var(--color-muted)] transition
                   flex items-center gap-1.5 font-[var(--font-mono)]"
        aria-label="Open command palette"
      >
        <Command className="w-3 h-3" /> K
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Verify**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC/frontend"
PATH="$HOME/.local/node22/bin:$PATH" pnpm exec tsc --noEmit
```

Expected: type error in `App.tsx` because `TopBar` now requires `show3D`/`onToggle3D` — that's fine, we fix App in Task 10.

- [ ] **Step 3: Commit**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC"
git add frontend/src/components/TopBar.tsx
git commit -m "feat(topbar): add 3D toggle button with active state styling"
```

---

## Task 4: Remove Templates from CommandBar

**Files:**
- Modify: `frontend/src/components/CommandBar.tsx`

Delete the `<Command.Group heading="Templates">` block and its import of `TEMPLATES`. Templates now live in the sidebar.

- [ ] **Step 1: Remove the Templates group and TEMPLATES import**

In `frontend/src/components/CommandBar.tsx`:

Remove this import line at the top:
```typescript
import { TEMPLATES } from "../templates";
```

Remove this entire JSX block (from `<Command.Group heading="Templates"` to its closing `</Command.Group>`):
```tsx
            <Command.Group heading="Templates" className="text-[10px] uppercase tracking-wide text-[var(--color-muted)] px-3 py-2">
              {Object.entries(TEMPLATES).map(([name, cols]) => (
                <Command.Item
                  key={name}
                  className="px-3 py-2 rounded data-[selected=true]:bg-[var(--color-surface-2)] cursor-pointer text-[13px]"
                  onSelect={async () => {
                    for (const c of cols) await api.addColumn(gridId, c.prompt, c.shape);
                    await refresh();
                    onClose();
                  }}
                >
                  Template · {name}{" "}
                  <span className="text-[var(--color-muted)] text-[11px]">· {cols.length} cols</span>
                </Command.Item>
              ))}
            </Command.Group>
```

- [ ] **Step 2: Verify**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC/frontend"
PATH="$HOME/.local/node22/bin:$PATH" pnpm exec tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC"
git add frontend/src/components/CommandBar.tsx
git commit -m "feat(command-bar): remove Templates group (moved to sidebar)"
```

---

## Task 5: Adapt FlowOverlay for inline panel mode

**Files:**
- Modify: `frontend/src/components/FlowOverlay.tsx`

Add a `variant?: 'overlay' | 'panel'` prop. In `panel` mode: no full-screen wrapper, no inner topbar, canvas fills the container. Everything else (Three.js scene, legend, answer card) is unchanged.

- [ ] **Step 1: Update the Props interface and component signature**

Find:
```typescript
interface Props {
  cellId: string | null;
  onClose: () => void;
}

export function FlowOverlay({ cellId, onClose }: Props) {
```

Replace with:
```typescript
interface Props {
  cellId: string | null;
  onClose: () => void;
  variant?: "overlay" | "panel";
}

export function FlowOverlay({ cellId, onClose, variant = "overlay" }: Props) {
```

- [ ] **Step 2: Update the root div className**

Find:
```tsx
  return (
    <div className="fixed inset-0 z-50 bg-[var(--color-canvas)]">
```

Replace with:
```tsx
  return (
    <div className={
      variant === "overlay"
        ? "fixed inset-0 z-50 bg-[var(--color-canvas)]"
        : "h-full w-full relative bg-[var(--color-canvas)]"
    }>
```

- [ ] **Step 3: Wrap the topbar in an overlay-only conditional**

Find:
```tsx
      {/* top bar */}
      <div className="h-11 flex items-center justify-between px-4 border-b border-[var(--color-border)] bg-[var(--color-canvas)]/80 backdrop-blur">
```

Replace with:
```tsx
      {/* top bar — overlay mode only */}
      {variant === "overlay" && (
      <div className="h-11 flex items-center justify-between px-4 border-b border-[var(--color-border)] bg-[var(--color-canvas)]/80 backdrop-blur">
```

Then find the closing tag of that topbar block. It ends at the `</div>` that closes the top bar div. The topbar block ends just before `{/* the three.js canvas container */}`. Add a closing `)}` after that `</div>`:

Find:
```tsx
        </button>
      </div>

      {/* the three.js canvas container */}
```

Replace with:
```tsx
        </button>
      </div>
      )}

      {/* the three.js canvas container */}
```

- [ ] **Step 4: Update the canvas container's top offset for panel mode**

Find:
```tsx
      {/* the three.js canvas container */}
      <div ref={containerRef} className="absolute inset-0 top-11" />
```

Replace with:
```tsx
      {/* the three.js canvas container */}
      <div ref={containerRef} className={variant === "overlay" ? "absolute inset-0 top-11" : "absolute inset-0"} />
```

- [ ] **Step 5: Verify**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC/frontend"
PATH="$HOME/.local/node22/bin:$PATH" pnpm exec tsc --noEmit
```

- [ ] **Step 6: Commit**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC"
git add frontend/src/components/FlowOverlay.tsx
git commit -m "feat(flow-overlay): add panel variant for inline rendering"
```

---

## Task 6: Create InlineFlowPanel

**Files:**
- Create: `frontend/src/components/InlineFlowPanel.tsx`

A 300px right panel with a slim header (title + close button) and `FlowOverlay` in `panel` mode filling the rest.

- [ ] **Step 1: Create `frontend/src/components/InlineFlowPanel.tsx`**

```tsx
import { X } from "lucide-react";
import { FlowOverlay } from "./FlowOverlay";
import { useGrid } from "../store/grid";
import type { CellStatus } from "../api/types";

interface Props {
  cellId: string | null;
  onClose: () => void;
}

const STATUS_DOT: Record<CellStatus, string> = {
  idle: "bg-zinc-500",
  queued: "bg-zinc-500",
  retrieving: "bg-[var(--color-accent-streaming)] animate-pulse",
  drafting: "bg-[var(--color-accent-streaming)] animate-pulse",
  verifying: "bg-[var(--color-accent-verify)] animate-pulse",
  done: "bg-[var(--color-accent-done)]",
  stale: "bg-[var(--color-accent-stale)]",
  failed: "bg-[var(--color-accent-fail)]",
};

export function InlineFlowPanel({ cellId, onClose }: Props) {
  const cell = useGrid((s) => {
    if (!cellId || !s.view) return undefined;
    return s.view.cells.find((c) => c.id === cellId);
  });
  const status: CellStatus = cell?.status ?? "idle";

  return (
    <div className="w-[300px] flex-shrink-0 border-l border-[var(--color-border)] flex flex-col h-full">
      {/* panel header */}
      <div className="h-9 flex items-center justify-between px-3 border-b border-[var(--color-border)] bg-[var(--color-surface)]/80 backdrop-blur flex-shrink-0">
        <div className="flex items-center gap-2 text-[11px] font-[var(--font-mono)]">
          <span className="text-[var(--color-accent-streaming)]">⬡</span>
          <span className="text-[var(--color-muted)]">3D Pipeline</span>
          {cell && (
            <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT[status]}`} />
          )}
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded text-[var(--color-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-surface-2)] transition"
          aria-label="Close 3D panel"
        >
          <X className="w-3 h-3" />
        </button>
      </div>

      {/* scene */}
      <div className="flex-1 relative overflow-hidden">
        <FlowOverlay cellId={cellId} onClose={onClose} variant="panel" />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC/frontend"
PATH="$HOME/.local/node22/bin:$PATH" pnpm exec tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC"
git add frontend/src/components/InlineFlowPanel.tsx
git commit -m "feat: InlineFlowPanel — 300px right panel hosting 3D scene"
```

---

## Task 7: Create TemplateList

**Files:**
- Create: `frontend/src/components/TemplateList.tsx`

Three template cards. "Use template" calls back with the template key so the caller (App.tsx) can create the columns.

- [ ] **Step 1: Create `frontend/src/components/TemplateList.tsx`**

```tsx
import { TEMPLATES } from "../templates";

interface Props {
  onUse: (key: string) => void;
}

const DESCRIPTIONS: Record<string, string> = {
  "Risk extraction": "Material risk factors, supply chain, cybersecurity, legal exposure",
  "Revenue & margins": "Revenue, YoY growth %, operating and gross margins",
  "Auditor & governance": "Auditor name, fees, CEO compensation, board composition",
};

export function TemplateList({ onUse }: Props) {
  return (
    <div className="flex flex-col gap-1 p-3">
      <div className="text-[9px] uppercase tracking-widest text-[var(--color-muted)] px-1 mb-1">
        Templates
      </div>
      {Object.entries(TEMPLATES).map(([name, cols]) => (
        <div
          key={name}
          className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-3 flex flex-col gap-2
                     hover:border-[var(--color-muted)] transition"
        >
          <div className="flex items-start justify-between gap-2">
            <div>
              <div className="text-[12px] font-medium text-[var(--color-text)]">{name}</div>
              <div className="text-[10px] text-[var(--color-muted)] mt-0.5 leading-snug">
                {DESCRIPTIONS[name] ?? `${cols.length} columns`}
              </div>
            </div>
            <span className="text-[9px] font-[var(--font-mono)] text-[var(--color-muted)] border border-[var(--color-border)] px-1.5 py-0.5 rounded flex-shrink-0">
              {cols.length} cols
            </span>
          </div>
          <button
            onClick={() => onUse(name)}
            className="w-full py-1.5 rounded border border-[var(--color-border)] text-[11px] text-[var(--color-muted)]
                       hover:bg-[var(--color-surface-2)] hover:text-[var(--color-text)] transition font-[var(--font-mono)]"
          >
            Use template
          </button>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Verify**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC/frontend"
PATH="$HOME/.local/node22/bin:$PATH" pnpm exec tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC"
git add frontend/src/components/TemplateList.tsx
git commit -m "feat: TemplateList component with 3 template cards"
```

---

## Task 8: Create SessionList

**Files:**
- Create: `frontend/src/components/SessionList.tsx`

Session rows grouped by Today/Yesterday/Older. "New session" button at top. Active session highlighted.

- [ ] **Step 1: Create `frontend/src/components/SessionList.tsx`**

```tsx
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
```

- [ ] **Step 2: Verify**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC/frontend"
PATH="$HOME/.local/node22/bin:$PATH" pnpm exec tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC"
git add frontend/src/components/SessionList.tsx
git commit -m "feat: SessionList with Today/Yesterday grouping and new session button"
```

---

## Task 9: Create Sidebar

**Files:**
- Create: `frontend/src/components/Sidebar.tsx`

40px icon rail (always visible). Clicking an icon toggles the flyout; clicking the active icon closes it. Flyout renders `SessionList` or `TemplateList` over the grid.

- [ ] **Step 1: Create `frontend/src/components/Sidebar.tsx`**

```tsx
import { LayoutGrid, FileText } from "lucide-react";
import { useGrid } from "../store/grid";
import type { Session } from "../store/grid";
import { SessionList } from "./SessionList";
import { TemplateList } from "./TemplateList";

interface Props {
  activeGridId: string | null;
  onNewSession: () => void;
  onSwitchSession: (s: Session) => void;
  onUseTemplate: (key: string) => void;
}

export function Sidebar({ activeGridId, onNewSession, onSwitchSession, onUseTemplate }: Props) {
  const { sidebarView, toggleSidebarView, setSidebarView, sessions } = useGrid();

  return (
    <div className="relative flex-shrink-0 z-20">
      {/* 40px icon rail */}
      <div className="w-10 h-full flex flex-col items-center py-3 gap-1
                      border-r border-[var(--color-border)] bg-[var(--color-canvas)]">
        {/* Logo / home */}
        <div className="w-7 h-7 flex items-center justify-center text-[var(--color-accent-streaming)] text-[14px] mb-2 select-none">
          ◇
        </div>

        <button
          onClick={() => toggleSidebarView("sessions")}
          title="Sessions"
          aria-pressed={sidebarView === "sessions"}
          className={`w-7 h-7 rounded-md flex items-center justify-center transition
            ${sidebarView === "sessions"
              ? "bg-[var(--color-accent-streaming)]/15 text-[var(--color-accent-streaming)]"
              : "text-[var(--color-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-surface)]"
            }`}
        >
          <LayoutGrid className="w-3.5 h-3.5" />
        </button>

        <button
          onClick={() => toggleSidebarView("templates")}
          title="Templates"
          aria-pressed={sidebarView === "templates"}
          className={`w-7 h-7 rounded-md flex items-center justify-center transition
            ${sidebarView === "templates"
              ? "bg-[var(--color-accent-streaming)]/15 text-[var(--color-accent-streaming)]"
              : "text-[var(--color-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-surface)]"
            }`}
        >
          <FileText className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Flyout panel — overlays the grid */}
      {sidebarView !== null && (
        <>
          {/* backdrop — click to close */}
          <div
            className="fixed inset-0 z-10"
            onClick={() => setSidebarView(null)}
          />
          <div
            className="absolute top-0 left-10 z-20 w-56 h-full
                       border-r border-[var(--color-border)] bg-[var(--color-canvas)]
                       shadow-2xl overflow-y-auto"
            style={{ maxHeight: "100vh" }}
            onClick={(e) => e.stopPropagation()}
          >
            {sidebarView === "sessions" && (
              <SessionList
                sessions={sessions}
                activeGridId={activeGridId}
                onNewSession={() => { setSidebarView(null); onNewSession(); }}
                onSwitchSession={(s) => { setSidebarView(null); onSwitchSession(s); }}
              />
            )}
            {sidebarView === "templates" && (
              <TemplateList
                onUse={(key) => { setSidebarView(null); onUseTemplate(key); }}
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC/frontend"
PATH="$HOME/.local/node22/bin:$PATH" pnpm exec tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC"
git add frontend/src/components/Sidebar.tsx
git commit -m "feat: Sidebar with 40px icon rail and flyout for sessions/templates"
```

---

## Task 10: Wire App.tsx — three-panel layout

**Files:**
- Modify: `frontend/src/App.tsx`

Replace the current layout with the three-panel shell. Add `onNewSession`, `onSwitchSession`, `onUseTemplate` handlers. Wire `show3D`/`toggle3D` through TopBar and InlineFlowPanel.

- [ ] **Step 1: Replace the full content of `frontend/src/App.tsx`**

```tsx
import { useEffect, useState } from "react";
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

  // Boot: create first workspace+grid if none exists
  useEffect(() => {
    if (boot !== "idle") return;
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

  const handleSwitchSession = async (s: Session) => {
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
```

- [ ] **Step 2: Verify TypeScript compiles with no errors**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC/frontend"
PATH="$HOME/.local/node22/bin:$PATH" pnpm exec tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Start dev server and verify visually**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC/frontend"
PATH="$HOME/.local/node22/bin:$PATH" pnpm dev
```

Open http://localhost:5173 and check:
- [ ] Page title shows "INGRID" in browser tab
- [ ] TopBar shows "◇ INGRID" (not "◇ Matrix")
- [ ] 40px icon rail visible on left with `◇`, grid icon, templates icon
- [ ] Clicking grid icon opens session flyout with "New session" button
- [ ] Clicking templates icon opens template cards flyout
- [ ] Clicking `[⬡ 3D]` in TopBar opens 300px right panel with 3D scene
- [ ] Clicking `[⬡ 3D]` again closes the panel
- [ ] "Use template" on a template card adds columns to the current grid
- [ ] ⌘K command palette no longer shows Templates group

- [ ] **Step 4: Commit**

```bash
cd "/Users/anup.roy/Downloads/Hebbia POC"
git add frontend/src/App.tsx
git commit -m "feat(app): three-panel layout — icon rail sidebar, inline 3D panel, session switching"
```
