import { useEffect, useRef } from "react";
import * as pdfjs from "pdfjs-dist";
// Vite-friendly worker URL
// @ts-ignore — worker URL ?url import handled by Vite
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

interface Props {
  url: string;
  page: number;
  highlight?: [number, number, number, number];
  scale?: number;
}

export function PdfView({ url, page, highlight, scale = 1.2 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const loaderRef = useRef<{ cancel: boolean }>({ cancel: false });

  useEffect(() => {
    const ctx = { cancel: false };
    loaderRef.current = ctx;
    (async () => {
      try {
        const pdf = await pdfjs.getDocument(url).promise;
        if (ctx.cancel) return;
        const pageNum = Math.min(Math.max(1, page), pdf.numPages);
        const p = await pdf.getPage(pageNum);
        if (ctx.cancel) return;
        const viewport = p.getViewport({ scale });
        const canvas = canvasRef.current;
        if (!canvas) return;
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        const c = canvas.getContext("2d");
        if (!c) return;
        await p.render({ canvasContext: c, viewport } as Parameters<typeof p.render>[0]).promise;
        if (highlight) {
          const [x0, y0, x1, y1] = highlight;
          const s = viewport.scale;
          c.fillStyle = "rgba(56,189,248,0.25)";
          c.strokeStyle = "rgba(56,189,248,0.9)";
          c.lineWidth = 1;
          // PDF coords: bottom-origin; canvas coords: top-origin.
          const rx = x0 * s;
          const ry = canvas.height - y1 * s;
          const rw = (x1 - x0) * s;
          const rh = (y1 - y0) * s;
          c.fillRect(rx, ry, rw, rh);
          c.strokeRect(rx, ry, rw, rh);
        }
      } catch (err) {
        console.warn("PdfView render failed", err);
      }
    })();
    return () => {
      ctx.cancel = true;
    };
  }, [url, page, highlight?.join(","), scale]);

  return (
    <canvas
      ref={canvasRef}
      className="rounded border border-[--color-border] max-w-full h-auto block"
    />
  );
}
