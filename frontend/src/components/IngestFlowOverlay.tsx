import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { X } from "lucide-react";
import { useGrid, type IngestStage } from "../store/grid";

const ACTIVE_STAGES: Record<IngestStage, string[]> = {
  queued:   ["upload"],
  parsing:  ["upload", "render", "vision"],
  indexing: ["upload", "render", "vision", "index"],
  wiki:     ["upload", "render", "vision", "index", "wiki"],
  ready:    ["upload", "render", "vision", "index", "wiki", "ready"],
  failed:   ["upload", "render", "vision"],
};

interface Stage {
  id: string;
  label: string;
  sub: string;
  pos: [number, number, number];
  color: number;
}
const STAGES: Stage[] = [
  { id: "upload", label: "Upload",       sub: "pdf bytes",      pos: [-12, 3,  0], color: 0xfafafa },
  { id: "render", label: "Render",       sub: "page → PNG",     pos: [ -7, 3,  3], color: 0x38bdf8 },
  { id: "vision", label: "Vision",       sub: "gpt 4.1 · /page", pos: [ -2, 3,  5], color: 0x38bdf8 },
  { id: "index",  label: "Index",        sub: "LanceDB",        pos: [  3, 3,  3], color: 0xa78bfa },
  { id: "wiki",   label: "Wiki",         sub: "metrics, claims", pos: [  8, 3,  0], color: 0xf59e0b },
  { id: "ready",  label: "Ready",        sub: "queryable row",  pos: [ 12, 3, -3], color: 0x10b981 },
];

const EDGES: Array<{ from: string; to: string }> = [
  { from: "upload", to: "render" },
  { from: "render", to: "vision" },
  { from: "vision", to: "index" },
  { from: "index",  to: "wiki"  },
  { from: "wiki",   to: "ready" },
];

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
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false });
  const sp = new THREE.Sprite(mat);
  sp.scale.set(scale * 3.2, scale, 1);
  return sp;
}

interface Props {
  documentId: string;
  onClose: () => void;
  variant?: "overlay" | "panel";
}

export function IngestFlowOverlay({ documentId, onClose, variant = "overlay" }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<{
    cleanup: () => void;
    setState: (set: Set<string>, stage: IngestStage, page: number | null, of: number | null) => void;
  } | null>(null);

  const ingest = useGrid((s) => s.ingests[documentId]);
  const stage: IngestStage = ingest?.stage ?? "queued";
  const page = ingest?.page ?? null;
  const of = ingest?.of ?? null;
  const activeSet = useMemo(() => new Set(ACTIVE_STAGES[stage]), [stage]);

  useEffect(() => {
    if (variant !== "overlay") return;
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onClose(); }
    };
    window.addEventListener("keydown", h, true);
    return () => window.removeEventListener("keydown", h, true);
  }, [onClose, variant]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0x09090b, 20, 80);

    const camera = new THREE.PerspectiveCamera(55, container.clientWidth / container.clientHeight, 0.1, 200);
    camera.position.set(14, 10, 20);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setClearColor(0x09090b, 1);
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true; controls.dampingFactor = 0.08;
    controls.target.set(0, 1, 0);

    scene.add(new THREE.AmbientLight(0xffffff, 0.35));
    const l1 = new THREE.PointLight(0x38bdf8, 1.0, 60, 2); l1.position.set(8, 12, 8); scene.add(l1);
    const l2 = new THREE.PointLight(0xa78bfa, 0.6, 50, 2); l2.position.set(-10, 8, -6); scene.add(l2);
    const l3 = new THREE.PointLight(0x10b981, 0.6, 40, 2); l3.position.set(0, -4, 10); scene.add(l3);

    const grid = new THREE.GridHelper(60, 30, 0x27272a, 0x18181b);
    grid.position.y = -2; scene.add(grid);

    // Stage nodes
    const nodeByStage = new Map<string, { group: THREE.Group; core: THREE.Mesh; glow: THREE.Mesh; color: number; label: THREE.Sprite }>();
    const nodeGroup = new THREE.Group(); scene.add(nodeGroup);
    for (const s of STAGES) {
      const g = new THREE.Group();
      g.position.set(...s.pos);
      const glowMat = new THREE.MeshBasicMaterial({ color: s.color, transparent: true, opacity: 0.15, side: THREE.BackSide });
      const glow = new THREE.Mesh(new THREE.SphereGeometry(1.7, 32, 32), glowMat); g.add(glow);
      const core = new THREE.Mesh(
        new THREE.IcosahedronGeometry(0.9, 1),
        new THREE.MeshStandardMaterial({ color: s.color, emissive: s.color, emissiveIntensity: 0.4, metalness: 0.3, roughness: 0.3 }),
      );
      g.add(core);
      const label = makeLabel(s.label, s.sub, 1.0);
      label.position.set(0, 1.9, 0);
      g.add(label);
      nodeGroup.add(g);
      nodeByStage.set(s.id, { group: g, core, glow, color: s.color, label });
    }

    // Edges with animated particles
    interface EdgeObj { key: string; curve: THREE.QuadraticBezierCurve3; tubeMat: THREE.MeshBasicMaterial; particles: Array<{ mesh: THREE.Mesh; t: number; speed: number }>; }
    const edges: EdgeObj[] = [];
    for (const e of EDGES) {
      const a = nodeByStage.get(e.from)!.group.position;
      const b = nodeByStage.get(e.to)!.group.position;
      const mid = new THREE.Vector3().addVectors(a, b).multiplyScalar(0.5); mid.y += 1;
      const curve = new THREE.QuadraticBezierCurve3(a.clone(), mid, b.clone());
      const tubeGeom = new THREE.TubeGeometry(curve, 64, 0.06, 8, false);
      const tubeMat = new THREE.MeshBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.12 });
      scene.add(new THREE.Mesh(tubeGeom, tubeMat));
      const particles: EdgeObj["particles"] = [];
      for (let i = 0; i < 4; i++) {
        const m = new THREE.Mesh(
          new THREE.SphereGeometry(0.1, 12, 12),
          new THREE.MeshBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.0 }),
        );
        scene.add(m);
        particles.push({ mesh: m, t: i / 4, speed: 0.25 });
      }
      edges.push({ key: `${e.from}->${e.to}`, curve, tubeMat, particles });
    }

    // PDF "page stack" that fills in as vision processes pages
    const pdfGroup = new THREE.Group();
    pdfGroup.position.set(-2, 3, -5);
    const maxPages = 50;
    const pageMeshes: THREE.Mesh[] = [];
    for (let i = 0; i < maxPages; i++) {
      const page = new THREE.Mesh(
        new THREE.BoxGeometry(2.2, 3, 0.04),
        new THREE.MeshStandardMaterial({
          color: 0xfafafa, metalness: 0.1, roughness: 0.7,
          transparent: true, opacity: 0.0,
        }),
      );
      const row = Math.floor(i / 10);
      const col = i % 10;
      page.position.set((col - 4.5) * 0.3, (row - 2) * 0.3, -i * 0.01);
      page.rotation.y = -0.1;
      pdfGroup.add(page);
      pageMeshes.push(page);
    }
    scene.add(pdfGroup);

    // Active state (closure reads)
    let activeStageSet = new Set<string>(["upload"]);
    let currentStage: IngestStage = "queued";
    let currentPage: number | null = null;
    let currentOf: number | null = null;

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
        const isFail = currentStage === "failed";
        const targetGlow = isFail && id === "vision" ? 0.7 : isActive ? 0.45 : 0.08;
        (nd.glow.material as THREE.MeshBasicMaterial).opacity += (targetGlow - (nd.glow.material as THREE.MeshBasicMaterial).opacity) * 0.08;
        const coreMat = nd.core.material as THREE.MeshStandardMaterial;
        const targetE = isFail && id === "vision" ? 1.5 : isActive ? 1.1 : 0.2;
        coreMat.emissiveIntensity += (targetE - coreMat.emissiveIntensity) * 0.1;
        const pulse = isActive ? 1 + Math.sin(t * 4 + nd.group.position.x * 0.3) * 0.1 : 1;
        nd.core.scale.setScalar(pulse);
        nd.core.rotation.y = t * 0.3; nd.core.rotation.x = t * 0.2;
      }

      for (const e of edges) {
        const [from, to] = e.key.split("->");
        const active = activeStageSet.has(from) && activeStageSet.has(to);
        const targetEdge = active ? 0.65 : 0.08;
        e.tubeMat.opacity += (targetEdge - e.tubeMat.opacity) * 0.08;
        const pOp = active ? 0.95 : 0.0;
        for (const p of e.particles) {
          p.t += (active ? p.speed : 0.05) * dt;
          if (p.t > 1) p.t = 0;
          p.mesh.position.copy(e.curve.getPoint(p.t));
          const m = p.mesh.material as THREE.MeshBasicMaterial;
          m.opacity += (pOp - m.opacity) * 0.12;
        }
      }

      // Page stack opacity: how many pages vision has finished
      const pagesDone = currentPage ?? 0;
      const totalPages = currentOf ?? 10;
      for (let i = 0; i < pageMeshes.length; i++) {
        const mat = pageMeshes[i].material as THREE.MeshStandardMaterial;
        const inRange = i < totalPages;
        const processed = i < pagesDone;
        const target = !inRange ? 0.0 : processed ? 0.95 : 0.25;
        mat.opacity += (target - mat.opacity) * 0.08;
        if (processed) mat.color.lerp(new THREE.Color(0x38bdf8), 0.02);
      }

      pdfGroup.rotation.y = Math.sin(t * 0.2) * 0.15;
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    sceneRef.current = {
      setState: (set, stg, p, o) => {
        activeStageSet = set;
        currentStage = stg;
        currentPage = p;
        currentOf = o;
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
    sceneRef.current.setState(activeSet, stage, page, of);
    return () => { sceneRef.current?.cleanup(); sceneRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    sceneRef.current?.setState(activeSet, stage, page, of);
  }, [activeSet, stage, page, of]);

  return (
    <div className={variant === "panel" ? "h-full w-full relative" : "fixed inset-0 z-50 bg-[var(--color-canvas)]"}>
      {variant === "overlay" && (
        <div className="h-11 flex items-center justify-between px-4 border-b border-[var(--color-border)] bg-[var(--color-canvas)]/80 backdrop-blur">
          <div className="flex items-center gap-3 text-[12px]">
            <div className="font-[var(--font-ui)]">◇ Ingest · 3D</div>
            <div className="h-3 w-px bg-[var(--color-border)]" />
            <div className="text-[var(--color-muted)] font-[var(--font-mono)]">
              {ingest?.filename ?? documentId.slice(0, 10)}
            </div>
            <div className="h-3 w-px bg-[var(--color-border)]" />
            <div className="flex items-center gap-1.5 text-[var(--color-muted)] font-[var(--font-mono)]">
              <span className={[
                "h-1.5 w-1.5 rounded-full",
                stage === "ready" ? "bg-[var(--color-accent-done)]"
                  : stage === "failed" ? "bg-[var(--color-accent-fail)]"
                  : "bg-[var(--color-accent-streaming)] animate-pulse",
              ].join(" ")}></span>
              {stage}{page && of ? ` · page ${page}/${of}` : ""}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded border border-[var(--color-border)] text-[var(--color-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-surface)]"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      <div ref={containerRef} className={variant === "panel" ? "absolute inset-0" : "absolute inset-0 top-11"} />

      {variant === "overlay" && (
        <div className="absolute left-5 bottom-5 p-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]/75 backdrop-blur text-[12px] max-w-xs leading-snug">
          <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted)] mb-1.5">Ingest pipeline</div>
          <div className="space-y-1">
            <div>Upload · pdf bytes arrive on server</div>
            <div>Render · each page rasterised to PNG</div>
            <div>Vision · gpt 4.1 returns markdown per page</div>
            <div>Index · chunks embedded into LanceDB</div>
            <div>Wiki · gpt 4.1 extracts metrics + claims</div>
            <div>Ready · row is queryable</div>
          </div>
        </div>
      )}
    </div>
  );
}
