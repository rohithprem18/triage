import type { Benchmark, Health, IncidentCard, IncidentDetail, InvestigationEvent, Runbook } from "./types";

async function getJSON<T>(path: string, signal?: AbortSignal, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { signal, ...init });
  if (!r.ok) throw new Error(`${path} returned ${r.status}`);
  return r.json() as Promise<T>;
}

export const api = {
  incidents: (signal?: AbortSignal) => getJSON<IncidentCard[]>("/api/incidents", signal),
  newIncident: () => getJSON<IncidentCard>("/api/incidents/new", undefined, { method: "POST" }),
  incident: (code: string, signal?: AbortSignal) => getJSON<IncidentDetail>(`/api/incidents/${code}`, signal),
  runbooks: (signal?: AbortSignal) => getJSON<Runbook[]>("/api/runbooks", signal),
  benchmark: (signal?: AbortSignal) => getJSON<Benchmark>("/api/benchmark", signal),
  health: (signal?: AbortSignal) => getJSON<Health>("/api/health", signal),

  async investigate(code: string, onEvent: (e: InvestigationEvent) => void, signal?: AbortSignal) {
    const r = await fetch("/api/investigate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
      signal,
    });
    if (!r.ok || !r.body) {
      let message = `Request failed (${r.status})`;
      try {
        message = (await r.json()).error?.message ?? message;
      } catch {
        /* keep default */
      }
      onEvent({ type: "error", message });
      return;
    }
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let nl: number;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (line) onEvent(JSON.parse(line) as InvestigationEvent);
      }
    }
  },
};
