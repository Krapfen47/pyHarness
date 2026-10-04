// The bottom bar: how much of each limit the run has used, and how big the
// conversation (the model's context) has grown.

import { useEffect, useState } from "react";
import { count, seconds } from "../format";
import { elapsedSeconds, estimateTokens, isRunning, totalOutputTokens, type RunView } from "../state";
import { Gauge } from "./common";

export function BudgetBar({ view }: { view: RunView }) {
  const running = isRunning(view);
  const [, tick] = useState(0);
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => tick((n) => n + 1), 1000); // re-render: elapsed time
    return () => clearInterval(timer);
  }, [running]);

  const limits = view.limits;
  const last = view.turns[view.turns.length - 1];
  const window = view.start?.model_settings?.context_window;
  const contextTokens = last ? estimateTokens(last.promptChars + (last.reply?.length ?? 0)) : 0;
  return (
    <footer className="budget">
      {limits ? <>
        <Gauge label="actions" value={view.budget.actions} max={limits.max_actions} />
        <Gauge label="retries" value={view.budget.retries} max={limits.max_retries} />
        <Gauge label="denied" value={view.budget.denied} max={limits.max_denied} />
      </> : <span className="faint small">limits appear when a run starts</span>}
      {window && <Gauge label="context ≈" value={contextTokens} max={window} warnAt={0.75} />}
      <span className="grow" />
      <span className="stat">errors <b>{view.budget.errors}</b></span>
      <span className="stat">repeats <b>{view.budget.repeats}</b></span>
      <span className="stat">tokens written <b>{count(totalOutputTokens(view))}</b></span>
      <span className="stat">elapsed <b>{seconds(elapsedSeconds(view))}</b></span>
    </footer>
  );
}
