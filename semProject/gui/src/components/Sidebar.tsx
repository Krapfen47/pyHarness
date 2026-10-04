// The left column: start a run, the live run, past runs, and system health.

import type { Health, RunSummary } from "../events";
import { modelLabel, runLabel, STATUS_TEXT, STATUS_TONE } from "../format";
import type { RunView } from "../state";
import { StageTag, STAGE_HINT } from "./common";

export type Selection =
  | { kind: "launcher" }
  | { kind: "live" }
  | { kind: "history"; runId: string };

const RESERVED: { label: string; stage: 2 | 3 }[] = [
  { label: "Sessions", stage: 2 },
  { label: "Repo map", stage: 2 },
  { label: "Approvals", stage: 3 },
  { label: "Policy", stage: 3 },
];

export function Sidebar({ selection, onSelect, live, liveRunning, runs, health }: {
  selection: Selection;
  onSelect: (selection: Selection) => void;
  live: RunView;
  liveRunning: boolean;
  runs: RunSummary[];
  health: Health | null;
}) {
  const liveStatus = live.finished?.status;
  return (
    <nav className="sidebar">
      <div className="side-section">
        <button className={`side-item ${selection.kind === "launcher" ? "selected" : ""}`}
          onClick={() => onSelect({ kind: "launcher" })}>
          <span className="grow">+ New run</span>
        </button>
        {live.runId && (
          <button className={`side-item ${selection.kind === "live" ? "selected" : ""}`}
            onClick={() => onSelect({ kind: "live" })}>
            <span className={`dot ${liveRunning ? "live" : STATUS_TONE[liveStatus ?? ""] ?? ""}`} />
            <span className="grow">
              <div>{liveRunning ? "Live run" : "Last live run"}</div>
              <div className="meta">{live.start?.task ?? live.launch?.mode ?? ""}
                {liveStatus ? ` · ${STATUS_TEXT[liveStatus] ?? liveStatus}` : ""}</div>
            </span>
          </button>
        )}
      </div>

      <div className="side-section"><div className="label">History</div></div>
      <div className="history">
        {runs.length === 0 && <div className="faint small" style={{ padding: "0 8px" }}>No runs yet.</div>}
        {runs.map((run) => (
          <button key={run.run_id}
            className={`side-item ${selection.kind === "history" && selection.runId === run.run_id ? "selected" : ""}`}
            onClick={() => onSelect({ kind: "history", runId: run.run_id })}
            title={`${run.run_id}: ${STATUS_TEXT[run.status] ?? run.status}`}>
            <span className={`dot ${STATUS_TONE[run.status] ?? ""}`} />
            <span className="grow" style={{ minWidth: 0 }}>
              <div className="ellipsis">{runLabel(run.run_id)}
                {run.mode === "baseline" && <span className="faint"> · baseline</span>}</div>
              <div className="meta ellipsis">
                {run.model ? modelLabel(run.model).replace(/ \(.*\)$/, "") : "no model"}
                {run.turns !== null ? ` · ${run.turns} turns` : ""}
              </div>
            </span>
          </button>
        ))}
      </div>

      <div className="side-section">
        <div className="label">Coming later</div>
        {RESERVED.map((item) => (
          <div key={item.label} className="side-item reserved" title={STAGE_HINT[item.stage]}>
            <span className="grow">{item.label}</span><StageTag stage={item.stage} />
          </div>
        ))}
      </div>

      <div className="health small">
        <div className="row" title={health?.ollama.detail ?? ""}>
          <span className={`dot ${health ? (health.ollama.ok ? "ok" : "bad") : ""}`} />
          {health ? (health.ollama.ok ? `Ollama · ${health.ollama.models.length} models`
            : "Ollama not reachable") : "checking Ollama…"}
        </div>
        <div className="row" title={health?.docker.detail ?? ""}>
          <span className={`dot ${health ? (health.docker.ok ? "ok" : "warn") : ""}`} />
          {health ? (health.docker.ok ? "Docker running" : "Docker not running") : "checking Docker…"}
        </div>
      </div>
    </nav>
  );
}
