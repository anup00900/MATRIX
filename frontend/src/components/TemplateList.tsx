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
