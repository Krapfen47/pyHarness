// The "New run" form: the handout's submit_task(), as a page.

import { useEffect, useState } from "react";
import type { Health, StartRunBody, TaskInfo } from "../events";
import { CodeBlock, Pill, StageTag, STAGE_HINT } from "./common";

type Kind = "model" | "scripted" | "baseline" | "baseline_patch";

const KINDS: { id: Kind; title: string; text: string }[] = [
  { id: "model", title: "Model run", text: "The LLM works on the task, then the harness verifies." },
  { id: "scripted", title: "Scripted demo", text: "Replays reference_script.json. No model needed." },
  { id: "baseline", title: "Baseline", text: "Only verify the starting code. Acceptance must fail." },
  { id: "baseline_patch", title: "Baseline + reference fix", text: "Apply reference_fix.patch first. Everything must pass." },
];

const PREFERRED_MODEL = "qwen2.5-coder:14b"; // passed 2 of 2 real runs (see README)

export function Launcher({ tasks, health, busy, onStart }: {
  tasks: TaskInfo[];
  health: Health | null;
  busy: boolean;
  onStart: (body: StartRunBody) => Promise<void>;
}) {
  const [taskId, setTaskId] = useState("");
  const [kind, setKind] = useState<Kind>("model");
  const [model, setModel] = useState("");
  const [maxActions, setMaxActions] = useState(30);
  const [pace, setPace] = useState(0.15);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    if (!taskId && tasks.length > 0) setTaskId(tasks[0].id);
  }, [tasks, taskId]);

  const models = health?.ollama.models ?? [];
  useEffect(() => {
    if (model || models.length === 0) return;
    const fallback = health?.ollama.default && models.includes(health.ollama.default)
      ? health.ollama.default : models[0];
    setModel(models.includes(PREFERRED_MODEL) ? PREFERRED_MODEL : fallback);
  }, [models, model, health]);

  const task = tasks.find((t) => t.id === taskId);
  const unavailable = (k: Kind) =>
    (k === "scripted" && !task?.has_script) || (k === "baseline_patch" && !task?.has_patch);

  async function start() {
    if (!task) { setError("Pick a task first."); return; }
    if (kind === "model" && !model) { setError("Pick a model first."); return; }
    setError(null);
    setStarting(true);
    try {
      await onStart({
        task: task.id,
        mode: kind.startsWith("baseline") ? "baseline" : "run",
        model: kind === "model" ? model : null,
        scripted: kind === "scripted",
        pace,
        reference_patch: kind === "baseline_patch",
        max_actions: maxActions,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="scroll grow">
      <div className="launcher">
        <div>
          <h2>Start a run</h2>
          <div className="muted">A fresh copy of the repository every time. The model can only
            use checked tools; the checks run in a locked-down Docker container.</div>
        </div>

        <div className="field">
          <span className="label">Task</span>
          <select value={taskId} onChange={(e) => setTaskId(e.target.value)}>
            {tasks.map((t) => <option key={t.id} value={t.id}>{t.name ?? t.id}</option>)}
          </select>
          {task?.error && <div className="notice bad">{task.error}</div>}
          {task?.request && (
            <>
              <div className="row wrap small">
                <span className="mono faint ellipsis">{task.repo_url} @ {task.commit?.slice(0, 12)}</span>
                <span className="grow" />
                {task.writable?.map((w) => <Pill key={w} title="writable">{w}</Pill>)}
              </div>
              <CodeBlock text={task.request} clampLines={8} />
            </>
          )}
        </div>

        <div className="field">
          <span className="label">What to run</span>
          <div className="choice-grid">
            {KINDS.map((k) => (
              <button key={k.id} disabled={unavailable(k.id)}
                className={`choice ${kind === k.id ? "selected" : ""} ${unavailable(k.id) ? "reserved" : ""}`}
                onClick={() => setKind(k.id)}>
                <b>{k.title}</b><span className="small muted">{k.text}</span>
              </button>
            ))}
            <div className="choice reserved" title={STAGE_HINT[2]}>
              <span className="row"><b className="grow">Session</b><StageTag stage={2} /></span>
              <span className="small muted">Keep talking to the agent with follow-up requests.</span>
            </div>
          </div>
        </div>

        <div className="row wrap" style={{ gap: 20 }}>
          {kind === "model" && (
            <label className="field">
              <span className="label">Model</span>
              <select value={model} onChange={(e) => setModel(e.target.value)} style={{ minWidth: 220 }}>
                {models.length === 0 && <option value="">(no models found)</option>}
                {models.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </label>
          )}
          {kind === "scripted" && (
            <label className="field">
              <span className="label">Typing speed (seconds per piece)</span>
              <input type="number" min={0} max={2} step={0.05} value={pace}
                onChange={(e) => setPace(Number(e.target.value))} />
            </label>
          )}
          {!kind.startsWith("baseline") && (
            <label className="field">
              <span className="label">Max actions</span>
              <input type="number" min={1} max={100} value={maxActions}
                onChange={(e) => setMaxActions(Number(e.target.value))} />
            </label>
          )}
        </div>

        {health && !health.docker.ok && (
          <div className="notice warn">Docker is not running. The run still works, but every check
            will be reported as unavailable, so the verdict can't be "verified". Start Docker Desktop
            first for a real run.</div>
        )}
        {health && kind === "model" && !health.ollama.ok && (
          <div className="notice bad">Ollama is not reachable: {health.ollama.detail}</div>
        )}
        {error && <div className="notice bad">{error}</div>}

        <div className="row">
          <button className="btn primary" onClick={start} disabled={starting || busy}>
            ▶ {busy ? "A run is in progress" : starting ? "Starting…" : "Start run"}
          </button>
          <span className="faint small">Ollama's first reply loads the model into memory, which can take a while.</span>
        </div>
      </div>
    </div>
  );
}
