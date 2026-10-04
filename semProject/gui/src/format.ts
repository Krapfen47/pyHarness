// Small formatting helpers used all over the UI.

export function seconds(value: number | undefined | null): string {
  if (value === undefined || value === null) return "–";
  if (value < 1) return `${Math.round(value * 1000)} ms`;
  if (value < 60) return `${value.toFixed(1)} s`;
  const minutes = Math.floor(value / 60);
  return `${minutes}m ${Math.round(value % 60)}s`;
}

export function count(value: number): string {
  return value >= 10_000 ? `${(value / 1000).toFixed(1)}k` : value.toLocaleString("en-US");
}

export function chars(value: number): string {
  return value >= 1000 ? `${(value / 1000).toFixed(1)}k chars` : `${value} chars`;
}

export function clock(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** "20261003-191123-run" -> "Oct 3, 19:11" */
export function runLabel(runId: string): string {
  const match = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/.exec(runId);
  if (!match) return runId;
  const [, y, mo, d, h, mi] = match;
  const date = new Date(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi));
  return `${date.toLocaleDateString([], { month: "short", day: "numeric" })}, ${h}:${mi}`;
}

/** Pretty-print text that may be JSON; anything else comes back unchanged. */
export function prettyJson(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

/** "script:semProject/tasks/x/reference_script.json" -> "scripted (reference_script.json)" */
export function modelLabel(model: string | null | undefined): string {
  if (!model) return "none";
  if (model.startsWith("script:")) return `scripted (${model.split(/[\\/]/).pop()})`;
  return model;
}

export function stringify(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

export const STATUS_TONE: Record<string, "ok" | "bad" | "warn" | "info" | ""> = {
  ok: "ok", passed: "ok", verified: "ok",
  denied: "bad", failed: "bad", not_verified: "bad", error: "bad", timed_out: "bad",
  stopped: "warn", unavailable: "warn", cancelled: "warn", incomplete: "warn",
};

export const STATUS_TEXT: Record<string, string> = {
  verified: "verified", not_verified: "not verified", cancelled: "stopped", error: "error",
  incomplete: "incomplete",
};
