// The bar at the very top: what is running, its status, Stop, and the phase strip.

import { modelLabel, STATUS_TEXT } from "../format";
import type { Phase, RunView } from "../state";
import { Pill, StageTag, STAGE_HINT } from "./common";

export function TopBar({ view, live, running, onStop, onNewRun }: {
  view: RunView | null;
  live: boolean;
  running: boolean;
  onStop: () => void;
  onNewRun: () => void;
}) {
  const start = view?.start;
  const status = view?.finished?.status;
  return (
    <header className="topbar">
      <div className="brand"><span className="brand-mark">&gt;_</span>pyHarness</div>
      {view?.runId && (
        <div className="identity small">
          {(start?.task ?? view.launch?.task) && <span>task <b>{start?.task ?? "…"}</b>
            {start?.commit && <span className="mono faint"> @{start.commit.slice(0, 7)}</span>}</span>}
          <span>model <b className="mono">{start ? (start.model ? modelLabel(start.model) : "none (baseline)") : "…"}</b></span>
          <span className="faint">{live ? "live" : "replay"} · {view.runId}</span>
        </div>
      )}
      <span className="grow" />
      {running && !view?.stopRequested && <Pill tone="accent"><span className="dot live" /> running</Pill>}
      {running && view?.stopRequested && <Pill tone="warn">stopping…</Pill>}
      {!running && status && <Pill tone={status === "verified" ? "ok" : status === "cancelled" ? "warn" : "bad"}>
        {STATUS_TEXT[status] ?? status}</Pill>}
      <span className="reserved row" title={STAGE_HINT[3]}>
        <select disabled aria-label="Autonomy mode"><option>autonomy: full (Stage 1)</option></select>
        <StageTag stage={3} />
      </span>
      {running && live
        ? <button className="btn danger" onClick={onStop} disabled={view?.stopRequested}>■ Stop</button>
        : <button className="btn primary" onClick={onNewRun}>+ New run</button>}
    </header>
  );
}

const PHASES: { id: Phase; label: string }[] = [
  { id: "setup", label: "Setup" },
  { id: "context", label: "Context" },
  { id: "loop", label: "Agent loop" },
  { id: "verification", label: "Verification" },
  { id: "done", label: "Result" },
];

export function PhaseStrip({ view, showFlow, onToggleFlow }: {
  view: RunView; showFlow: boolean; onToggleFlow: () => void;
}) {
  const current = PHASES.findIndex((p) => p.id === view.phase);
  const baseline = view.launch?.mode === "baseline" || view.start?.mode === "baseline";
  return (
    <div className="phases">
      {PHASES.map((phase, i) => {
        const skipped = baseline && (phase.id === "context" || phase.id === "loop");
        const done = i < current || (phase.id === "done" && view.phase === "done");
        const active = i === current && view.phase !== "done";
        return (
          <span key={phase.id} className="row" style={{ gap: 6 }}>
            {i > 0 && <span className="phase-arrow">→</span>}
            <span className={`phase ${active ? "active" : done && !skipped ? "done" : ""}`}
              style={skipped ? { textDecoration: "line-through" } : undefined}>
              {active && <span className="spinner" />}
              {done && !skipped && "✓ "}{phase.label}
              {phase.id === "loop" && view.turns.length > 0 && !baseline &&
                <span className="faint small">· turn {view.turns[view.turns.length - 1].n}</span>}
            </span>
          </span>
        );
      })}
      <span className="grow" />
      <button className="btn small ghost" onClick={onToggleFlow}>
        {showFlow ? "▾ hide architecture" : "▸ show architecture"}
      </button>
    </div>
  );
}
