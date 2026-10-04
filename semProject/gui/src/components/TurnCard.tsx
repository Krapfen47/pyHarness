// One turn of the agent loop as a card:
//   the model's reply (streaming while it is written)
//   -> the validation gates it passed (json, shape, tool, args, policy)
//   -> what the tool did, or why the reply was rejected

import { memo } from "react";
import { count, seconds, stringify } from "../format";
import { gates, runCheckOutput, type Gate, type Turn } from "../state";
import { CodeBlock, Pill, StageTag, StatusPill } from "./common";
import { EditDiff } from "./DiffView";

const GATE_LABEL: Record<Gate, string> = {
  json: "json", shape: "shape", tool: "tool", args: "args", policy: "path guard",
};
const GATE_HINT: Record<Gate, string> = {
  json: "Is the reply valid JSON?",
  shape: 'Is it {"tool": ..., "args": ...} or {"final": ...}?',
  tool: "Is it a tool that exists?",
  args: "Exactly the right arguments, all strings, not too long?",
  policy: "Did the policy allow it (PathGuard / configured checks)?",
};

export function Gates({ turn }: { turn: Turn }) {
  const state = gates(turn);
  const order: Gate[] = turn.final !== undefined ? ["json", "shape"]
    : ["json", "shape", "tool", "args", "policy"];
  return (
    <div className="gates" title="The harness checks every reply before anything runs">
      {order.map((gate, i) => (
        <span key={gate} className="row" style={{ gap: 4 }}>
          {i > 0 && <span className="gate-arrow">›</span>}
          <span title={GATE_HINT[gate]}
            className={`gate ${state[gate] === true ? "pass" : state[gate] === false ? "fail" : ""}`}>
            {state[gate] === true ? "✓ " : state[gate] === false ? "✕ " : ""}{GATE_LABEL[gate]}
          </span>
        </span>
      ))}
    </div>
  );
}

function argSummary(turn: Turn): string {
  const args = turn.action?.args ?? {};
  if (args.path) return args.path;
  if (args.query) return `"${args.query}"`;
  if (args.name) return args.name;
  return "";
}

function OutcomeDetail({ turn }: { turn: Turn }) {
  const { action, result } = turn;
  if (!action || !result) return null;
  const output = result.output as Record<string, unknown> | string;

  if (result.status !== "ok") {
    return <div className={result.status === "denied" ? "" : "muted"}>
      <CodeBlock text={stringify(output)} clampLines={6} />
    </div>;
  }
  if (action.tool === "edit_file" && action.args) {
    return (
      <div className="section">
        <EditDiff before={action.args.old ?? ""} after={action.args.new ?? ""} />
        {typeof output === "string" && output.includes("\n") && (
          <CodeBlock text={output} clampLines={6} />
        )}
      </div>
    );
  }
  const check = runCheckOutput(turn);
  if (check) {
    const tail = check.output.trim().split("\n").slice(-8).join("\n");
    return <CodeBlock text={tail} clampLines={8} />;
  }
  return null;
}

function outcomeSummary(turn: Turn): string {
  const output = turn.result?.output as Record<string, unknown> | string | undefined;
  if (turn.result?.status !== "ok") return ""; // the error text is shown in full below
  if (!output || typeof output === "string") return typeof output === "string" ? output : "";
  if (Array.isArray(output.files)) return `${output.files.length} files${output.truncated ? " (cut)" : ""}`;
  if (Array.isArray(output.matches)) return `${output.matches.length} matches`;
  if (typeof output.content === "string") {
    return `${count(output.content.length)} chars${output.truncated ? ", shortened" : ""}`;
  }
  return "";
}

// memo: re-render a card only when ITS props change. While the model streams,
// only the newest turn changes, so the older cards are not redrawn for every token.
export const TurnCard = memo(function TurnCard({ turn, selected, live, onSelect }: {
  turn: Turn; selected: boolean; live: boolean; onSelect: (n: number) => void;
}) {
  const writing = turn.reply === undefined && !turn.aborted;
  const check = runCheckOutput(turn);
  const thinking = turn.thinking ?? turn.streamedThinking;
  const cutOff = turn.aborted?.reason.startsWith("stopped") || turn.aborted?.reason.startsWith("interrupted");

  return (
    <div className={`card clickable ${selected ? "selected" : ""} ${live && writing ? "live" : ""}
      ${turn.invalid || (turn.aborted && !cutOff) ? "bad" : ""}`} onClick={() => onSelect(turn.n)}>
      <div className="card-head">
        <h3>Turn {turn.n}</h3>
        {writing && live && <Pill tone="accent"><span className="spinner" /> model is writing</Pill>}
        {writing && !live && <Pill>no reply</Pill>}
        {turn.aborted && <Pill tone={cutOff ? "warn" : "bad"}>{cutOff ? "cut off by Stop" : "model error"}</Pill>}
        {turn.invalid && <Pill tone="bad">invalid reply · retry</Pill>}
        {turn.final !== undefined && <Pill tone="info">final answer</Pill>}
        {turn.action && <span className="tool-name">{turn.action.tool}</span>}
        {turn.legacy && <span className="faint small"
          title="This log is from before the GUI existed; it didn't store the raw replies.">
          older log: reply rebuilt from the action</span>}
        <span className="grow" />
        <span className="faint small">
          {turn.duration !== undefined && `model ${seconds(turn.duration)}`}
          {turn.stats && ` · ${turn.stats.output_tokens} tok`}
          {turn.stats?.tokens_per_s && ` · ${turn.stats.tokens_per_s} tok/s`}
        </span>
      </div>

      <div className="card-body">
        {thinking && (
          <div className="thinking small">
            <span className="label">thinking</span>
            <pre>{thinking.length > 600 ? `${thinking.slice(0, 600)}…` : thinking}</pre>
          </div>
        )}

        {writing ? (
          <CodeBlock className="reply" text={turn.streamed || " "} cursor={live} clampLines={8} />
        ) : turn.aborted ? (
          <>
            {turn.aborted.partial && <CodeBlock className="reply" text={`${turn.aborted.partial} …`} clampLines={4} />}
            <div style={{ color: cutOff ? "var(--warn)" : "var(--bad)" }}>{turn.aborted.reason}</div>
          </>
        ) : (
          <CodeBlock className="reply" text={turn.reply ?? ""} clampLines={4} />
        )}

        {!writing && !turn.aborted && <Gates turn={turn} />}

        {turn.invalid && <div style={{ color: "var(--bad)" }}>{turn.invalid.error}</div>}

        {turn.final !== undefined && (
          <div><span className="label">claim (not verified yet)</span><div>{turn.final}</div></div>
        )}

        {turn.action && (
          <div className="action-line">
            <span className="tool-name">{turn.action.tool}</span>
            <span className="mono ellipsis" style={{ maxWidth: 420 }}>{argSummary(turn)}</span>
            {turn.result ? <StatusPill status={turn.result.status} /> : live && (
              <Pill tone="accent"><span className="spinner" /> running</Pill>)}
            {check && <StatusPill status={check.status}
              label={`${check.status} · exit ${check.exit_code ?? "–"}`} />}
            {turn.repeat && <Pill tone="warn" title="Same request as before, nothing changed since. The model was told.">repeat</Pill>}
            <span className="faint small ellipsis grow">{!check && outcomeSummary(turn)}</span>
            <span className="reserved row" style={{ gap: 4 }} title="Stage 3 adds approve / deny for actions">
              <span className="faint small">auto-approved</span><StageTag stage={3} />
            </span>
          </div>
        )}
        <OutcomeDetail turn={turn} />
      </div>
    </div>
  );
});
