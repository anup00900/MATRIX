import { create } from "zustand";
import type { Cell, GridView } from "../api/types";

interface State {
  view: GridView | null;
  workspaceId: string | null;
  focused: string | null; // cell id
  setWorkspace: (id: string) => void;
  setView: (v: GridView) => void;
  upsertCell: (c: Partial<Cell> & { id: string }) => void;
  focus: (cellId: string | null) => void;
}

export const useGrid = create<State>((set) => ({
  view: null,
  workspaceId: null,
  focused: null,
  setWorkspace: (id) => set({ workspaceId: id }),
  setView: (v) => set({ view: v }),
  upsertCell: (c) =>
    set((s) => {
      if (!s.view) return s;
      const cells = s.view.cells.map((x) => (x.id === c.id ? { ...x, ...c } : x));
      return { view: { ...s.view, cells } };
    }),
  focus: (cellId) => set({ focused: cellId }),
}));
