import type { Column, Document, Grid, GridView, Row, Workspace } from "./types";

const BASE = "http://127.0.0.1:8000/api";

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

export const api = {
  createWorkspace: (name: string) =>
    fetch(`${BASE}/workspaces`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name }),
    }).then(j) as Promise<Workspace>,

  uploadDocument: async (wsId: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch(`${BASE}/workspaces/${wsId}/documents`, {
      method: "POST",
      body: fd,
    });
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    return r.json() as Promise<{ document_id: string }>;
  },

  listDocuments: (wsId: string) =>
    fetch(`${BASE}/workspaces/${wsId}/documents`).then(j) as Promise<Document[]>,

  createGrid: (workspace_id: string, name: string, retriever_mode = "wiki") =>
    fetch(`${BASE}/grids`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ workspace_id, name, retriever_mode }),
    }).then(j) as Promise<Grid>,

  getGrid: (gridId: string) =>
    fetch(`${BASE}/grids/${gridId}`).then(j) as Promise<GridView>,

  setRetriever: (gridId: string, mode: string) =>
    fetch(`${BASE}/grids/${gridId}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ retriever_mode: mode }),
    }).then(j),

  addRow: (gridId: string, docId: string) =>
    fetch(`${BASE}/grids/${gridId}/rows/${docId}`, { method: "POST" }).then(
      j,
    ) as Promise<Row>,

  addColumn: (gridId: string, prompt: string, shape_hint: string) =>
    fetch(`${BASE}/grids/${gridId}/columns`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ prompt, shape_hint }),
    }).then(j) as Promise<Column>,

  editColumn: (columnId: string, body: { prompt?: string; shape_hint?: string }) =>
    fetch(`${BASE}/columns/${columnId}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }).then(j) as Promise<Column>,

  rerunCell: (cellId: string) =>
    fetch(`${BASE}/cells/${cellId}/rerun`, { method: "POST" }).then(j) as Promise<{
      ok: boolean;
    }>,

  suggestColumns: (gridId: string, prompt: string) =>
    fetch(`${BASE}/grids/${gridId}/suggest-columns`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ prompt }),
    }).then(j) as Promise<{ columns: Array<{ prompt: string; shape_hint: string }> }>,

  exportCsvUrl: (gridId: string) => `${BASE}/grids/${gridId}/export.csv`,
  exportJsonUrl: (gridId: string) => `${BASE}/grids/${gridId}/export.json`,

  streamUrl: (gridId: string) => `${BASE}/grids/${gridId}/stream`,

  pdfUrl: (documentId: string) => `${BASE}/pdf/${documentId}`,
};
