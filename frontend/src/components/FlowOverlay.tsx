import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { X } from "lucide-react";
import type { Cell, CellStatus, Citation } from "../api/types";
import { useGrid } from "../store/grid";

const ACTIVE_STAGES: Record<CellStatus, string[]> = {
  idle:       ["prompt"],
  queued:     ["prompt"],
  retrieving: ["prompt", "decompose", "retrieve"],
  drafting:   ["prompt", "decompose", "retrieve", "draft"],
  verifying:  ["prompt", "decompose", "retrieve", "draft", "verify"],
  done:       ["prompt", "decompose", "retrieve", "draft", "verify", "done"],
  stale:      ["prompt"],
  failed:     ["prompt", "decompose", "retrieve", "draft", "verify"],
};

interface Stage { id: string; label: string; sub: string; pos: [number, number, number]; color: number; }
const STAGES: Stage[] = [
  { id: "prompt",    label: "Prompt",    sub: "column.prompt",       pos: [-10, 3,  0], color: 0xfafafa },
  { id: "decompose", label: "Decompose", sub: "LLM · sub-queries",   pos: [ -5, 3,  4], color: 0x38bdf8 },
  { id: "retrieve",  label: "Retrieve",  sub: "naive · isd · wiki",  pos: [  0, 3,  6], color: 0xa78bfa },
  { id: "draft",     label: "Draft",     sub: "LLM · synthesise",    pos: [  5, 3,  4], color: 0x38bdf8 },
  { id: "verify",    label: "Verify",    sub: "LLM · per claim",     pos: [ 10, 3,  0], color: 0xf59e0b },
  { id: "done",      label: "Done",      sub: "SSE → cell",          pos: [  5, 3, -4], color: 0x10b981 },
];

const STAGE_COLOR_CSS: Record<string, string> = {
  prompt:    "#fafafa",
  decompose: "#38bdf8",
  retrieve:  "#a78bfa",
  draft:     "#38bdf8",
  verify:    "#f59e0b",
  done:      "#10b981",
};

const STAGE_INFO: Record<string, { desc: string; detail: string }> = {
  prompt:    { desc: "Your column question, sent as the driving intent for the entire pipeline.", detail: "Everything downstream derives from this prompt." },
  decompose: { desc: "LLM breaks the question into 2–5 targeted sub-queries, each aimed at a specific section.", detail: "Improves recall by covering different angles of the original prompt." },
  retrieve:  { desc: "Dense vector search finds the most relevant text chunks across all documents.", detail: "naive: cosine sim · ISD: instruction-following dense · wiki: pre-built wiki sections" },
  draft:     { desc: "LLM synthesises the retrieved chunks into a structured answer with inline citations.", detail: "Cites every claim by page number. Respects the column's shape hint (text / number / list…)." },
  verify:    { desc: "LLM re-reads each factual claim against its source chunk and adjusts confidence.", detail: "High = all claims verified · Medium = partial · Low = weak evidence" },
  done:      { desc: "Final answer and citations streamed back to the grid cell.", detail: "Latency, token usage, and retriever mode are logged." },
};

type EdgeKind = "streaming" | "verify" | "done" | "revise";
const EDGES: Array<{ from: string; to: string; kind: EdgeKind; loop?: boolean }> = [
  { from: "prompt",    to: "decompose", kind: "streaming" },
  { from: "decompose", to: "retrieve",  kind: "streaming" },
  { from: "retrieve",  to: "draft",     kind: "streaming" },
  { from: "draft",     to: "verify",    kind: "verify"    },
  { from: "verify",    to: "done",      kind: "done"      },
  { from: "verify",    to: "draft",     kind: "revise", loop: true },
];
const EDGE_COLORS: Record<EdgeKind, number> = {
  streaming: 0x38bdf8, verify: 0xf59e0b, done: 0x10b981, revise: 0xf43f5e,
};

function activeEdges(stageSet: Set<string>): Set<string> {
  const keys = new Set<string>();
  for (const e of EDGES) {
    if (e.loop) continue;
    if (stageSet.has(e.from) && stageSet.has(e.to)) keys.add(`${e.from}->${e.to}`);
  }
  return keys;
}

function makeLabel(text: string, sub: string, scale = 1.0): THREE.Sprite {
  const canvas = document.createElement("canvas");
  canvas.width = 512; canvas.height = 160;
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#fafafa";
  ctx.font = '600 56px "Inter Tight", Inter, system-ui, sans-serif';
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(text, 256, sub ? 58 : 80);
  if (sub) {
    ctx.fillStyle = "#a1a1aa";
    ctx.font = '400 26px "JetBrains Mono", monospace';
    ctx.fillText(sub, 256, 118);
  }
  const tex = new THREE.CanvasTexture(canvas); tex.anisotropy = 8;
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }));
  sp.scale.set(scale * 3.2, scale, 1);
  return sp;
}

function makePageTexture(snippet: string, pageNum: number): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = 300; c.height = 420;
  const ctx = c.getContext("2d")!;
  ctx.fillStyle = "#fafafa"; ctx.fillRect(0, 0, 300, 420);
  ctx.fillStyle = "#e4e4e740";
  for (let i = 0; i < 18; i++) {
    const w = 200 - (Math.random() * 80 | 0);
    ctx.fillRect(18, 22 + i * 20, w, 6);
  }
  // purple side bar
  ctx.fillStyle = "#a78bfa66"; ctx.fillRect(0, 0, 5, 420);
  // snippet text
  ctx.fillStyle = "#18181b"; ctx.font = "10px system-ui, sans-serif";
  const words = snippet.replace(/[#*_]/g, "").trim().split(/\s+/);
  let line = ""; let y = 40;
  for (const w of words) {
    const test = line + w + " ";
    if (ctx.measureText(test).width > 264 && line) {
      ctx.fillText(line.trim(), 18, y); line = w + " "; y += 15;
      if (y > 390) break;
    } else { line = test; }
  }
  if (line && y <= 390) ctx.fillText(line.trim(), 18, y);
  // page number
  ctx.fillStyle = "#a78bfa"; ctx.font = "bold 14px monospace";
  ctx.fillText(`p.${pageNum}`, 18, 408);
  const tex = new THREE.CanvasTexture(c); tex.anisotropy = 8;
  return tex;
}

interface Props {
  cellId: string | null;
  onClose: () => void;
  variant?: "overlay" | "panel";
}

export function FlowOverlay({ cellId, onClose, variant = "overlay" }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<{
    cleanup: () => void;
    setActiveStages: (s: Set<string>, status: CellStatus) => void;
    setCitations: (cits: Citation[]) => void;
  } | null>(null);
  const [selectedStage, setSelectedStage] = useState<string | null>(null);
  // ref so Three.js click handler can call it without stale closure
  const setStageRef = useRef(setSelectedStage);
  useEffect(() => { setStageRef.current = setSelectedStage; }, []);

  const cell: Cell | undefined = useGrid((s) => {
    if (!cellId) return undefined;
    return s.view?.cells.find((c) => c.id === cellId);
  });
  const column = useGrid((s) => {
    if (!cell || !s.view) return undefined;
    return s.view.columns.find((c) => c.id === cell.column_id);
  });
  const status: CellStatus = cell?.status ?? "idle";
  const activeSet = useMemo(() => new Set(ACTIVE_STAGES[status]), [status]);

  useEffect(() => {
    if (variant !== "overlay") return;
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onClose(); }
    };
    window.addEventListener("keydown", h, true);
    return () => window.removeEventListener("keydown", h, true);
  }, [onClose, variant]);

  // Build Three.js scene once
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0x09090b, 20, 80);

    const camera = new THREE.PerspectiveCamera(55, container.clientWidth / container.clientHeight, 0.1, 200);
    camera.position.set(12, 10, 22);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setClearColor(0x09090b, 1);
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true; controls.dampingFactor = 0.08;
    controls.target.set(0, 1, 0);

    scene.add(new THREE.AmbientLight(0xffffff, 0.35));
    const key = new THREE.PointLight(0x38bdf8, 1.0, 60, 2); key.position.set(10, 12, 8); scene.add(key);
    const fill = new THREE.PointLight(0xa78bfa, 0.6, 50, 2); fill.position.set(-10, 8, -6); scene.add(fill);
    const rim = new THREE.PointLight(0x10b981, 0.5, 40, 2); rim.position.set(0, -6, 10); scene.add(rim);

    const gridHelper = new THREE.GridHelper(60, 30, 0x27272a, 0x18181b);
    gridHelper.position.y = -2;
    scene.add(gridHelper);

    // Stage nodes
    const nodeGroup = new THREE.Group(); scene.add(nodeGroup);
    const nodeByStage = new Map<string, { group: THREE.Group; core: THREE.Mesh; glow: THREE.Mesh; color: number }>();
    const coreToStage = new Map<THREE.Mesh, string>();

    for (const s of STAGES) {
      const group = new THREE.Group(); group.position.set(...s.pos);
      const glowMat = new THREE.MeshBasicMaterial({ color: s.color, transparent: true, opacity: 0.16, side: THREE.BackSide });
      const glow = new THREE.Mesh(new THREE.SphereGeometry(1.6, 32, 32), glowMat); group.add(glow);
      const core = new THREE.Mesh(
        new THREE.IcosahedronGeometry(0.9, 1),
        new THREE.MeshStandardMaterial({ color: s.color, emissive: s.color, emissiveIntensity: 0.4, metalness: 0.3, roughness: 0.3 }),
      );
      group.add(core);
      const label = makeLabel(s.label, s.sub, 1.0);
      label.position.set(0, 1.9, 0); group.add(label);
      nodeGroup.add(group);
      nodeByStage.set(s.id, { group, core, glow, color: s.color });
      coreToStage.set(core, s.id);
    }

    // Edges
    interface EdgeObj { key: string; curve: THREE.QuadraticBezierCurve3; tubeMat: THREE.MeshBasicMaterial; particles: Array<{ mesh: THREE.Mesh; t: number; speed: number }>; kind: EdgeKind; loop: boolean; }
    const edgeObjects: EdgeObj[] = [];
    for (const e of EDGES) {
      const a = nodeByStage.get(e.from)!.group.position;
      const b = nodeByStage.get(e.to)!.group.position;
      const mid = new THREE.Vector3().addVectors(a, b).multiplyScalar(0.5);
      mid.y += e.loop ? 5 : 1;
      const curve = new THREE.QuadraticBezierCurve3(a.clone(), mid, b.clone());
      const tubeMat = new THREE.MeshBasicMaterial({ color: EDGE_COLORS[e.kind], transparent: true, opacity: 0.12 });
      scene.add(new THREE.Mesh(new THREE.TubeGeometry(curve, 64, e.loop ? 0.04 : 0.06, 8, false), tubeMat));
      const particles: EdgeObj["particles"] = [];
      const pCount = e.loop ? 2 : 4;
      for (let i = 0; i < pCount; i++) {
        const m = new THREE.Mesh(
          new THREE.SphereGeometry(0.1, 12, 12),
          new THREE.MeshBasicMaterial({ color: EDGE_COLORS[e.kind], transparent: true, opacity: 0.0 }),
        );
        scene.add(m);
        particles.push({ mesh: m, t: i / pCount, speed: e.loop ? 0.14 : 0.25 });
      }
      edgeObjects.push({ key: `${e.from}->${e.to}`, curve, tubeMat, particles, kind: e.kind, loop: !!e.loop });
    }

    // PDF page stack — pages are updated with citation textures later
    const pdfGroup = new THREE.Group(); pdfGroup.position.set(0, 3, 14);
    const pageMeshes: THREE.Mesh[] = [];
    for (let i = 0; i < 10; i++) {
      const mat = new THREE.MeshStandardMaterial({ color: 0xe4e4e7, metalness: 0.05, roughness: 0.8, transparent: true, opacity: 0.85 });
      const m = new THREE.Mesh(new THREE.BoxGeometry(3, 4, 0.08), mat);
      m.position.set((i - 4.5) * 0.38, 0, i * 0.02); m.rotation.y = -0.15;
      pdfGroup.add(m); pageMeshes.push(m);
    }
    scene.add(pdfGroup);

    // Citation beams
    const retrievePos = nodeByStage.get("retrieve")!.group.position;
    const beams: Array<{ line: THREE.Line; mat: THREE.LineBasicMaterial; page: THREE.Object3D }> = [];
    for (let i = 0; i < 6; i++) {
      const page = pdfGroup.children[i % pdfGroup.children.length];
      const end = new THREE.Vector3(); page.getWorldPosition(end);
      const geom = new THREE.BufferGeometry().setFromPoints([retrievePos, end]);
      const mat = new THREE.LineBasicMaterial({ color: 0xa78bfa, transparent: true, opacity: 0.0 });
      scene.add(new THREE.Line(geom, mat));
      beams.push({ line: new THREE.Line(geom, mat), mat, page });
    }

    // Stars
    const starsPos = new Float32Array(400 * 3);
    for (let i = 0; i < 400; i++) {
      starsPos[i*3]=(Math.random()-.5)*120; starsPos[i*3+1]=(Math.random()-.5)*60; starsPos[i*3+2]=(Math.random()-.5)*120;
    }
    const starsGeo = new THREE.BufferGeometry(); starsGeo.setAttribute("position", new THREE.BufferAttribute(starsPos, 3));
    scene.add(new THREE.Points(starsGeo, new THREE.PointsMaterial({ color: 0x71717a, size: 0.08, transparent: true, opacity: 0.6 })));

    // Raycasting for node clicks + hover cursor
    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    const allCores = Array.from(coreToStage.keys());

    const onMouseMove = (ev: MouseEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      mouse.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(mouse, camera);
      const hits = raycaster.intersectObjects(allCores, false);
      renderer.domElement.style.cursor = hits.length > 0 ? "pointer" : "default";
    };
    const onClick = (ev: MouseEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      mouse.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(mouse, camera);
      const hits = raycaster.intersectObjects(allCores, false);
      if (hits.length > 0) {
        const stageId = coreToStage.get(hits[0].object as THREE.Mesh);
        if (stageId) setStageRef.current(stageId);
      }
    };
    renderer.domElement.addEventListener("mousemove", onMouseMove);
    renderer.domElement.addEventListener("click", onClick);

    // Closure state
    let activeStageSet = new Set<string>(["prompt"]);
    let currentStatus: CellStatus = "idle";
    let activeEdgeKeys = activeEdges(activeStageSet);

    const onResize = () => {
      if (!container) return;
      camera.aspect = container.clientWidth / container.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(container.clientWidth, container.clientHeight);
    };
    window.addEventListener("resize", onResize);

    const clock = new THREE.Clock();
    let raf = 0;
    const animate = () => {
      raf = requestAnimationFrame(animate);
      const t = clock.getElapsedTime();
      const dt = clock.getDelta();

      for (const [id, nd] of nodeByStage) {
        const isActive = activeStageSet.has(id);
        const isFail = currentStatus === "failed" && (id === "verify" || id === "draft");
        const glowMat = nd.glow.material as THREE.MeshBasicMaterial;
        glowMat.opacity += ((isFail ? 0.7 : isActive ? 0.45 : 0.08) - glowMat.opacity) * 0.08;
        const coreMat = nd.core.material as THREE.MeshStandardMaterial;
        coreMat.emissiveIntensity += ((isFail ? 1.5 : isActive ? 1.1 : 0.2) - coreMat.emissiveIntensity) * 0.1;
        coreMat.emissive.setHex(isFail ? 0xf43f5e : nd.color);
        nd.core.scale.setScalar(isActive ? 1 + Math.sin(t * 4 + nd.group.position.x * 0.3) * 0.1 : 1);
        nd.core.rotation.y = t * 0.3; nd.core.rotation.x = t * 0.2;
      }

      for (const eo of edgeObjects) {
        const reviseActive = eo.loop && currentStatus === "failed";
        const edgeActive = (!eo.loop && activeEdgeKeys.has(eo.key)) || reviseActive;
        eo.tubeMat.opacity += ((edgeActive ? (eo.loop ? 0.6 : 0.65) : 0.08) - eo.tubeMat.opacity) * 0.08;
        const pOp = edgeActive ? 0.95 : 0.0;
        for (const p of eo.particles) {
          p.t += (edgeActive ? p.speed : 0.05) * dt;
          if (p.t > 1) p.t = 0;
          p.mesh.position.copy(eo.curve.getPoint(p.t));
          const m = p.mesh.material as THREE.MeshBasicMaterial;
          m.opacity += (pOp - m.opacity) * 0.12;
        }
      }

      const retrieveActive = activeStageSet.has("retrieve");
      for (const b of beams) {
        const target = retrieveActive ? (0.3 + 0.3 * (Math.sin(t * 2 + b.page.position.x) * 0.5 + 0.5)) : 0.0;
        b.mat.opacity += (target - b.mat.opacity) * 0.08;
      }

      pdfGroup.rotation.y = Math.sin(t * 0.2) * 0.1;
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    sceneRef.current = {
      setActiveStages: (s, st) => { activeStageSet = s; currentStatus = st; activeEdgeKeys = activeEdges(s); },
      setCitations: (cits: Citation[]) => {
        const unique = Array.from(new Map(cits.map((c) => [c.page, c])).values()).slice(0, 10);
        // Reset all pages to grey first
        for (const m of pageMeshes) {
          (m.material as THREE.MeshStandardMaterial).map = null;
          (m.material as THREE.MeshStandardMaterial).color.setHex(0xe4e4e7);
          (m.material as THREE.MeshStandardMaterial).needsUpdate = true;
        }
        // Apply citation textures to the first N pages
        unique.forEach((cit, i) => {
          if (i >= pageMeshes.length) return;
          const tex = makePageTexture(cit.snippet ?? `Page ${cit.page}`, cit.page);
          const mat = pageMeshes[i].material as THREE.MeshStandardMaterial;
          mat.map = tex; mat.color.setHex(0xffffff); mat.needsUpdate = true;
        });
      },
      cleanup: () => {
        cancelAnimationFrame(raf);
        window.removeEventListener("resize", onResize);
        renderer.domElement.removeEventListener("mousemove", onMouseMove);
        renderer.domElement.removeEventListener("click", onClick);
        controls.dispose(); renderer.dispose();
        if (renderer.domElement.parentElement === container) container.removeChild(renderer.domElement);
      },
    };
    sceneRef.current.setActiveStages(activeSet, status);
    return () => { sceneRef.current?.cleanup(); sceneRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { sceneRef.current?.setActiveStages(activeSet, status); }, [activeSet, status]);
  useEffect(() => {
    if (cell?.citations_json && cell.citations_json.length > 0) {
      sceneRef.current?.setCitations(cell.citations_json);
    }
  }, [cell?.citations_json]);

  const stageInfo = selectedStage ? STAGE_INFO[selectedStage] : null;
  const stageMeta = selectedStage ? STAGES.find((s) => s.id === selectedStage) : null;

  return (
    <div className={variant === "overlay" ? "fixed inset-0 z-50 bg-[var(--color-canvas)]" : "h-full w-full relative bg-[var(--color-canvas)]"}>
      {/* Top bar — overlay only */}
      {variant === "overlay" && (
        <div className="h-11 flex items-center justify-between px-4 border-b border-[var(--color-border)] bg-[var(--color-canvas)]/80 backdrop-blur">
          <div className="flex items-center gap-3 text-[12px]">
            <div className="font-[var(--font-ui)]">◇ 3D Flow</div>
            <div className="h-3 w-px bg-[var(--color-border)]" />
            <div className="text-[var(--color-muted)]">{column ? `column · ${column.prompt}` : "no cell selected"}</div>
            {cell && (
              <>
                <div className="h-3 w-px bg-[var(--color-border)]" />
                <div className="flex items-center gap-1.5 text-[var(--color-muted)] font-[var(--font-mono)]">
                  <span className={["h-1.5 w-1.5 rounded-full",
                    status === "done" ? "bg-[var(--color-accent-done)]"
                    : status === "failed" ? "bg-[var(--color-accent-fail)]"
                    : status === "verifying" ? "bg-[var(--color-accent-verify)] animate-pulse"
                    : ["retrieving","drafting"].includes(status) ? "bg-[var(--color-accent-streaming)] animate-pulse"
                    : "bg-zinc-500",
                  ].join(" ")} />
                  {status}
                </div>
              </>
            )}
          </div>
          <button onClick={onClose} className="p-1.5 rounded border border-[var(--color-border)] text-[var(--color-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-surface)]" aria-label="Close">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Three.js canvas */}
      <div ref={containerRef} className={variant === "overlay" ? "absolute inset-0 top-11" : "absolute inset-0"} />

      {/* Hint — visible only in overlay, before a stage is selected */}
      {variant === "overlay" && !selectedStage && (
        <div className="absolute left-5 bottom-5 text-[10px] text-[var(--color-muted)] font-[var(--font-mono)]">
          click a node to inspect · drag to orbit · scroll to zoom
        </div>
      )}

      {/* Stage info card — appears on node click */}
      {selectedStage && stageInfo && stageMeta && (
        <div className={[
          "absolute left-3 right-3 p-3 rounded-lg border border-[var(--color-border)]",
          "bg-[var(--color-surface)]/92 backdrop-blur",
          variant === "overlay" ? "bottom-5" : "bottom-2",
        ].join(" ")}>
          <div className="flex items-start justify-between gap-2 mb-1.5">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="h-2 w-2 rounded-full shrink-0" style={{ background: STAGE_COLOR_CSS[selectedStage] }} />
              <span className="text-[13px] font-semibold">{stageMeta.label}</span>
              <span className="text-[10px] text-[var(--color-muted)] font-[var(--font-mono)]">{stageMeta.sub}</span>
            </div>
            <button onClick={() => setSelectedStage(null)} className="shrink-0 p-0.5 rounded text-[var(--color-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-surface-2)] transition">
              <X className="w-3 h-3" />
            </button>
          </div>
          <p className="text-[12px] leading-relaxed text-[var(--color-text)]">{stageInfo.desc}</p>
          <p className="text-[11px] text-[var(--color-muted)] mt-1 font-[var(--font-mono)] leading-relaxed">{stageInfo.detail}</p>

          {/* Live data per stage */}
          {selectedStage === "prompt" && column && (
            <div className="mt-2 text-[11px] font-[var(--font-mono)] text-[var(--color-accent-streaming)] bg-[var(--color-canvas)] rounded px-2 py-1 border border-[var(--color-border)] truncate">
              "{column.prompt}"
            </div>
          )}
          {selectedStage === "retrieve" && cell?.citations_json && cell.citations_json.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              <span className="text-[10px] text-[var(--color-muted)] mr-1">{cell.citations_json.length} chunks from</span>
              {Array.from(new Set(cell.citations_json.map((c) => c.page))).map((p) => (
                <span key={p} className="px-1.5 py-0.5 text-[10px] font-[var(--font-mono)] rounded border border-[var(--color-border)] text-[var(--color-muted)]">p.{p}</span>
              ))}
            </div>
          )}
          {selectedStage === "verify" && cell?.confidence && (
            <div className="mt-2 text-[11px] font-[var(--font-mono)]">
              confidence: <span className={cell.confidence === "high" ? "text-[var(--color-accent-done)]" : cell.confidence === "medium" ? "text-[var(--color-accent-verify)]" : "text-[var(--color-accent-fail)]"}>{cell.confidence}</span>
            </div>
          )}
          {selectedStage === "done" && cell?.answer_json && (
            <div className="mt-2 text-[11px] text-[var(--color-muted)] line-clamp-2 leading-relaxed">
              {String(cell.answer_json.value).slice(0, 180)}
            </div>
          )}
        </div>
      )}

      {/* Answer card — overlay mode, shown when not inspecting a stage */}
      {variant === "overlay" && cell?.answer_json && !selectedStage && (
        <div className="absolute right-5 top-16 w-72 max-w-[calc(100%-2.5rem)] p-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]/85 backdrop-blur text-[12px]">
          <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted)] mb-1">Answer</div>
          <div className="text-[14px] leading-snug">
            {typeof cell.answer_json.value === "string" ? cell.answer_json.value : JSON.stringify(cell.answer_json.value)}
          </div>
          {cell.citations_json && cell.citations_json.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {cell.citations_json.map((c, i) => (
                <span key={i} className="px-1.5 py-0.5 text-[10px] font-[var(--font-mono)] rounded border border-[var(--color-border)] text-[var(--color-muted)]">p.{c.page}</span>
              ))}
            </div>
          )}
          <div className="mt-2 text-[10px] text-[var(--color-muted)] font-[var(--font-mono)]">
            {cell.latency_ms}ms · {cell.tokens_used}tok · {cell.retriever_mode ?? "—"}
          </div>
        </div>
      )}
    </div>
  );
}

