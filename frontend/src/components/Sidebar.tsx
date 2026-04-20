import { LayoutGrid, FileText } from "lucide-react";
import { useGrid } from "../store/grid";
import type { Session } from "../store/grid";
import { SessionList } from "./SessionList";
import { TemplateList } from "./TemplateList";

interface Props {
  activeGridId: string | null;
  onNewSession: () => void;
  onSwitchSession: (s: Session) => void;
  onUseTemplate: (key: string) => void;
}

export function Sidebar({ activeGridId, onNewSession, onSwitchSession, onUseTemplate }: Props) {
  const { sidebarView, toggleSidebarView, setSidebarView, sessions } = useGrid();

  return (
    <div className="relative flex-shrink-0 z-20">
      {/* 40px icon rail */}
      <div className="w-10 h-full flex flex-col items-center py-3 gap-1
                      border-r border-[var(--color-border)] bg-[var(--color-canvas)]">
        {/* Logo / home */}
        <div className="w-7 h-7 flex items-center justify-center text-[var(--color-accent-streaming)] text-[14px] mb-2 select-none">
          ◇
        </div>

        <button
          onClick={() => toggleSidebarView("sessions")}
          title="Sessions"
          aria-pressed={sidebarView === "sessions"}
          className={`w-7 h-7 rounded-md flex items-center justify-center transition
            ${sidebarView === "sessions"
              ? "bg-[var(--color-accent-streaming)]/15 text-[var(--color-accent-streaming)]"
              : "text-[var(--color-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-surface)]"
            }`}
        >
          <LayoutGrid className="w-3.5 h-3.5" />
        </button>

        <button
          onClick={() => toggleSidebarView("templates")}
          title="Templates"
          aria-pressed={sidebarView === "templates"}
          className={`w-7 h-7 rounded-md flex items-center justify-center transition
            ${sidebarView === "templates"
              ? "bg-[var(--color-accent-streaming)]/15 text-[var(--color-accent-streaming)]"
              : "text-[var(--color-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-surface)]"
            }`}
        >
          <FileText className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Flyout panel — overlays the grid */}
      {sidebarView !== null && (
        <>
          {/* backdrop — click to close */}
          <div
            className="fixed inset-0 z-10"
            onClick={() => setSidebarView(null)}
          />
          <div
            className="absolute top-0 left-10 z-20 w-56 h-full
                       border-r border-[var(--color-border)] bg-[var(--color-canvas)]
                       shadow-2xl overflow-y-auto"
            style={{ maxHeight: "100vh" }}
            onClick={(e) => e.stopPropagation()}
          >
            {sidebarView === "sessions" && (
              <SessionList
                sessions={sessions}
                activeGridId={activeGridId}
                onNewSession={() => { setSidebarView(null); onNewSession(); }}
                onSwitchSession={(s) => { setSidebarView(null); onSwitchSession(s); }}
              />
            )}
            {sidebarView === "templates" && (
              <TemplateList
                onUse={(key) => { setSidebarView(null); onUseTemplate(key); }}
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}
