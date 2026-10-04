// The center column: the whole run as a vertical list of cards, in the order
// things happened: setup -> context -> turns -> loop end -> verification -> verdict.

import { useEffect, useRef } from "react";
import { chars, modelLabel, seconds } from "../format";
import { estimateTokens, type RunView } from "../state";
import { CodeBlock, Pill, StatusPill } from "./common";
import { TurnCard } from "./TurnCard";

const SETUP_TEXT: Record<string, Record<string, string>> = {
  task: { ok: "Task loaded" },
  workspace: { ok: "Fresh workspace cloned" },
  sandbox: { building: "Building the sandbox image (first run only)", ok: "Sandbox image ready",
    unavailable: "Sandbox unavailable: checks will be reported as unavailable" },
  patch: { ok: "Reference patch applied" },
  model: { ok: "Model" },
};

function SetupCard({ view }: { view: RunView }) {
  if (view.setup.length === 0 && !view.launch) return null;
  return (
    <div className="card">
      <div className="card-head"><h3>Setup</h3>
        {view.launch && <span className="faint small">{view.launch.mode === "baseline"
          ? "baseline: verification only, no model" : "model run"}</span>}
      </div>
      <div className="card-body checklist">
        {view.setup.map((step) => (
          <div key={step.step} className="check-row">
            {step.status === "building" && !view.finished ? <span className="spinner" />
              : <span className={`dot ${step.status === "ok" ? "ok" : step.status === "building" ? "" : "warn"}`} />}
            <span>{SETUP_TEXT[step.step]?.[step.status] ?? `${step.step}: ${step.status}`}</span>
            <span className="mono faint ellipsis grow" title={step.detail}>
              {step.step === "model" ? modelLabel(step.detail) : step.detail}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ContextCard({ view, onOpen }: { view: RunView; onOpen: () => void }) {
  if (!view.context) return null;
  const total = view.context.reduce((sum, m) => sum + m.content.length, 0);
  return (
    <div className="card clickable" onClick={onOpen} title="Show the exact messages in the Prompt tab">
      <div className="card-head">
        <h3>Context</h3>
        <span className="muted">the model's starting knowledge:</span>
        {view.context.map((m, i) => (
          <Pill key={i}>{m.role === "system" ? "rules + tools" : "task + file list"} · {chars(m.content.length)}</Pill>
        ))}
        <span className="grow" />
        <span className="faint small">≈ {estimateTokens(total)} tokens</span>
      </div>
    </div>
  );
}

function StopCard({ view }: { view: RunView }) {
  const stop = view.stop;
  if (!stop) return null;
  const tone = stop.stop_reason === "final" ? "info" : stop.stop_reason === "cancelled" ? "warn" : "bad";
  return (
    <div className="card">
      <div className="card-head">
        <h3>Agent loop ended</h3>
        <Pill tone={tone}>{stop.stop_reason.replace("_", " ")}</Pill>
        <span className="muted grow">{stop.reason}</span>
        <span className="faint small">
          {stop.turns} turns · {stop.actions} actions · {stop.retries} retries · {stop.denied} denied
          · {stop.errors} errors · {stop.repeats} repeats
        </span>
      </div>
    </div>
  );
}

function VerificationCard({ view }: { view: RunView }) {
  if (view.verifyChecks.length === 0) return null;
  const changed = view.verification?.changed_files;
  return (
    <div className="card">
      <div className="card-head">
        <h3>Verification</h3>
        <span className="muted">run by the harness in fresh sandbox containers, not by the model</span>
      </div>
      <div className="card-body">
        <div className="checklist">
          {view.verifyChecks.map((check) => (
            <div key={check.name} className="check-row">
              {check.running ? <span className="spinner" />
                : check.result ? <StatusPill status={check.result.status} />
                  : <span className="dot" />}
              <span className="mono">{check.name}</span>
              <span className="faint small grow">
                {check.name === "scope" ? "every change inside the writable area?"
                  : check.result?.exit_code !== undefined && check.result?.exit_code !== null
                    ? `exit ${check.result.exit_code}` : ""}
              </span>
              {check.result?.duration ? <span className="faint small">{seconds(check.result.duration)}</span> : null}
            </div>
          ))}
        </div>
        {changed && (
          <div className="row wrap small">
            <span className="label">changed files</span>
            {changed.length === 0 ? <span className="faint">none</span>
              : changed.map((f) => <span key={f} className="mono">{f}</span>)}
          </div>
        )}
      </div>
    </div>
  );
}

function VerdictCard({ view }: { view: RunView }) {
  const { finished, stop, verification } = view;
  if (!finished || finished.status === "error") return null;
  const baseline = view.start?.mode === "baseline" || view.launch?.mode === "baseline";
  const passed = verification?.passed ?? finished.passed;
  return (
    <div className="verdict">
      <div className="claim">
        <span className="label">{baseline ? "baseline" : "the model's claim (unverified)"}</span>
        <div style={{ marginTop: 4 }}>
          {baseline ? "No model involved: only the starting code was checked."
            : stop?.final_message ?? `No final answer: the loop stopped (${stop?.stop_reason ?? "?"}).`}
        </div>
      </div>
      <div className={passed ? "passed" : "failed"}>
        <span className="label">the harness's verdict</span>
        <div className="big" style={{ color: passed ? "var(--ok)" : "var(--bad)" }}>
          {finished.status === "cancelled" ? "STOPPED · NOT VERIFIED"
            : passed ? "VERIFIED" : "NOT VERIFIED"}
        </div>
        <div className="small muted">
          {passed ? "every check passed" : "at least one check did not pass (or could not run)"}
        </div>
      </div>
    </div>
  );
}

export function Timeline({ view, live, selectedTurn, onSelectTurn, onOpenPrompt }: {
  view: RunView;
  live: boolean;
  selectedTurn: number | null;
  onSelectTurn: (n: number) => void;
  onOpenPrompt: () => void;
}) {
  const bottom = useRef<HTMLDivElement>(null);
  const container = useRef<HTMLDivElement>(null);
  const stick = useRef(true); // follow new events, unless the user scrolled up

  useEffect(() => {
    const element = container.current?.parentElement;
    if (!element) return;
    const onScroll = () => {
      stick.current = element.scrollHeight - element.scrollTop - element.clientHeight < 120;
    };
    element.addEventListener("scroll", onScroll);
    return () => element.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (live && stick.current) bottom.current?.scrollIntoView({ block: "end" });
  });

  const lastTurn = view.turns[view.turns.length - 1]?.n;
  return (
    <div className="timeline" ref={container}>
      <SetupCard view={view} />
      {view.error && (
        <div className="notice bad"><b>Setup failed:</b> {view.error}</div>
      )}
      <ContextCard view={view} onOpen={onOpenPrompt} />
      {view.turns.map((turn) => (
        <TurnCard key={turn.n} turn={turn} selected={selectedTurn === turn.n}
          live={live && !view.stop && turn.n === lastTurn} onSelect={onSelectTurn} />
      ))}
      {view.stopRequested && !view.finished && (
        <div className="notice warn">Stopping: cutting off the model, removing containers…</div>
      )}
      <StopCard view={view} />
      <VerificationCard view={view} />
      <VerdictCard view={view} />
      {view.unknown.map((event) => (
        <div key={event.seq} className="card">
          <div className="card-head"><h3>{event.type}</h3><span className="faint small">event this GUI doesn't know yet</span></div>
          <div className="card-body"><CodeBlock text={JSON.stringify(event, null, 2)} clampLines={8} /></div>
        </div>
      ))}
      <div ref={bottom} />
    </div>
  );
}
