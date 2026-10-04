// The harness's events, as TypeScript types.
//
// These mirror the Python side exactly: every event the run emits (see the
// docstrings of controller.py, runner.py and verification.py) arrives here as
// one JSON object. `type` tells them apart, so TypeScript can narrow a
// `HarnessEvent` to the right shape inside `switch (event.type)`. This is a
// "discriminated union", the TS version of a sealed class hierarchy in Java/C#.

export interface Meta {
  seq: number; // 1, 2, 3, ... per run
  time: string; // ISO timestamp
  run_id: string; // also the log file's name, e.g. "20261003-191123-run"
}

export interface Message {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface Budget {
  actions: number;
  retries: number;
  denied: number;
  errors: number;
  repeats: number;
}

export interface Limits {
  max_actions: number;
  max_retries: number;
  max_denied: number;
  max_output_chars: number;
  max_observation_chars: number;
  [key: string]: number;
}

export interface ModelSettings {
  model: string;
  endpoint: string;
  timeout: number;
  context_window: number;
  temperature: number;
  max_reply_tokens: number;
  think: boolean | null;
}

export interface ReplyStats {
  prompt_tokens: number;
  output_tokens: number;
  load_s: number;
  prompt_s: number;
  output_s: number;
  total_s: number;
  tokens_per_s: number | null;
  done_reason: string | null;
}

export interface Action {
  tool: string;
  args?: Record<string, string>;
}

export interface ToolResult {
  status: "ok" | "denied" | "error";
  output: unknown; // a string, or a tool-specific object (see tools/repo.py)
}

export interface CheckResult {
  name: string;
  status: "passed" | "failed" | "timed_out" | "stopped" | "unavailable";
  exit_code: number | null;
  output: string;
  truncated: boolean;
  duration: number;
}

export interface RunRequestInfo {
  task: string;
  mode: "run" | "baseline";
  model: string | null;
  script: string | null;
  pace: number;
  patch: string | null;
  max_actions: number;
}

// ---- one interface per event type ----

export interface LaunchEvent extends Meta { type: "launch"; request: RunRequestInfo }
export interface SetupEvent extends Meta {
  type: "setup";
  step: "task" | "workspace" | "sandbox" | "patch" | "model";
  status: "ok" | "building" | "unavailable";
  task?: string;
  commit?: string;
  path?: string;
  image?: string;
  detail?: string;
  patch?: string;
  model?: string;
}
export interface StartEvent extends Meta {
  type: "start";
  mode?: "run" | "baseline";
  task: string;
  commit: string;
  repo_url?: string;
  request?: string;
  writable?: string[];
  agent_checks?: Record<string, string>;
  verification_checks?: Record<string, string>;
  model: string | null;
  model_settings?: ModelSettings | null;
  workspace: string;
  sandbox?: { image: string; problem: string | null };
  limits: Limits;
}
export interface ContextEvent extends Meta { type: "context"; messages: Message[] }
export interface ModelCallEvent extends Meta {
  type: "model_call"; turn: number; messages: number; chars: number;
}
export interface ModelTokenEvent extends Meta {
  type: "model_token"; turn: number; kind: "content" | "thinking"; text: string;
}
export interface ModelReplyEvent extends Meta {
  type: "model_reply";
  turn: number;
  reply: string;
  thinking: string | null;
  duration: number;
  stats: ReplyStats | null;
}
export interface ModelAbortedEvent extends Meta {
  type: "model_aborted";
  turn: number;
  reason: string;
  partial: string; // what the model had written before it was cut off
  thinking: string | null;
  duration: number;
}
export interface InvalidEvent extends Meta {
  type: "invalid";
  turn: number;
  error: string;
  gate?: "json" | "shape" | "tool" | "args";
  reply: string;
  budget?: Budget;
}
export interface RequestEvent extends Meta { type: "request"; turn: number; action: Action }
export interface ResultEvent extends Meta {
  type: "result"; turn: number; tool: string; result: ToolResult; budget?: Budget;
}
export interface RepeatEvent extends Meta { type: "repeat"; turn: number; tool: string }
export interface ObservationEvent extends Meta { type: "observation"; turn: number; content: string }
export interface StopEvent extends Meta, Budget {
  type: "stop";
  stop_reason: string;
  reason: string;
  final_message: string | null;
  turns: number;
}
export interface VerifyStartEvent extends Meta { type: "verify_start"; checks: string[] }
export interface CheckStartEvent extends Meta { type: "check_start"; name: string }
export interface CheckEndEvent extends Meta, CheckResult { type: "check_end" }
export interface VerificationEvent extends Meta {
  type: "verification";
  passed: boolean;
  checks: CheckResult[];
  changed_files: string[];
  diff: string;
}
export interface FinishedEvent extends Meta {
  type: "finished";
  status: "verified" | "not_verified" | "cancelled" | "error";
  passed: boolean;
  stop_reason?: string | null;
}
export interface ErrorEvent extends Meta { type: "error"; message: string }
export interface StopRequestedEvent extends Meta { type: "stop_requested" }

export type HarnessEvent =
  | LaunchEvent | SetupEvent | StartEvent | ContextEvent
  | ModelCallEvent | ModelTokenEvent | ModelReplyEvent | ModelAbortedEvent | InvalidEvent
  | RequestEvent | ResultEvent | RepeatEvent | ObservationEvent | StopEvent
  | VerifyStartEvent | CheckStartEvent | CheckEndEvent | VerificationEvent
  | FinishedEvent | ErrorEvent | StopRequestedEvent;

// An event type this GUI doesn't know yet (e.g. one added in Stage 2). It is
// still shown, as a plain card, instead of silently disappearing.
export interface UnknownEvent extends Meta { type: string; [key: string]: unknown }

// ---- REST API shapes (see harness/gui/server.py) ----

export interface Health {
  ollama: { ok: boolean; models: string[]; default?: string; detail?: string };
  docker: { ok: boolean; detail: string | null };
  active_run: string | null;
}

export interface TaskInfo {
  id: string;
  name?: string;
  repo_url?: string;
  commit?: string;
  request?: string;
  writable?: string[];
  agent_checks?: Record<string, string>;
  verification?: Record<string, string>;
  has_script?: boolean;
  has_patch?: boolean;
  error?: string;
}

export interface RunSummary {
  run_id: string;
  mode: string;
  time: string | null;
  task: string | null;
  model: string | null;
  status: string;
  stop_reason: string | null;
  turns: number | null;
  events: number;
}

export interface StartRunBody {
  task: string;
  mode: "run" | "baseline";
  model?: string | null;
  scripted?: boolean;
  pace?: number;
  reference_patch?: boolean;
  max_actions?: number;
}
