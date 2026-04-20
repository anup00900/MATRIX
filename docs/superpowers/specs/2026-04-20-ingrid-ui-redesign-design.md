# INGRID UI Redesign — Design Spec

**Date:** 2026-04-20  
**Status:** Approved

---

## Overview

Rename the product from "Matrix" to "INGRID", add a Hebbia-style sidebar with session history and templates directly accessible (not buried in ⌘K), and integrate the 3D pipeline view inline as a collapsible right panel instead of a full-screen overlay.

---

## 1. Shell Layout

Three horizontal panels inside a full-height flex row, spanning below the top bar:

```
┌────────────────────────────────────────────────────┐
│                    TopBar (full width)              │
├──────┬──────────────────────────────┬──────────────┤
│ Icon │                              │   3D Panel   │
│ Rail │         Grid (main)          │  (collapsible│
│ 40px │       fills remaining        │   ~300px)    │
└──────┴──────────────────────────────┴──────────────┘
```

- Icon rail is always visible (40px, fixed).
- Grid fills all remaining horizontal space.
- 3D panel is closed by default; toggled via a button in the top bar. When open the grid shrinks to accommodate it. No full-screen overlays.

---

## 2. Icon Rail (Left)

A 40px wide vertical strip always visible on the left edge. Four icons:

| Position | Icon | Action |
|----------|------|--------|
| Top | `◇` (INGRID logo) | Collapses any open flyout / home |
| 2 | `⊞` Sessions | Opens Sessions flyout |
| 3 | `⊡` Templates | Opens Templates flyout |
| Bottom | `⚙` Settings | Opens Settings flyout (stub for now) |

- Active icon is highlighted in accent blue (`#4f8ef7`).
- Clicking the active icon again collapses the flyout.
- Only one flyout open at a time.

---

## 3. Flyout Panel

Slides out from the left, overlapping the grid (not pushing it). Width ~220px. Closes on outside click or re-clicking the active icon. Dark background (`#111`), subtle border, no animation jank — `transform: translateX` with `transition: 0.18s ease`.

### Sessions view

```
[ + New session           ]
─────────────────────────
Today
  ● Acme Corp Contracts   ← active (highlighted)
    Q4 Earnings Review
Yesterday
    Vendor Risk Audit
─────────────────────────
```

- "New session" button creates a new workspace + grid, switches to it.
- Sessions are stored in Zustand; loaded from backend workspace list.
- Truncated to one line with `text-overflow: ellipsis`.
- Active session highlighted.

### Templates view

Three cards, one per template:

```
┌─────────────────────────┐
│ Risk Extraction          │
│ 4 columns — legal risk,  │
│ compliance, exposure...  │
│          [Use template]  │
└─────────────────────────┘
```

- "Use template" creates a new session pre-loaded with that template's columns.
- Templates: Risk Extraction, Revenue & Margins, Auditor Review (from `templates.ts`).

---

## 4. Inline 3D Pipeline Panel (Right)

- A `[⬡ 3D]` toggle button in the top bar opens/closes the right panel.
- The existing `FlowOverlay` Three.js scene renders inside this panel — no full-screen takeover.
- Panel width: `300px`, fixed, not resizable in v1.
- When closed: grid uses full remaining width. When open: grid shrinks by 300px.
- State managed in Zustand (`show3D: boolean`).

---

## 5. Branding Changes

| Location | Before | After |
|----------|--------|-------|
| TopBar brand text | `◇ Matrix` | `◇ INGRID` |
| Page `<title>` | `Matrix PoC` | `INGRID` |
| Any other UI string | "Matrix" | "INGRID" |

---

## 6. Command Palette (⌘K) Changes

Templates are removed from ⌘K since they now live in the sidebar. ⌘K retains:

- Add column
- Add documents
- Export CSV / Export JSON
- Switch retriever (Naive / ISD / Wiki)
- Open 3D flow (same as the top-bar toggle, kept as shortcut)

---

## 7. Component Breakdown

| File | Change |
|------|--------|
| `frontend/src/components/Sidebar.tsx` | **New** — icon rail + flyout, renders `SessionList` and `TemplateList` sub-components |
| `frontend/src/components/SessionList.tsx` | **New** — session rows grouped by Today / Yesterday, new-session button |
| `frontend/src/components/TemplateList.tsx` | **New** — 3 template cards with "Use template" action |
| `frontend/src/components/InlineFlowPanel.tsx` | **New** — right-panel wrapper that hosts the existing FlowOverlay Three.js scene |
| `frontend/src/components/TopBar.tsx` | **Edit** — rename brand text to INGRID, add `[⬡ 3D]` toggle button |
| `frontend/src/components/CommandBar.tsx` | **Edit** — remove Templates entries |
| `frontend/src/App.tsx` | **Edit** — adopt 3-panel flex layout, wire sidebar open state and 3D panel open state |
| `frontend/src/store/grid.ts` | **Edit** — add `show3D: boolean`, `sidebarView: 'sessions' \| 'templates' \| null` |
| `frontend/index.html` | **Edit** — `<title>INGRID</title>` |

---

## 8. Data Flow

```
User clicks Sessions icon
  → store.sidebarView = 'sessions'
  → Sidebar flyout opens, SessionList renders workspace list from store

User clicks "Use template"
  → creates new workspace (POST /workspaces)
  → adds template columns (POST /workspaces/:id/columns)
  → store.workspaceId = new id
  → sidebarView = null (flyout closes)

User clicks [⬡ 3D] in TopBar
  → store.show3D = !show3D
  → InlineFlowPanel renders/hides in right slot
```

---

## 9. Out of Scope (v1)

- Sidebar resize handle
- Session rename / delete
- Settings flyout (stub icon only)
- Persisting sidebar open state across reloads
