export type CellStatus =
  | "idle" | "queued" | "retrieving" | "drafting"
  | "verifying" | "done" | "stale" | "failed";

export type Shape = "text" | "number" | "currency" | "percentage" | "list" | "table";

export interface Workspace {
  id: string;
  name: string;
  created_at: string;
}

export interface Document {
  id: string;
  workspace_id: string;
  filename: string;
  sha256: string;
  status: string;
  n_pages: number | null;
  meta_json: Record<string, unknown> | null;
  parsed_path: string | null;
  wiki_path: string | null;
  error: string | null;
}

export interface Column {
  id: string;
  grid_id: string;
  position: number;
  prompt: string;
  shape_hint: Shape;
  version: number;
}

export interface Row {
  id: string;
  grid_id: string;
  document_id: string;
  position: number;
}

export interface Citation {
  chunk_id: string;
  page: number;
  snippet: string;
  bboxes: Array<{ page: number; bbox: [number, number, number, number] }>;
}

export interface Cell {
  id: string;
  grid_id: string;
  row_id: string;
  column_id: string;
  column_version: number;
  status: CellStatus;
  answer_json: { value: unknown; shape: Shape } | null;
  citations_json: Citation[] | null;
  confidence: "high" | "medium" | "low" | null;
  tokens_used: number;
  latency_ms: number;
  retriever_mode: string | null;
  error: string | null;
}

export interface Grid {
  id: string;
  workspace_id: string;
  name: string;
  retriever_mode: "naive" | "isd" | "wiki";
}

export interface GridView {
  grid: Grid;
  columns: Column[];
  rows: Row[];
  cells: Cell[];
}
