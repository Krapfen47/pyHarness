// Talking to the Python server (harness/gui/server.py): plain fetch() calls
// for the REST endpoints, and one EventSource for the live event stream.

import type {
  HarnessEvent, Health, RunSummary, StartRunBody, TaskInfo, UnknownEvent,
} from "./events";

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    // FastAPI puts its error message in {"detail": ...}.
    const detail = await response.json().then((d) => d.detail, () => response.statusText);
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("GET", "/api/health"),
  tasks: () => request<TaskInfo[]>("GET", "/api/tasks"),
  runs: () => request<RunSummary[]>("GET", "/api/runs"),
  run: (id: string) =>
    request<{ run_id: string; events: (HarnessEvent | UnknownEvent)[] }>("GET", `/api/runs/${id}`),
  start: (body: StartRunBody) => request<{ run_id: string }>("POST", "/api/runs", body),
  stop: (id: string) => request<{ stopping: string }>("POST", `/api/runs/${id}/stop`),
};

export type LiveStatus = "connecting" | "open" | "closed";

/**
 * Subscribe to the live run. The browser's EventSource keeps the connection
 * open and reconnects by itself; after a reconnect the server re-sends the
 * current run, and the reducer skips events it already has (by `seq`).
 * Returns a function that closes the connection.
 */
export function openLive(
  onEvent: (event: HarnessEvent | UnknownEvent) => void,
  onStatus: (status: LiveStatus) => void,
): () => void {
  const source = new EventSource("/api/live");
  onStatus("connecting");
  source.onopen = () => onStatus("open");
  source.onerror = () => onStatus(source.readyState === EventSource.CLOSED ? "closed" : "connecting");
  source.onmessage = (message) => onEvent(JSON.parse(message.data));
  return () => source.close();
}
