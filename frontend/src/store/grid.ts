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
