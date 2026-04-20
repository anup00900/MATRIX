import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { X } from "lucide-react";
import type { Cell, CellStatus } from "../api/types";
import { useGrid } from "../store/grid";

// Maps the cell's current status to which stages are "active" in the 3D scene.
// active = full-intensity glow + particles flowing on incoming edge.
const ACTIVE_STAGES: Record<CellStatus, string[]> = {
  idle: ["prompt"],
  queued: ["prompt"],
  retrieving: ["prompt", "decompose", "retrieve"],
  drafting: ["prompt", "decompose", "retrieve", "draft"],
  verifying: ["prompt", "decompose", "retrieve", "draft", "verify"],
  done: ["prompt", "decompose", "retrieve", "draft", "verify", "done"],
  stale: ["prompt"],
  failed: ["prompt", "decompose", "retrieve", "draft", "verify"],
};

interface Stage {
  id: string;
  label: string;
  sub: string;
  pos: [number, number, number];
  color: number;
}
const STAGES: Stage[] = [
  { id: "prompt",    label: "User Prompt", sub: "column.prompt",        pos: [-10, 3,  0], color: 0xfafafa },
  { id: "decompose", label: "Decompose",   sub: "LLM · 1",              pos: [ -5, 3,  4], color: 0x38bdf8 },
  { id: "retrieve",  label: "Retrieve",    sub: "naive · isd · wiki",   pos: [  0, 3,  6], color: 0xa78bfa },
  { id: "draft",     label: "Draft",       sub: "LLM · 2",              pos: [  5, 3,  4], color: 0x38bdf8 },
  { id: "verify",    label: "Verify",      sub: "LLM · per claim",      pos: [ 10, 3,  0], color: 0xf59e0b },
  { id: "done",      label: "Done",        sub: "SSE → UI",             pos: [  5, 3, -4], color: 0x10b981 },
];

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
  streaming: 0x38bdf8,
  verify: 0xf59e0b,
  done: 0x10b981,
  revise: 0xf43f5e,
};

// Which edges "light up" given a set of active stages.
function activeEdges(stageSet: Set<string>): Set<string> {
  const keys = new Set<string>();
  for (const e of EDGES) {
    if (e.loop) continue; // revise loop lights only on failed path; skip here
    if (stageSet.has(e.from) && stageSet.has(e.to)) {
      keys.add(`${e.from}->${e.to}`);
    }
  }
  return keys;
}

function makeLabel(text: string, sub: string, scale = 1.0): THREE.Sprite {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 160;
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#fafafa";
  ctx.font = '600 56px "Inter Tight", Inter, system-ui, sans-serif';
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, 256, sub ? 58 : 80);
  if (sub) {
    ctx.fillStyle = "#a1a1aa";
    ctx.font = '400 26px "JetBrains Mono", monospace';
    ctx.fillText(sub, 256, 118);
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.anisotropy = 8;
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false });
  const sp = new THREE.Sprite(mat);
  sp.scale.set(scale * 3.2, scale, 1);
  return sp;
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
  } | null>(null);

  // subscribe to the live cell
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

  // Escape closes
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", h, true);
    return () => window.removeEventListener("keydown", h, true);
  }, [onClose]);

  // Build the three.js scene once; keep reference to update active stages.
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
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.target.set(0, 1, 0);

    scene.add(new THREE.AmbientLight(0xffffff, 0.35));
    const key = new THREE.PointLight(0x38bdf8, 1.0, 60, 2);
    key.position.set(10, 12, 8); scene.add(key);
    const fill = new THREE.PointLight(0xa78bfa, 0.6, 50, 2);
    fill.position.set(-10, 8, -6); scene.add(fill);
    const rim = new THREE.PointLight(0x10b981, 0.5, 40, 2);
    rim.position.set(0, -6, 10); scene.add(rim);

    const grid = new THREE.GridHelper(60, 30, 0x27272a, 0x18181b);
    grid.position.y = -2; scene.add(grid);

    // Stage nodes
    const nodeGroup = new THREE.Group(); scene.add(nodeGroup);
    const nodeByStage = new Map<string, { group: THREE.Group; core: THREE.Mesh; glow: THREE.Mesh; color: number }>();
    for (const s of STAGES) {
      const group = new THREE.Group();
      group.position.set(...s.pos);
      const glowMat = new THREE.MeshBasicMaterial({ color: s.color, transparent: true, opacity: 0.16, side: THREE.BackSide });
      const glow = new THREE.Mesh(new THREE.SphereGeometry(1.6, 32, 32), glowMat);
      group.add(glow);
      const core = new THREE.Mesh(
        new THREE.IcosahedronGeometry(0.9, 1),
        new THREE.MeshStandardMaterial({
          color: s.color, emissive: s.color, emissiveIntensity: 0.4,
          metalness: 0.3, roughness: 0.3,
        }),
      );
      group.add(core);
      const label = makeLabel(s.label, s.sub, 1.0);
      label.position.set(0, 1.9, 0);
      group.add(label);
      nodeGroup.add(group);
      nodeByStage.set(s.id, { group, core, glow, color: s.color });
    }

    // Edges with tube geometry + particles
    interface EdgeObj {
      key: string;
      curve: THREE.QuadraticBezierCurve3;
      tube: THREE.Mesh;
      tubeMat: THREE.MeshBasicMaterial;
      particles: Array<{ mesh: THREE.Mesh; t: number; speed: number }>;
      kind: EdgeKind;
      loop: boolean;
    }
    const edgeObjects: EdgeObj[] = [];
    for (const e of EDGES) {
      const a = nodeByStage.get(e.from)!.group.position;
      const b = nodeByStage.get(e.to)!.group.position;
      const mid = new THREE.Vector3().addVectors(a, b).multiplyScalar(0.5);
      mid.y += e.loop ? 5 : 1;
      const curve = new THREE.QuadraticBezierCurve3(a.clone(), mid, b.clone());
      const tubeGeom = new THREE.TubeGeometry(curve, 64, e.loop ? 0.04 : 0.06, 8, false);
      const tubeMat = new THREE.MeshBasicMaterial({
        color: EDGE_COLORS[e.kind], transparent: true, opacity: 0.12,
      });
      const tube = new THREE.Mesh(tubeGeom, tubeMat);
      scene.add(tube);

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
      edgeObjects.push({
        key: `${e.from}->${e.to}`, curve, tube, tubeMat, particles, kind: e.kind, loop: !!e.loop,
      });
    }

    // PDF page stack on the side
    const pdfGroup = new THREE.Group();
    pdfGroup.position.set(0, 3, 14);
    for (let i = 0; i < 10; i++) {
      const page = new THREE.Mesh(
        new THREE.BoxGeometry(3, 4, 0.08),
        new THREE.MeshStandardMaterial({
          color: 0xfafafa, metalness: 0.1, roughness: 0.7,
          transparent: true, opacity: 0.9,
        }),
      );
      page.position.set((i - 4.5) * 0.35, 0, i * 0.02);
      page.rotation.y = -0.15;
      pdfGroup.add(page);
    }
    scene.add(pdfGroup);

    // Citation beams (retrieve → pages)
    const retrievePos = nodeByStage.get("retrieve")!.group.position;
    const beams: Array<{ line: THREE.Line; mat: THREE.LineBasicMaterial; page: THREE.Object3D }> = [];
    for (let i = 0; i < 4; i++) {
      const page = pdfGroup.children[Math.floor(Math.random() * pdfGroup.children.length)];
      const end = new THREE.Vector3();
      page.getWorldPosition(end);
      const geom = new THREE.BufferGeometry().setFromPoints([retrievePos, end]);
      const mat = new THREE.LineBasicMaterial({ color: 0xa78bfa, transparent: true, opacity: 0.0 });
      const line = new THREE.Line(geom, mat);
      scene.add(line);
      beams.push({ line, mat, page });
    }

    // stars bg
    const starsGeo = new THREE.BufferGeometry();
    const starsN = 400;
    const starsPos = new Float32Array(starsN * 3);
    for (let i = 0; i < starsN; i++) {
      starsPos[i * 3 + 0] = (Math.random() - 0.5) * 120;
      starsPos[i * 3 + 1] = (Math.random() - 0.5) * 60;
      starsPos[i * 3 + 2] = (Math.random() - 0.5) * 120;
    }
    starsGeo.setAttribute("position", new THREE.BufferAttribute(starsPos, 3));
    scene.add(new THREE.Points(starsGeo, new THREE.PointsMaterial({
      color: 0x71717a, size: 0.08, transparent: true, opacity: 0.6,
    })));

    // state that the closure below reads
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

      // Stage glow/core pulsing based on active set
      for (const [id, nd] of nodeByStage) {
        const isActive = activeStageSet.has(id);
        const isFail = currentStatus === "failed" && (id === "verify" || id === "draft");
        const targetGlow = isFail ? 0.7 : isActive ? 0.45 : 0.08;
        const glowMat = nd.glow.material as THREE.MeshBasicMaterial;
        glowMat.opacity += (targetGlow - glowMat.opacity) * 0.08;

        const coreMat = nd.core.material as THREE.MeshStandardMaterial;
        const targetEmissive = isFail ? 1.5 : isActive ? 1.1 : 0.2;
        coreMat.emissiveIntensity += (targetEmissive - coreMat.emissiveIntensity) * 0.1;

        if (isFail) coreMat.emissive.setHex(0xf43f5e);
        else coreMat.emissive.setHex(nd.color);

        const pulse = isActive ? 1 + Math.sin(t * 4 + nd.group.position.x * 0.3) * 0.1 : 1;
        nd.core.scale.setScalar(pulse);
        nd.core.rotation.y = t * 0.3;
        nd.core.rotation.x = t * 0.2;
      }

      // Edge intensity + particles
      for (const eo of edgeObjects) {
        const isRevise = eo.loop;
        const reviseVisible = isRevise && currentStatus === "failed";
        const isActive = (!isRevise && activeEdgeKeys.has(eo.key)) || reviseVisible;
        const targetEdgeOpacity = isActive ? (isRevise ? 0.6 : 0.65) : 0.08;
        eo.tubeMat.opacity += (targetEdgeOpacity - eo.tubeMat.opacity) * 0.08;

        const pOpacity = isActive ? 0.95 : 0.0;
        for (const p of eo.particles) {
          p.t += (isActive ? p.speed : 0.05) * dt;
          if (p.t > 1) p.t = 0;
          const pos = eo.curve.getPoint(p.t);
          p.mesh.position.copy(pos);
          const m = p.mesh.material as THREE.MeshBasicMaterial;
          m.opacity += (pOpacity - m.opacity) * 0.12;
        }
      }

      // Citation beams light up when Retrieve is active
      const retrieveActive = activeStageSet.has("retrieve");
      for (const b of beams) {
        const target = retrieveActive ? (0.25 + 0.3 * (Math.sin(t * 2 + b.page.position.x) * 0.5 + 0.5)) : 0.0;
        b.mat.opacity += (target - b.mat.opacity) * 0.08;
      }

      pdfGroup.rotation.y = Math.sin(t * 0.2) * 0.1;
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    sceneRef.current = {
      setActiveStages: (s, st) => {
        activeStageSet = s;
        currentStatus = st;
        activeEdgeKeys = activeEdges(s);
      },
      cleanup: () => {
        cancelAnimationFrame(raf);
        window.removeEventListener("resize", onResize);
        controls.dispose();
        renderer.dispose();
        if (renderer.domElement.parentElement === container) {
          container.removeChild(renderer.domElement);
        }
      },
    };

    // apply initial state
    sceneRef.current.setActiveStages(activeSet, status);

    return () => {
      sceneRef.current?.cleanup();
      sceneRef.current = null;
    };
    // we intentionally do NOT include activeSet/status here — scene is built once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // push live status updates into the existing scene
  useEffect(() => {
    sceneRef.current?.setActiveStages(activeSet, status);
  }, [activeSet, status]);

  return (
    <div className={
      variant === "overlay"
        ? "fixed inset-0 z-50 bg-[var(--color-canvas)]"
        : "h-full w-full relative bg-[var(--color-canvas)]"
    }>
      {/* top bar — overlay mode only */}
      {variant === "overlay" && (
      <div className="h-11 flex items-center justify-between px-4 border-b border-[var(--color-border)] bg-[var(--color-canvas)]/80 backdrop-blur">
        <div className="flex items-center gap-3 text-[12px]">
          <div className="font-[var(--font-ui)]">◇ 3D Flow</div>
          <div className="h-3 w-px bg-[var(--color-border)]" />
          <div className="text-[var(--color-muted)]">
            {column ? `column · ${column.prompt}` : "no cell selected"}
          </div>
          {cell && (
            <>
              <div className="h-3 w-px bg-[var(--color-border)]" />
              <div className="flex items-center gap-1.5 text-[var(--color-muted)] font-[var(--font-mono)]">
                <span className={[
                  "h-1.5 w-1.5 rounded-full",
                  status === "done" ? "bg-[var(--color-accent-done)]"
                    : status === "failed" ? "bg-[var(--color-accent-fail)]"
                    : status === "verifying" ? "bg-[var(--color-accent-verify)] animate-pulse"
                    : ["retrieving", "drafting"].includes(status) ? "bg-[var(--color-accent-streaming)] animate-pulse"
                    : status === "stale" ? "bg-[var(--color-accent-stale)]"
                    : "bg-zinc-500",
                ].join(" ")}></span>
                {status}
              </div>
            </>
          )}
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded border border-[var(--color-border)] text-[var(--color-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-surface)]"
          aria-label="Close 3D flow"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      )}

      {/* the three.js canvas container */}
      <div ref={containerRef} className={variant === "overlay" ? "absolute inset-0 top-11" : "absolute inset-0"} />

      {/* legend */}
      <div className="absolute left-5 bottom-5 p-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]/75 backdrop-blur text-[12px] max-w-xs leading-snug">
        <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted)] mb-1.5">Pipeline</div>
        <div className="space-y-1 text-[12px]">
          <div className="flex items-center gap-2"><span className="h-1.5 w-1.5 rounded-full bg-[var(--color-accent-streaming)]"></span>Decompose · sub queries + target sections</div>
          <div className="flex items-center gap-2"><span className="h-1.5 w-1.5 rounded-full bg-[var(--color-accent-streaming)]"></span>Retrieve · evidence chunks</div>
          <div className="flex items-center gap-2"><span className="h-1.5 w-1.5 rounded-full bg-[var(--color-accent-streaming)]"></span>Draft · answer with cited chunks</div>
          <div className="flex items-center gap-2"><span className="h-1.5 w-1.5 rounded-full bg-[var(--color-accent-verify)]"></span>Verify · claim by claim check</div>
          <div className="flex items-center gap-2"><span className="h-1.5 w-1.5 rounded-full bg-[var(--color-accent-done)]"></span>Done · answer + citations</div>
        </div>
        <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted)] mt-3 mb-1.5">Hint</div>
        <div className="text-[var(--color-muted)] text-[11px] font-[var(--font-mono)]">drag to orbit · scroll to zoom</div>
      </div>

      {/* right-side latest-state card */}
      {cell && cell.answer_json && (
        <div className="absolute right-5 top-16 w-80 p-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]/85 backdrop-blur text-[12px]">
          <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted)] mb-1">Answer</div>
          <div className="text-[14px] leading-snug">
            {typeof cell.answer_json.value === "string"
              ? cell.answer_json.value
              : JSON.stringify(cell.answer_json.value)}
          </div>
          {cell.citations_json && cell.citations_json.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {cell.citations_json.map((c, i) => (
                <span key={i} className="px-1.5 py-0.5 text-[10px] font-[var(--font-mono)] rounded border border-[var(--color-border)] text-[var(--color-muted)]">
                  p.{c.page}
                </span>
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
