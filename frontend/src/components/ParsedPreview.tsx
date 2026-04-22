import { useEffect, useState } from "react";
import { X, ChevronLeft, ChevronRight, FileText, Hash, ImageOff } from "lucide-react";
import { api } from "../api/client";
import { cn } from "../lib/utils";

interface ParsedDoc {
  document_id: string;
  filename: string;
  n_pages: number;
  n_chunks: number;
  pages: Array<{ page_no: number; markdown: string; failed: boolean }>;
  sections: Array<{ id: string; title: string; page_start: number; page_end: number }>;
}

interface Props {
  documentId: string;
  onClose: () => void;
}

export function ParsedPreview({ documentId, onClose }: Props) {
  const [doc, setDoc] = useState<ParsedDoc | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [page, setPage] = useState(1);
  const [imgErr, setImgErr] = useState(false);

  useEffect(() => {
    setLoading(true);
    setErr("");
    api.getParsed(documentId)
      .then((d) => { setDoc(d); setLoading(false); })
      .catch((e) => { setErr(String(e)); setLoading(false); });
  }, [documentId]);

  // Reset image error state when page changes
  useEffect(() => { setImgErr(false); }, [page, documentId]);

  const currentPage = doc?.pages.find((p) => p.page_no === page);
  const pageImageUrl = api.pageImageUrl(documentId, page);

  return (
    <div className="fixed inset-0 z-50 bg-[var(--color-canvas)] flex flex-col">
      {/* Header */}
      <div className="h-11 flex items-center justify-between px-4 border-b border-[var(--color-border)] bg-[var(--color-canvas)]/90 backdrop-blur shrink-0">
        <div className="flex items-center gap-3 text-[12px] min-w-0">
          <span className="text-[var(--color-accent-streaming)]">◇</span>
          <span className="font-[var(--font-ui)] truncate">{doc?.filename ?? "Loading…"}</span>
          {doc && (
            <>
              <div className="h-3 w-px bg-[var(--color-border)] shrink-0" />
              <span className="text-[var(--color-muted)] font-[var(--font-mono)] shrink-0">{doc.n_pages}p</span>
              <div className="h-3 w-px bg-[var(--color-border)] shrink-0" />
              <span className="text-[var(--color-muted)] font-[var(--font-mono)] shrink-0">{doc.n_chunks} chunks</span>
              <div className="h-3 w-px bg-[var(--color-border)] shrink-0" />
              <span className="text-[var(--color-muted)] font-[var(--font-mono)] shrink-0">{doc.sections.length} sections</span>
            </>
          )}
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded border border-[var(--color-border)] text-[var(--color-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-surface)] shrink-0"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {loading && (
        <div className="flex-1 flex items-center justify-center text-[var(--color-muted)] text-[13px] font-[var(--font-mono)]">
          loading parsed output…
        </div>
      )}

      {err && (
        <div className="flex-1 flex items-center justify-center text-[var(--color-accent-fail)] text-[13px] font-[var(--font-mono)]">
          {err} — document may still be indexing
        </div>
      )}

      {doc && !loading && (
        <div className="flex-1 flex min-h-0">
          {/* Left sidebar: page list + sections */}
          <div className="w-48 shrink-0 border-r border-[var(--color-border)] flex flex-col overflow-hidden">
            <div className="px-3 py-2 border-b border-[var(--color-border)]">
              <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted)]">Pages</div>
            </div>
            <div className="flex-1 overflow-y-auto py-1">
              {doc.pages.map((p) => {
                const section = doc.sections.find(
                  (s) => p.page_no >= s.page_start && p.page_no <= s.page_end
                );
                return (
                  <button
                    key={p.page_no}
                    onClick={() => setPage(p.page_no)}
                    className={cn(
                      "w-full text-left px-3 py-1.5 text-[11px] flex items-center gap-2 transition",
                      page === p.page_no
                        ? "bg-[var(--color-surface-2)] text-[var(--color-text)]"
                        : "text-[var(--color-muted)] hover:bg-[var(--color-surface)] hover:text-[var(--color-text)]",
                    )}
                  >
                    <FileText className="w-3 h-3 shrink-0" />
                    <span className="font-[var(--font-mono)]">p.{p.page_no}</span>
                    {p.failed && <span className="text-[var(--color-accent-fail)] text-[9px]">✗</span>}
                    {section && (
                      <span className="truncate text-[9px] text-[var(--color-muted)]">{section.title}</span>
                    )}
                  </button>
                );
              })}
            </div>

            {doc.sections.length > 0 && (
              <>
                <div className="px-3 py-2 border-t border-[var(--color-border)]">
                  <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted)]">Sections</div>
                </div>
                <div className="overflow-y-auto max-h-48 py-1">
                  {doc.sections.map((s) => (
                    <button
                      key={s.id}
                      onClick={() => setPage(s.page_start)}
                      className="w-full text-left px-3 py-1.5 text-[10px] flex items-center gap-2 text-[var(--color-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-surface)] transition"
                    >
                      <Hash className="w-2.5 h-2.5 shrink-0" />
                      <span className="truncate">{s.title}</span>
                      <span className="shrink-0 font-[var(--font-mono)] text-[9px]">p.{s.page_start}</span>
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>

          {/* Main: rendered page image + extracted markdown side by side */}
          <div className="flex-1 flex min-w-0">
            {/* Rendered page image (what GPT-4.1 actually saw) */}
            <div className="flex-1 flex flex-col border-r border-[var(--color-border)] min-w-0">
              <div className="h-8 flex items-center justify-between px-3 border-b border-[var(--color-border)] bg-[var(--color-surface)]/50 shrink-0">
                <div className="flex items-center gap-2 text-[11px] text-[var(--color-muted)]">
                  <span className="text-[var(--color-accent-streaming)] text-[9px]">●</span>
                  <span>Rendered image · what GPT-4.1 saw · page {page}</span>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page <= 1}
                    className="p-0.5 rounded text-[var(--color-muted)] hover:text-[var(--color-text)] disabled:opacity-30"
                  >
                    <ChevronLeft className="w-3.5 h-3.5" />
                  </button>
                  <span className="text-[10px] font-[var(--font-mono)] text-[var(--color-muted)]">{page}/{doc.n_pages}</span>
                  <button
                    onClick={() => setPage((p) => Math.min(doc.n_pages, p + 1))}
                    disabled={page >= doc.n_pages}
                    className="p-0.5 rounded text-[var(--color-muted)] hover:text-[var(--color-text)] disabled:opacity-30"
                  >
                    <ChevronRight className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
              <div className="flex-1 overflow-auto flex items-start justify-center bg-[var(--color-surface)]/30 p-2">
                {imgErr ? (
                  <div className="flex flex-col items-center justify-center gap-2 text-[var(--color-muted)] pt-16">
                    <ImageOff className="w-6 h-6" />
                    <span className="text-[11px] font-[var(--font-mono)]">image not saved — re-upload to enable</span>
                  </div>
                ) : (
                  <img
                    key={pageImageUrl}
                    src={pageImageUrl}
                    alt={`Page ${page}`}
                    className="max-w-full h-auto shadow-lg border border-[var(--color-border)]"
                    onError={() => setImgErr(true)}
                  />
                )}
              </div>
            </div>

            {/* Extracted markdown */}
            <div className="flex-1 flex flex-col min-w-0">
              <div className="h-8 flex items-center justify-between px-3 border-b border-[var(--color-border)] bg-[var(--color-surface)]/50 shrink-0">
                <div className="flex items-center gap-2 text-[11px] text-[var(--color-muted)]">
                  <FileText className="w-3 h-3" />
                  <span>Extracted markdown · used for indexing + wiki</span>
                </div>
                {currentPage?.failed && (
                  <span className="text-[10px] text-[var(--color-accent-fail)] font-[var(--font-mono)]">extraction failed</span>
                )}
              </div>
              <div className="flex-1 overflow-auto p-4">
                {currentPage?.markdown ? (
                  <pre className={cn(
                    "text-[11px] font-[var(--font-mono)] leading-relaxed whitespace-pre-wrap break-words",
                    "text-[var(--color-text)]",
                  )}>
                    {currentPage.markdown}
                  </pre>
                ) : (
                  <div className="text-[var(--color-muted)] text-[12px] font-[var(--font-mono)] pt-4">
                    {currentPage?.failed ? "Vision extraction failed for this page." : "No content extracted."}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
