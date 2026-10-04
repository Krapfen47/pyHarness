// From a list of events to "what the screen shows": one pure function.
//
//   reduce(state, event) -> new state
//
// The same function draws a LIVE run (events arrive one by one over SSE) and
// REPLAYS a past run (we fold the log's events in a loop; the replay slider
// simply stops the loop at event k). Because the reducer never mutates the
// old state and has no side effects, "the screen after event k" is always
// the same, which is what makes the replay slider trustworthy.
//
// React's useReducer and Redux use exactly this pattern.

import type {
  Action, Budget, CheckResult, FinishedEvent, HarnessEvent, LaunchEvent, Limits, Message,
  ReplyStats, StartEvent, StopEvent, ToolResult, UnknownEvent, VerificationEvent,
} from "./events";

export type Phase = "idle" | "setup" | "context" | "loop" | "verification" | "done";

// The boxes of the architecture diagram (FlowDiagram.tsx).
export type FlowNode =
  | "ui" | "controller" | "llm" | "context" | "tools" | "sandbox" | "verification";

export type Gate = "json" | "shape" | "tool" | "args" | "policy";

export interface Turn {
  n: number;
  startedAt: string;
  promptMessages: number; // how many messages the model was sent
  promptChars: number;
  streamed: string; // the reply so far, while it is being written (live only)
  streamedThinking: string;
  reply?: string; // the complete raw reply
  thinking?: string | null;
  duration?: number; // seconds the model needed
  stats?: ReplyStats | null;
  invalid?: { error: string; gate: Gate };
  action?: Action; // the validated request (absent for invalid / final replies)
  final?: string; // the model's final claim, if this turn ended the loop
  result?: ToolResult;
  repeat?: boolean;
  observation?: string; // the exact message sent back to the model
  legacy?: boolean; // from an old log without model events: the reply wasn't recorded
  aborted?: { reason: string; partial: string }; // the reply was cut off (Stop, model error)
}

export interface SetupStep {
  step: string;
  status: string;
  detail?: string;
}

export interface CheckState {
  name: string;
  running: boolean;
  result?: CheckResult;
}

export interface RunView {
  runId: string | null;
  events: (HarnessEvent | UnknownEvent)[]; // every stored event, in order (model_token excluded)
  lastSeq: number;
  launch?: LaunchEvent["request"];
  start?: StartEvent;
  setup: SetupStep[];
  context?: Message[];
  turns: Turn[];
  budget: Budget;
  limits?: Limits;
  stop?: StopEvent;
  verifyChecks: CheckState[];
  verification?: VerificationEvent;
  finished?: FinishedEvent;
  error?: string;
  stopRequested: boolean;
  phase: Phase;
  activeNode: FlowNode | null;
  activeEdge: [FlowNode, FlowNode] | null;
  unknown: UnknownEvent[];
  firstTime?: string;
  lastTime?: string;
}

export const ZERO_BUDGET: Budget = { actions: 0, retries: 0, denied: 0, errors: 0, repeats: 0 };

export function emptyRun(runId: string | null = null): RunView {
  return {
    runId, events: [], lastSeq: 0, setup: [], turns: [], budget: ZERO_BUDGET,
    verifyChecks: [], stopRequested: false, phase: "idle", activeNode: null,
    activeEdge: null, unknown: [],
  };
}

// ---- helpers that return an updated copy ----

function updateTurn(state: RunView, n: number, change: (turn: Turn) => Partial<Turn>): RunView {
  // Logs written before the GUI existed have no model_call events, so a turn
  // may first appear with its request. Create it then, instead of losing it.
  const turns = state.turns.some((t) => t.n === n) ? state.turns : [...state.turns, {
    n, startedAt: state.lastTime ?? "", promptMessages: 0, promptChars: 0,
    streamed: "", streamedThinking: "", legacy: true,
  }];
  return {
    ...state,
    turns: turns.map((turn) => (turn.n === n ? { ...turn, ...change(turn) } : turn)),
  };
}

function upsertSetup(steps: SetupStep[], next: SetupStep): SetupStep[] {
  const others = steps.filter((s) => s.step !== next.step);
  const index = steps.findIndex((s) => s.step === next.step);
  if (index === -1) return [...steps, next];
  others.splice(index, 0, next); // keep the original position
  return others;
}

function upsertCheck(checks: CheckState[], next: CheckState): CheckState[] {
  return checks.some((c) => c.name === next.name)
    ? checks.map((c) => (c.name === next.name ? next : c))
    : [...checks, next];
}

const FILE_TOOLS = new Set(["list_files", "read_file", "search_files", "edit_file", "write_file"]);

// ---- the reducer ----

export function reduce(state: RunView, event: HarnessEvent | UnknownEvent): RunView {
  // A new run id means a new run: start from a clean slate.
  if (event.run_id !== state.runId) state = emptyRun(event.run_id);
  // After a reconnect the server re-sends the run's events; skip the ones we have.
  if (event.seq <= state.lastSeq) return state;

  const base: RunView = {
    ...state,
    lastSeq: event.seq,
    events: event.type === "model_token" ? state.events : [...state.events, event],
    firstTime: state.firstTime ?? event.time,
    lastTime: event.time,
  };
  const e = event as HarnessEvent;

  switch (e.type) {
    case "launch":
      return { ...base, launch: e.request, phase: "setup", activeNode: "ui", activeEdge: null };

    case "setup":
      return {
        ...base,
        phase: "setup",
        setup: upsertSetup(base.setup, {
          step: e.step,
          status: e.status,
          detail: e.detail ?? e.path ?? e.image ?? e.model ?? e.patch
            ?? (e.task ? `${e.task} @ ${e.commit?.slice(0, 12)}` : undefined),
        }),
        activeNode: e.step === "sandbox" ? "sandbox" : e.step === "model" ? "llm" : "tools",
        activeEdge: null,
      };

    case "start":
      return { ...base, start: e, limits: e.limits };

    case "context":
      return { ...base, context: e.messages, phase: "context", activeNode: "context",
        activeEdge: ["context", "controller"] };

    case "model_call":
      return {
        ...base,
        phase: "loop",
        activeNode: "llm",
        activeEdge: ["controller", "llm"],
        turns: [...base.turns, {
          n: e.turn, startedAt: e.time, promptMessages: e.messages, promptChars: e.chars,
          streamed: "", streamedThinking: "",
        }],
      };

    case "model_token":
      return updateTurn(base, e.turn, (turn) =>
        e.kind === "thinking"
          ? { streamedThinking: turn.streamedThinking + e.text }
          : { streamed: turn.streamed + e.text });

    case "model_reply":
      return {
        ...updateTurn(base, e.turn, () => ({
          reply: e.reply, thinking: e.thinking, duration: e.duration, stats: e.stats,
        })),
        activeNode: "controller",
        activeEdge: ["llm", "controller"],
      };

    case "model_aborted":
      return {
        ...updateTurn(base, e.turn, () => ({
          aborted: { reason: e.reason, partial: e.partial }, thinking: e.thinking,
          duration: e.duration,
        })),
        activeNode: "controller",
        activeEdge: null,
      };

    case "invalid":
      return {
        ...updateTurn(base, e.turn, (turn) => ({ invalid: { error: e.error, gate: e.gate ?? "shape" },
          reply: turn.reply ?? e.reply })),
        budget: e.budget ?? { ...base.budget, retries: base.budget.retries + 1 },
      };

    case "request":
      return {
        // Old logs: rebuild the reply from the action (it was valid JSON with this content).
        ...updateTurn(base, e.turn, (turn) => ({ action: e.action,
          reply: turn.reply ?? (turn.legacy ? JSON.stringify(e.action) : undefined) })),
        activeNode: e.action.tool === "run_check" ? "sandbox" : "tools",
        activeEdge: ["controller", e.action.tool === "run_check" ? "sandbox" : "tools"],
      };

    case "result": {
      const counted = e.budget ?? {
        ...base.budget,
        actions: base.budget.actions + 1,
        denied: base.budget.denied + (e.result.status === "denied" ? 1 : 0),
        errors: base.budget.errors + (e.result.status === "error" ? 1 : 0),
      };
      const from: FlowNode = FILE_TOOLS.has(e.tool) ? "tools" : "sandbox";
      return {
        ...updateTurn(base, e.turn, () => ({ result: e.result })),
        budget: counted,
        activeNode: "controller",
        activeEdge: [from, "controller"],
      };
    }

    case "repeat": {
      const marked = updateTurn(base, e.turn, () => ({ repeat: true }));
      return { ...marked, budget: { ...marked.budget, repeats: countRepeats(marked) } };
    }

    case "observation":
      return {
        ...updateTurn(base, e.turn, () => ({ observation: e.content })),
        activeNode: "llm",
        activeEdge: ["controller", "llm"],
      };

    case "stop": {
      const withFinal = e.final_message
        ? updateTurn(base, e.turns, (turn) => ({ final: e.final_message ?? undefined,
          reply: turn.reply ?? JSON.stringify({ final: e.final_message }) }))
        : base;
      return {
        ...withFinal,
        stop: e,
        budget: { actions: e.actions, retries: e.retries, denied: e.denied, errors: e.errors,
          repeats: e.repeats },
        activeNode: "controller",
        activeEdge: null,
      };
    }

    case "verify_start":
      return {
        ...base,
        phase: "verification",
        verifyChecks: e.checks.map((name) => ({ name, running: false })),
        activeNode: "verification",
        activeEdge: ["controller", "verification"],
      };

    case "check_start":
      return {
        ...base,
        verifyChecks: upsertCheck(base.verifyChecks, { name: e.name, running: true }),
        activeNode: e.name === "scope" ? "verification" : "sandbox",
        activeEdge: e.name === "scope" ? null : ["verification", "sandbox"],
      };

    case "check_end": {
      const { seq: _s, time: _t, run_id: _r, type: _ty, ...result } = e;
      return {
        ...base,
        verifyChecks: upsertCheck(base.verifyChecks, { name: e.name, running: false, result }),
        activeNode: "verification",
        activeEdge: null,
      };
    }

    case "verification":
      return {
        ...base,
        verification: e,
        // Old logs have no check_start / check_end events: take the checks from here.
        verifyChecks: base.verifyChecks.length > 0 ? base.verifyChecks
          : e.checks.map((result) => ({ name: result.name, running: false, result })),
        // The verdict is known now. (A live run's "finished" follows right
        // away and replaces this; old logs end here.)
        finished: base.finished ?? { ...e, type: "finished",
          status: e.passed ? "verified" : "not_verified", passed: e.passed },
        phase: "done",
        activeNode: "verification",
        activeEdge: ["verification", "ui"],
      };

    case "finished":
      return { ...base, finished: e, phase: "done", activeNode: "ui", activeEdge: null };

    case "error":
      return { ...base, error: e.message };

    case "stop_requested":
      return { ...base, stopRequested: true };

    default:
      return { ...base, unknown: [...base.unknown, event as UnknownEvent] };
  }
}

function countRepeats(state: RunView): number {
  return state.turns.filter((t) => t.repeat).length;
}

/** Fold a whole list of events, e.g. a log file (optionally only the first `upTo`). */
export function replay(events: (HarnessEvent | UnknownEvent)[], upTo = events.length): RunView {
  let state = emptyRun(events[0]?.run_id ?? null);
  for (let i = 0; i < upTo; i++) state = reduce(state, events[i]);
  return state;
}

// ---- derived values the views need ----

/** The exact list of messages the model was sent on turn n (before it replied). */
export function messagesForTurn(view: RunView, n: number): Message[] {
  const messages: Message[] = [...(view.context ?? [])];
  for (const turn of view.turns) {
    if (turn.n >= n) break;
    if (turn.reply !== undefined) messages.push({ role: "assistant", content: turn.reply });
    if (turn.observation !== undefined) messages.push({ role: "user", content: turn.observation });
  }
  return messages;
}

/** Which validation steps a turn passed: true = passed, false = failed, undefined = not reached. */
export function gates(turn: Turn): Record<Gate, boolean | undefined> {
  const order: Gate[] = ["json", "shape", "tool", "args", "policy"];
  const result: Record<Gate, boolean | undefined> = {
    json: undefined, shape: undefined, tool: undefined, args: undefined, policy: undefined,
  };
  if (turn.reply === undefined) return result;
  if (turn.invalid) {
    for (const gate of order) {
      if (gate === turn.invalid.gate) { result[gate] = false; break; }
      result[gate] = true;
    }
    return result;
  }
  result.json = true;
  result.shape = true;
  if (turn.final !== undefined) return result; // a final answer has no tool to check
  if (turn.action) { result.tool = true; result.args = true; }
  if (turn.result) result.policy = turn.result.status !== "denied";
  return result;
}

/** A rough token count: about 4 characters per token for English text and code. */
export function estimateTokens(chars: number): number {
  return Math.round(chars / 4);
}

export function isRunning(view: RunView): boolean {
  return view.runId !== null && view.phase !== "idle" && !view.finished;
}

export function elapsedSeconds(view: RunView, now = Date.now()): number {
  if (!view.firstTime) return 0;
  const end = view.finished && view.lastTime ? Date.parse(view.lastTime) : now;
  return Math.max(0, (end - Date.parse(view.firstTime)) / 1000);
}

export function totalOutputTokens(view: RunView): number {
  return view.turns.reduce((sum, t) => sum + (t.stats?.output_tokens ?? 0), 0);
}

/** Every check that ran during the run: the model's run_check calls, then verification. */
export interface CheckRun {
  source: "model" | "harness"; // who ran it: the model via run_check, or verification
  turn?: number;
  check: CheckResult;
}

// What the run_check tool returns to the model (see Toolbox.run_check).
interface RunCheckOutput {
  check: string;
  status: CheckResult["status"];
  exit_code: number | null;
  output: string;
  truncated: boolean;
}

export function runCheckOutput(turn: Turn): RunCheckOutput | null {
  const output = turn.result?.output;
  if (turn.action?.tool !== "run_check" || typeof output !== "object" || output === null) return null;
  return "check" in output ? (output as RunCheckOutput) : null;
}

export function allChecks(view: RunView): CheckRun[] {
  const list: CheckRun[] = [];
  for (const turn of view.turns) {
    const output = runCheckOutput(turn);
    if (output) {
      list.push({ source: "model", turn: turn.n, check: {
        name: output.check, status: output.status, exit_code: output.exit_code,
        output: output.output, truncated: output.truncated, duration: 0,
      } });
    }
  }
  for (const state of view.verifyChecks) {
    if (state.result) list.push({ source: "harness", check: state.result });
  }
  return list;
}
