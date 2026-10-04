// The right column: everything about the selected turn, the exact prompt the
// model saw, the diff, every check's full output, and the run's settings.

import { Fragment, useState } from "react";
import { chars, count, prettyJson, seconds, stringify } from "../format";
import {
  allChecks, estimateTokens, messagesForTurn, runCheckOutput, type RunView, type Turn,
} from "../state";
import type { Message } from "../events";
import { CodeBlock, Gauge, Pill, Section, StageTag, STAGE_HINT, StatusPill } from "./common";
import { EditDiff, UnifiedDiff } from "./DiffView";
import { Gates } from "./TurnCard";

export type InspectorTab = "turn" | "prompt" | "diff" | "checks" | "run";

const TABS: { id: InspectorTab; label: string }[] = [
  { id: "turn", label: "Turn" },
  { id: "prompt", label: "Prompt" },
  { id: "diff", label: "Diff" },
  { id: "checks", label: "Checks" },
  { id: "run", label: "Run" },
];
const RESERVED_TABS: { label: string; stage: 2 | 3 }[] = [
  { label: "Context", stage: 2 },
  { label: "Audit", stage: 3 },
];

// ---- Turn ----

function TurnTab({ view, turn }: { view: RunView; turn: Turn | undefined }) {
  if (!turn) return <div className="empty">Select a turn in the timeline.</div>;
  const stats = turn.stats;
  const check = runCheckOutput(turn);
  const thinking = turn.thinking ?? turn.streamedThinking;
  return (
    <>
      <Section title={`Turn ${turn.n}`}>
        <div className="kv small">
          <span>prompt sent</span><span>{turn.promptMessages} messages · {chars(turn.promptChars)}</span>
          <span>model time</span><span>{seconds(turn.duration)}</span>
          {stats && <>
            <span>tokens read</span><span>{count(stats.prompt_tokens)} (in {seconds(stats.prompt_s)})</span>
            <span>tokens written</span><span>{stats.output_tokens} (in {seconds(stats.output_s)}
              {stats.tokens_per_s ? `, ${stats.tokens_per_s} tok/s` : ""})</span>
            {stats.load_s > 0.05 && <><span>model load</span><span>{seconds(stats.load_s)}</span></>}
            <span>ended because</span><span>{stats.done_reason ?? "–"}</span>
          </>}
        </div>
      </Section>

      <Section title="thinking">
        {thinking ? <CodeBlock text={thinking} className="thinking" />
          : <div className="faint small">
            {view.start?.model?.startsWith("script:") ? "Scripted replies have no thinking."
              : "This model doesn't write separate thinking; its whole output is the reply below. "
                + "Thinking models (e.g. qwen3) with OLLAMA_THINK=true show it here."}
          </div>}
      </Section>

      <Section title="raw reply (untrusted text from the model)">
        {turn.aborted ? <>
          <CodeBlock className="reply" text={turn.aborted.partial || "(nothing written yet)"} clampLines={30} />
          <div className="small" style={{ color: "var(--warn)" }}>cut off: {turn.aborted.reason}</div>
        </> : (
          <CodeBlock className="reply"
            text={turn.reply ?? (turn.streamed || (view.finished ? "(no reply)" : "(waiting…)"))}
            cursor={turn.reply === undefined && !view.finished} clampLines={30} />
        )}
      </Section>

      {turn.reply !== undefined && (
        <Section title="validation"><Gates turn={turn} />
          {turn.invalid && <div style={{ color: "var(--bad)" }}>
            rejected at "{turn.invalid.gate}": {turn.invalid.error}<br />
            <span className="faint">Nothing ran. This counts as a retry; the error goes back to the model.</span>
          </div>}
        </Section>
      )}

      {turn.action && (
        <Section title="parsed action">
          <CodeBlock text={JSON.stringify(turn.action, null, 2)} clampLines={20} />
        </Section>
      )}

      {turn.result && (
        <Section title="tool result" extra={<StatusPill status={turn.result.status} />}>
          {check ? <>
            <div className="row"><StatusPill status={check.status} />
              <span className="small muted">exit {check.exit_code ?? "–"}{check.truncated ? " · output shortened" : ""}</span></div>
            <CodeBlock text={check.output} clampLines={30} />
          </> : <CodeBlock text={stringify(turn.result.output)} clampLines={30} />}
        </Section>
      )}

      {turn.observation !== undefined && (
        <Section title="sent back to the model"
          extra={<span className="faint small">{chars(turn.observation.length)}</span>}>
          <CodeBlock text={prettyJson(turn.observation)} clampLines={20} />
        </Section>
      )}
    </>
  );
}

// ---- Prompt ----

function MessageView({ message, open: initiallyOpen }: { message: Message; open: boolean }) {
  const [open, setOpen] = useState(initiallyOpen);
  const label = message.role === "system" ? "rules + tools"
    : message.role === "assistant" ? "model reply" : message.content.startsWith("{\"source\"")
      ? "tool result" : "task";
  return (
    <div className="message">
      <button className="message-head" onClick={() => setOpen(!open)}>
        <span className={`role ${message.role}`}>{message.role}</span>
        <span className="muted small grow">{label}</span>
        <span className="faint small">{chars(message.content.length)}</span>
        <span className="faint">{open ? "▾" : "▸"}</span>
      </button>
      {open && <pre>{message.content}</pre>}
    </div>
  );
}

function PromptTab({ view, turn }: { view: RunView; turn: Turn | undefined }) {
  if (!view.context) return <div className="empty">No context yet.</div>;
  const n = turn?.n ?? 1;
  const messages = messagesForTurn(view, n);
  const total = messages.reduce((sum, m) => sum + m.content.length, 0);
  const window = view.start?.model_settings?.context_window;
  const realTokens = turn?.stats?.prompt_tokens;
  return (
    <>
      <Section title={`what the model saw on turn ${n}`}>
        <div className="small muted">
          The model has no memory: every turn it gets the whole conversation again.
          These {messages.length} messages are exactly what was sent.
        </div>
        {window && <Gauge label="context window (estimated)" value={estimateTokens(total)} max={window}
          suffix=" tok" warnAt={0.75} />}
        <div className="small faint">
          {chars(total)} ≈ {count(estimateTokens(total))} tokens
          {realTokens ? ` · Ollama counted ${count(realTokens)} prompt tokens it had to process` : ""}
        </div>
      </Section>
      <div className="section">
        {messages.map((m, i) => (
          <MessageView key={`${n}-${i}`} message={m} open={i === messages.length - 1 && i > 1} />
        ))}
      </div>
    </>
  );
}

// ---- Diff ----

function DiffTab({ view }: { view: RunView }) {
  if (view.verification) {
    return (
      <Section title="final diff (git, collected by the harness)">
        <UnifiedDiff diff={view.verification.diff} />
      </Section>
    );
  }
  const edits = view.turns.filter((t) =>
    (t.action?.tool === "edit_file" || t.action?.tool === "write_file") && t.result?.status === "ok");
  if (edits.length === 0) return <div className="empty">No file changes yet.</div>;
  return (
    <Section title="edits so far (the final git diff appears after verification)">
      {edits.map((t) => (
        <div key={t.n} className="section">
          <div className="row small"><Pill>turn {t.n}</Pill><span className="mono">{t.action?.args?.path}</span></div>
          <EditDiff before={t.action?.args?.old ?? ""}
            after={t.action?.args?.new ?? t.action?.args?.content ?? ""} />
        </div>
      ))}
    </Section>
  );
}

// ---- Checks ----

function ChecksTab({ view }: { view: RunView }) {
  const checks = allChecks(view);
  if (checks.length === 0) return <div className="empty">No checks have run yet.</div>;
  return (
    <>
      {checks.map((item, i) => (
        <Section key={i} title={item.source === "model" ? `run by the model · turn ${item.turn}`
          : "run by the harness · verification"}>
          <div className="row">
            <span className="mono">{item.check.name}</span>
            <StatusPill status={item.check.status} />
            <span className="faint small grow">exit {item.check.exit_code ?? "–"}
              {item.check.duration ? ` · ${seconds(item.check.duration)}` : ""}
              {item.check.truncated ? " · output shortened" : ""}</span>
          </div>
          {item.check.output && <CodeBlock text={item.check.output} clampLines={12} />}
        </Section>
      ))}
    </>
  );
}

// ---- Run ----

function RunTab({ view }: { view: RunView }) {
  const start = view.start;
  if (!start && !view.launch) return <div className="empty">No run selected.</div>;
  return (
    <>
      <Section title="run">
        <div className="kv small">
          <span>run id</span><span className="mono">{view.runId}</span>
          <span>log file</span><span className="mono">semProject/runs/{view.runId}.jsonl</span>
          <span>events</span><span>{view.events.length} stored</span>
          {start && <>
            <span>task</span><span>{start.task}</span>
            <span>repository</span><span className="mono ellipsis">{start.repo_url ?? "–"}</span>
            <span>commit</span><span className="mono">{start.commit}</span>
            <span>model</span><span className="mono">{start.model ?? "(none: baseline)"}</span>
            <span>workspace</span><span className="mono">{start.workspace}</span>
            {start.sandbox && <><span>sandbox</span><span className="mono">{start.sandbox.image}
              {start.sandbox.problem ? ` (unavailable: ${start.sandbox.problem})` : ""}</span></>}
          </>}
        </div>
      </Section>
      {start?.request && <Section title="task request (word for word)"><CodeBlock text={start.request} /></Section>}
      {start?.writable && (
        <Section title="writable area (everything else is read-only)">
          <div className="row wrap">{start.writable.map((w) => <Pill key={w}>{w}</Pill>)}</div>
        </Section>
      )}
      {start?.agent_checks && (
        <Section title="checks">
          <div className="kv small">
            {Object.entries(start.agent_checks).map(([name, cmd]) => (
              <Fragment key={`a-${name}`}><span>model: {name}</span><span className="mono">{cmd}</span></Fragment>
            ))}
            {Object.entries(start.verification_checks ?? {}).map(([name, cmd]) => (
              <Fragment key={`v-${name}`}><span>harness: {name}</span><span className="mono">{cmd}</span></Fragment>
            ))}
          </div>
        </Section>
      )}
      {start?.limits && (
        <Section title="limits">
          <div className="kv small">
            {Object.entries(start.limits).map(([key, value]) => (
              <Fragment key={key}><span>{key}</span><span>{value}</span></Fragment>
            ))}
          </div>
        </Section>
      )}
      {start?.model_settings && (
        <Section title="model settings">
          <div className="kv small">
            {Object.entries(start.model_settings).map(([key, value]) => (
              <Fragment key={key}><span>{key}</span><span className="mono">{String(value)}</span></Fragment>
            ))}
          </div>
        </Section>
      )}
    </>
  );
}

export function Inspector({ view, turn, tab, onTab }: {
  view: RunView; turn: Turn | undefined; tab: InspectorTab; onTab: (tab: InspectorTab) => void;
}) {
  return (
    <aside className="inspector">
      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.id} className={`tab ${tab === t.id ? "active" : ""}`} onClick={() => onTab(t.id)}>
            {t.label}
          </button>
        ))}
        {RESERVED_TABS.map((t) => (
          <span key={t.label} className="tab reserved" title={STAGE_HINT[t.stage]}>
            {t.label} <StageTag stage={t.stage} />
          </span>
        ))}
      </div>
      <div className="scroll grow">
        <div className="inspector-body">
          {tab === "turn" && <TurnTab view={view} turn={turn} />}
          {tab === "prompt" && <PromptTab view={view} turn={turn} />}
          {tab === "diff" && <DiffTab view={view} />}
          {tab === "checks" && <ChecksTab view={view} />}
          {tab === "run" && <RunTab view={view} />}
        </div>
      </div>
    </aside>
  );
}
