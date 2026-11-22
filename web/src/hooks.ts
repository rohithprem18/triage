import { useEffect, useState } from "react";

export const ROUTES = ["incidents", "system", "runbooks", "benchmark"] as const;
export type Route = (typeof ROUTES)[number];

function parse(): { route: Route; incident: string | null } {
  const [path, query] = window.location.hash.replace(/^#\/?/, "").split("?");
  const route = (ROUTES as readonly string[]).includes(path) ? (path as Route) : "incidents";
  return { route, incident: new URLSearchParams(query ?? "").get("i") };
}

/** Hash routing with ?i=<incident code>, so the selected incident survives navigation. */
export function useRoute() {
  const [state, setState] = useState(parse);
  useEffect(() => {
    const on = () => setState(parse());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const go = (route: Route, incident?: string | null) => {
    window.location.hash = `/${route}${incident ? `?i=${incident}` : ""}`;
  };
  return { ...state, go };
}

export function useLoad<T>(load: (signal: AbortSignal) => Promise<T>, deps: unknown[]): [T | null, boolean] {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    const c = new AbortController();
    setError(false);
    load(c.signal)
      .then(setData)
      .catch((e) => {
        if (!(e instanceof DOMException && e.name === "AbortError")) setError(true);
      });
    return () => c.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return [data, error];
}

export const FAULT_LABEL: Record<string, string> = {
  bad_deploy: "Bad deploy",
  db_connection_exhaustion: "DB connection exhaustion",
  memory_leak: "Memory leak",
  dependency_latency: "Slow external dependency",
  certificate_expired: "Expired certificate",
  bad_config: "Bad configuration",
  disk_full: "Disk full",
};
