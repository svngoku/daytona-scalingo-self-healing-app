"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Incident, SystemStatus, WorkflowEvent } from "@shared/incident";
import { api, latestEvent, streamEvents, terminalStates } from "./incident";

const TOKEN_KEY = "recovery-control-token";

export function publicationSettled(incident: Incident | null) {
  return incident?.state === "AWAITING_APPROVAL" || incident?.artifacts.publication_status === "dry_run";
}

function humanError(error: unknown) {
  return error instanceof Error && error.message !== "Failed to fetch"
    ? error.message
    : "Can't reach the orchestrator. Check that the API is running and try again.";
}

function newest(incidents: Incident[]) {
  return [...incidents].sort((left, right) => right.updated_at.localeCompare(left.updated_at));
}

function upsert(incidents: Incident[], incident: Incident) {
  const previous = incidents.find(({ id }) => incident.id === id);
  if (previous && (latestEvent(previous)?.id ?? 0) > (latestEvent(incident)?.id ?? 0)) return incidents;
  return newest([...incidents.filter(({ id }) => incident.id !== id), incident]);
}

export function useDashboard() {
  const [token, setToken] = useState("");
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [action, setAction] = useState("");
  const [actionError, setActionError] = useState("");
  const [connection, setConnection] = useState<{ id: string; connected: boolean } | null>(null);
  const refreshRequest = useRef<AbortController | null>(null);
  const incident = incidents.find(({ id }) => id === selectedId) ?? null;
  const shouldStream = Boolean(incident && !terminalStates.has(incident.state) && !publicationSettled(incident));

  const refresh = useCallback(async (apiToken: string) => {
    refreshRequest.current?.abort();
    const controller = new AbortController();
    refreshRequest.current = controller;
    const options = { signal: controller.signal };
    setLoading(true);
    setError("");
    const [health, history] = await Promise.allSettled([
      api<SystemStatus>("/status", apiToken, options),
      api<Incident[]>("/incidents", apiToken, options),
    ]);
    if (controller.signal.aborted) return;
    if (health.status === "fulfilled") setStatus(health.value);
    else setStatus(null);
    if (history.status === "fulfilled") {
      setIncidents((previous) => {
        const prior = previous.filter((item) => history.value.some((entry) => item.id === entry.id));
        return history.value.reduce(upsert, prior);
      });
      setSelectedId((previous) => history.value.some(({ id }) => id === previous)
        ? previous : newest(history.value)[0]?.id ?? null);
    }
    if (health.status === "rejected" || history.status === "rejected") {
      setError(humanError(health.status === "rejected" ? health.reason : history.status === "rejected" ? history.reason : null));
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    const saved = window.sessionStorage.getItem(TOKEN_KEY) ?? "";
    setToken(saved);
    void refresh(saved);
    return () => refreshRequest.current?.abort();
  }, [refresh]);

  useEffect(() => {
    if (!selectedId) return;
    const id = selectedId;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cursor = 0;
    let pending: Promise<void> | null = null;
    let refreshAgain = false;
    let finished = false;

    function sync() {
      if (pending) {
        refreshAgain = true;
        return pending;
      }
      pending = api<Incident>(`/incidents/${encodeURIComponent(id)}`, token, { signal: controller.signal })
        .then((result) => {
          if (controller.signal.aborted) return;
          setIncidents((previous) => upsert(previous, result));
          cursor = Math.max(cursor, latestEvent(result)?.id ?? 0);
          finished = terminalStates.has(result.state) || publicationSettled(result);
        })
        .catch(() => {})
        .finally(() => {
          pending = null;
          if (refreshAgain && !controller.signal.aborted && !finished) {
            refreshAgain = false;
            void sync();
          }
        });
      return pending;
    }

    function accept(event: WorkflowEvent) {
      if (event.id <= cursor) return;
      cursor = event.id;
      setIncidents((previous) => previous.map((item) => {
        if (item.id !== id || (latestEvent(item)?.id ?? 0) >= event.id) return item;
        // Keep the state open until the durable snapshot includes the final evidence.
        const closing = terminalStates.has(event.state) || event.state === "AWAITING_APPROVAL";
        return {
          ...item, state: closing ? item.state : event.state,
          updated_at: event.timestamp, events: [...item.events, event], error: event.error ?? item.error,
        };
      }));
      void sync();
    }

    async function connect() {
      if (controller.signal.aborted || finished) return;
      try {
        await streamEvents(id, token, cursor, controller.signal, accept, () => {
          setConnection({ id, connected: true });
        });
      } catch {
        // Durable incident details keep the UI useful while the stream reconnects.
      }
      if (controller.signal.aborted) return;
      setConnection({ id, connected: false });
      await sync();
      if (!controller.signal.aborted && !finished) timer = setTimeout(() => void connect(), 2500);
    }

    void sync().then(() => { if (shouldStream) void connect(); });
    const polling = shouldStream ? setInterval(() => void sync(), 9000) : undefined;
    return () => {
      controller.abort();
      clearTimeout(timer);
      clearInterval(polling);
    };
  }, [selectedId, shouldStream, token]);

  useEffect(() => {
    if (!selectedId || shouldStream) return;
    const controller = new AbortController();
    void api<SystemStatus>("/status", token, { signal: controller.signal }).then(setStatus).catch(() => {});
    return () => controller.abort();
  }, [selectedId, shouldStream, token]);

  function updateToken(input: string) {
    const trimmed = input.trim();
    if (trimmed) window.sessionStorage.setItem(TOKEN_KEY, trimmed);
    else window.sessionStorage.removeItem(TOKEN_KEY);
    setToken(trimmed);
    void refresh(trimmed);
  }

  function select(id: string) {
    setSelectedId(id);
    setActionError("");
  }

  async function mutate(kind: "trigger" | "retry" | "cancel" | "authorize") {
    const path = kind === "trigger" ? "/incidents" : `/incidents/${encodeURIComponent(selectedId ?? "")}/${kind}`;
    setAction(kind);
    setActionError("");
    try {
      const result = await api<Incident>(path, token, {
        method: "POST",
        body: JSON.stringify(kind === "authorize" ? { authorized: true } : {}),
      });
      setIncidents((previous) => upsert(previous, result));
      setSelectedId(result.id);
      return true;
    } catch (cause) {
      setActionError(humanError(cause));
      return false;
    } finally {
      setAction("");
    }
  }

  return {
    token, status, incidents, incident, loading, error, action, actionError, select, updateToken, mutate,
    refresh: () => void refresh(token), live: shouldStream && selectedId === connection?.id && connection.connected,
  };
}

export type DashboardData = ReturnType<typeof useDashboard>;
