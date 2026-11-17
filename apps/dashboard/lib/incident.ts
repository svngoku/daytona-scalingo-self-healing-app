import type { Incident, RunState, WorkflowEvent } from "@shared/incident";

export const terminalStates = new Set<RunState>(["COMPLETED", "FAILED", "CANCELLED"]);

export function label(value: string) {
  return value.toLowerCase().replaceAll("_", " ").replace(/^./, (char) => char.toUpperCase());
}

export function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

export function string(value: unknown) {
  return typeof value === "string" ? value : "";
}

export function recordedSandboxProvider(incident: Incident | null) {
  const provider = string(record(incident?.artifacts.sandbox).provider);
  return provider ? label(provider) : null;
}

export function array(value: unknown) {
  return Array.isArray(value) ? value : [];
}

export function safeUrl(value: unknown) {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

export function eventTime(timestamp: string) {
  return new Date(timestamp).toLocaleTimeString(undefined, {
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  });
}

export function latestEvent(incident: Incident | null) {
  return (incident?.events ?? []).at(-1);
}

export function runEvents(incident: Incident | null) {
  const events = incident?.events ?? [];
  return events.slice(events.findLastIndex((event) => event.state === "RETRYING" && event.summary === "Retry requested") + 1);
}

export function stateTone(state: RunState) {
  if (state === "COMPLETED") return "success";
  if (state === "FAILED") return "danger";
  if (state === "AWAITING_APPROVAL") return "warning";
  if (state === "IDLE" || state === "CANCELLED") return "muted";
  return "active";
}

const apiOrigin = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/+$/, "");

async function request(path: string, token: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers);
  if (token) headers.set("X-Orchestrator-Token", token);
  if (options.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`${apiOrigin}/api${path}`, {
    ...options,
    headers,
    cache: "no-store",
  });
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    const detail = string(record(payload).detail);
    throw new Error(detail || (response.status === 401 || response.status === 403
      ? "The API rejected this request. Check your token and permissions in Settings."
      : `Orchestrator request failed (HTTP ${response.status}).`));
  }
  return response;
}

export async function api<T>(path: string, token: string, options: RequestInit = {}) {
  const response = await request(path, token, options);
  return await response.json() as T;
}

export async function streamEvents(
  id: string,
  token: string,
  since: number,
  signal: AbortSignal,
  accept: (event: WorkflowEvent) => void,
  connected: () => void,
) {
  const response = await request(`/incidents/${encodeURIComponent(id)}/events`, token, {
    signal,
    headers: { Accept: "text/event-stream", "Last-Event-ID": String(since) },
  });
  if (!response.body) throw new Error("The orchestrator did not open an event stream.");
  connected();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let data: string[] = [];
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let newline = buffer.indexOf("\n");
      while (newline !== -1) {
        const line = buffer.slice(0, newline).replace(/\r$/, "");
        buffer = buffer.slice(newline + 1);
        if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
        if (!line && data.length) {
          try {
            const event = JSON.parse(data.join("\n")) as WorkflowEvent;
            if (typeof event.id === "number" && event.incident_id === id) accept(event);
          } catch {
            // A malformed frame must not prevent subsequent durable events from loading.
          }
          data = [];
        }
        newline = buffer.indexOf("\n");
      }
    }
  } finally {
    reader.releaseLock();
  }
}
