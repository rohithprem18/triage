import { useEffect, useState } from "react";
import { api } from "../api";
import { Sparkline, Topology } from "../components/Topology";
import { useLoad } from "../hooks";

const METRIC_LABEL: Record<string, [string, string]> = {
  error_rate: ["Error rate", "%"],
  p95_ms: ["p95 latency", "ms"],
  rps: ["Throughput", "req/s"],
  memory: ["Memory", "%"],
  restarts: ["Restarts", "/min"],
  connections: ["DB connections", "of 100"],
};

export function System({ incident, onIncident }: { incident: string | null; onIncident: (code: string) => void }) {
  const [cards] = useLoad((s) => api.incidents(s), []);
  const code = incident ?? cards?.[0]?.code ?? null;
  const [detail, error] = useLoad((s) => (code ? api.incident(code, s) : Promise.resolve(null)), [code]);
  const [service, setService] = useState<string | null>(null);
  useEffect(() => setService(detail?.alert.service ?? null), [detail?.code]);
  const metrics = service && detail ? detail.metrics[service] : null;

  return (
    <div className="view">
      <header className="view-head">
        <span className="eyebrow">System</span>
        <div className="row">
          <h1 className="display">{detail ? `${detail.code}: ${detail.title}` : "System"}</h1>
          <div className="pill-group">
            {(cards ?? []).map((c) => (
              <button key={c.code} className={`pill sm ${code === c.code ? "on" : ""}`} onClick={() => onIncident(c.code)}>{c.code}</button>
            ))}
          </div>
        </div>
        <p className="lead">The same data the agent sees: a simulated e-commerce system with the incident injected. Click a service to see its last hour.</p>
      </header>
      {error && <div className="error-banner">Couldn't load this incident.</div>}

      {detail && (
        <section className="sys">
          <div className="stack">
            <div className="card">
              <div className="card-head">
                <span className="card-title">Service map</span>
                <div className="legend">
                  <span><i style={{ background: "var(--good)" }} />Healthy</span>
                  <span><i style={{ background: "var(--warn)" }} />Degraded</span>
                  <span><i style={{ background: "var(--bad)" }} />Unhealthy</span>
                </div>
              </div>
              <Topology services={detail.services} topology={detail.topology} selected={service} onSelect={setService} />
            </div>
            <div className="table-wrap" style={{ maxHeight: 260 }}>
              <table>
                <thead><tr><th>Change</th><th>Service</th><th className="num">When</th></tr></thead>
                <tbody>
                  {detail.changes.map((c, i) => (
                    <tr key={i} style={{ cursor: "default" }}>
                      <td><span className="tag" style={{ marginRight: 8 }}>{c.kind}</span>{c.summary}</td>
                      <td className="muted">{c.service}</td>
                      <td className="num muted">{c.minutes_ago} min ago</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <span className="card-title">{service ?? "Select a service"}</span>
              <span className="mono-label">last {detail.window_minutes} minutes</span>
            </div>
            {metrics && Object.entries(metrics).map(([m, values]) => {
              const [label, unit] = METRIC_LABEL[m] ?? [m, ""];
              if (!values.some((v) => v > 0)) return null;
              const now = values.slice(-5).reduce((a, b) => a + b, 0) / 5;
              const base = values.slice(0, 20).reduce((a, b) => a + b, 0) / 20;
              const moved = base ? Math.abs(now - base) / base > 0.5 : now > 0;
              return (
                <div key={m} className="spark-row">
                  <span className="muted">{label}</span>
                  <Sparkline values={values} color={moved ? "var(--sunset)" : "var(--mute)"} />
                  <span className="v">{now >= 100 ? Math.round(now).toLocaleString() : now.toFixed(1)} <span className="muted">{unit}</span></span>
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
