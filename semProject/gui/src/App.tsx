// The app shell: loads data, keeps the live connection, and arranges the panels.
//
//   ┌ TopBar ─────────────────────────────────────────────────────┐
//   ├ PhaseStrip (+ FlowDiagram) ─────────────────────────────────┤
//   │ Sidebar │ Timeline (or Launcher)          │ Inspector       │
//   │         │ Composer                        │                 │
//   ├ BudgetBar ──────────────────────────────────────────────────┤

import { useCallback, useEffect, useMemo, useReducer, useState } from "react";
import { api, openLive, type LiveStatus } from "./api";
import type { HarnessEvent, Health, RunSummary, StartRunBody, TaskInfo, UnknownEvent } from "./events";
import { emptyRun, isRunning, reduce, replay, type RunView } from "./state";
import { BudgetBar } from "./components/BudgetBar";
import { StageTag, STAGE_HINT } from "./components/common";
import { FlowDiagram } from "./components/FlowDiagram";
import { Inspector, type InspectorTab } from "./components/Inspector";
import { Launcher } from "./components/Launcher";
import { ReplayBar } from "./components/ReplayBar";
import { Sidebar, type Selection } from "./components/Sidebar";
import { Timeline } from "./components/Timeline";
import { PhaseStrip, TopBar } from "./components/TopBar";

// Remember small UI preferences across reloads. Wrapped in try/catch because
// storage can be unavailable (e.g. private windows).
function stored(key: string, fallback: boolean): boolean {
  try { return (localStorage.getItem(key) ?? String(fallback)) === "true"; } catch { return fallback; }
}
function store(key: string, value: boolean) {
  try { localStorage.setItem(key, String(value)); } catch { /* ignore */ }
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [tasks, setTasks] = useState<TaskInfo[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selection, setSelection] = useState<Selection>({ kind: "launcher" });
  const [selectedTurn, setSelectedTurn] = useState<number | null>(null); // null = follow the newest
  const [tab, setTab] = useState<InspectorTab>("turn");
  const [showFlow, setShowFlow] = useState(() => stored("showFlow", true));
  const [liveStatus, setLiveStatus] = useState<LiveStatus>("connecting");

  // The live run: every event from the server goes through the reducer.
  const [live, dispatch] = useReducer(reduce, null, () => emptyRun());

  // A past run: its events, and how far the replay slider is.
  const [history, setHistory] = useState<{ runId: string; events: (HarnessEvent | UnknownEvent)[] } | null>(null);
  const [replayIndex, setReplayIndex] = useState(0);
  const [playing, setPlaying] = useState(false);

  const refreshRuns = useCallback(() => { api.runs().then(setRuns, () => {}); }, []);

  // ---- loading ----

  useEffect(() => {
    api.tasks().then(setTasks, () => {});
    refreshRuns();
    let first = true;
    const check = () => api.health().then((h) => {
      setHealth(h);
      if (first && h.active_run) setSelection({ kind: "live" }); // a run is already going
      first = false;
    }, () => {});
    check();
    const timer = setInterval(check, 15_000);
    return () => clearInterval(timer);
  }, [refreshRuns]);

  useEffect(() => openLive(dispatch, setLiveStatus), []);

  // When the live run finishes, it shows up in History.
  const liveFinished = live.finished?.seq;
  useEffect(() => { if (liveFinished) refreshRuns(); }, [liveFinished, refreshRuns]);

  // Load a past run when it is selected.
  useEffect(() => {
    if (selection.kind !== "history") return;
    let cancelled = false;
    api.run(selection.runId).then((data) => {
      if (cancelled) return;
      setHistory({ runId: data.run_id, events: data.events });
      setReplayIndex(data.events.length);
      setPlaying(false);
    }, () => {});
    return () => { cancelled = true; };
  }, [selection]);

  // ---- what to show ----

  const historyView = useMemo<RunView | null>(() => {
    if (selection.kind !== "history" || !history || history.runId !== selection.runId) return null;
    return replay(history.events, replayIndex);
  }, [selection, history, replayIndex]);

  const view: RunView | null = selection.kind === "live" ? live
    : selection.kind === "history" ? historyView : null;
  const liveRunning = isRunning(live) && !live.finished;
  const turn = view?.turns.find((t) => t.n === selectedTurn) ?? view?.turns[view.turns.length - 1];

  // ---- actions ----

  const select = useCallback((next: Selection) => {
    setSelection(next);
    setSelectedTurn(null);
  }, []);

  const startRun = useCallback(async (body: StartRunBody) => {
    await api.start(body); // throws on error; the Launcher shows the message
    setSelectedTurn(null);
    setTab("turn");
    setSelection({ kind: "live" });
  }, []);

  const stopRun = useCallback(() => {
    if (live.runId) api.stop(live.runId).catch(() => {});
  }, [live.runId]);

  const selectTurn = useCallback((n: number) => {
    // Clicking the newest turn goes back to "follow the newest".
    setSelectedTurn((current) => (current === n ? null : n));
  }, []);

  const toggleFlow = () => { setShowFlow(!showFlow); store("showFlow", !showFlow); };

  return (
    <div className="app">
      <TopBar view={view} live={selection.kind === "live"} running={selection.kind === "live" && liveRunning}
        onStop={stopRun} onNewRun={() => select({ kind: "launcher" })} />
      {view ? <div>
        <PhaseStrip view={view} showFlow={showFlow} onToggleFlow={toggleFlow} />
        {showFlow && <FlowDiagram view={view} />}
      </div> : <div />}

      <div className={`body ${view ? "" : "no-inspector"}`}>
        <Sidebar selection={selection} onSelect={select} live={live} liveRunning={liveRunning}
          runs={runs} health={health} />

        <main className="main">
          {selection.kind === "history" && history && history.runId === selection.runId && (
            <ReplayBar events={history.events} index={replayIndex} onIndex={setReplayIndex}
              playing={playing} onPlaying={setPlaying} />
          )}
          {selection.kind === "live" && liveStatus !== "open" && (
            <div className="notice warn" style={{ margin: "10px 20px 0" }}>
              Connection to the harness server lost, reconnecting…</div>
          )}
          {view ? (
            <>
              <div className="scroll grow">
                {view.runId ? (
                  <Timeline view={view} live={selection.kind === "live"} selectedTurn={selectedTurn}
                    onSelectTurn={selectTurn} onOpenPrompt={() => { setSelectedTurn(1); setTab("prompt"); }} />
                ) : <div className="empty">No live run yet. Start one with “New run”.</div>}
              </div>
              <Composer view={view} />
            </>
          ) : (
            <Launcher tasks={tasks} health={health} busy={liveRunning} onStart={startRun} />
          )}
        </main>

        {view && <Inspector view={view} turn={turn} tab={tab} onTab={setTab} />}
      </div>

      {view ? <BudgetBar view={view} /> : <div />}
    </div>
  );
}

// The bottom of the main column. In Stage 1 a run has exactly one request (the
// task); Stage 2 sessions turn this into a chat box for follow-up requests.
function Composer({ view }: { view: RunView }) {
  const request = view.start?.request;
  return (
    <div className="composer">
      <div className="composer-inner">
        {request && (
          <div className="row small">
            <span className="label">request</span>
            <span className="muted ellipsis grow" title={request}>{request.replace(/\s+/g, " ")}</span>
          </div>
        )}
        <div className="row reserved" title={STAGE_HINT[2]}>
          <textarea rows={1} disabled placeholder="Send a follow-up request to the agent…" />
          <StageTag stage={2} />
        </div>
      </div>
    </div>
  );
}
