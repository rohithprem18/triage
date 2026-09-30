import { api } from "../api";
import { fmtPct } from "../format";
import { FAULT_LABEL, useLoad } from "../hooks";

export function Benchmark() {
  const [b, error] = useLoad((s) => api.benchmark(s), []);
  return (
    <div className="view">
      <header className="view-head">
        <span className="eyebrow">Benchmark</span>
        <div className="row">
          <h1 className="display">Does investigating beat guessing?</h1>
          <span className="caption">{b ? `${b.n} incidents · 6 fault types × 5 seeds` : ""}</span>
        </div>
        <p className="lead">
          Each incident has one injected fault. A diagnosis counts only when both the root-cause service and the fault type are right.
          The baseline is the same model given only the alert and the dependency graph, with no tools.
        </p>
      </header>
      {error && <div className="error-banner">Benchmark results are not available yet.</div>}
      {b && (
        <>
          <section className="kpis">
            <div className="card kpi"><span className="mono-label">Agent accuracy</span><span className="kpi-value">{fmtPct(b.agent.accuracy, 0)}</span><span className="caption">service and fault type right</span></div>
            <div className="card kpi"><span className="mono-label">Alert-only baseline</span><span className="kpi-value">{fmtPct(b.baseline_alert_only.accuracy, 0)}</span><span className="caption">same model, no tools</span></div>
            <div className="card kpi"><span className="mono-label">Right service</span><span className="kpi-value">{fmtPct(b.agent.service_accuracy, 0)}</span><span className="caption">vs {fmtPct(b.baseline_alert_only.service_accuracy, 0)} without tools</span></div>
            <div className="card kpi"><span className="mono-label">Median investigation</span><span className="kpi-value">{b.median_steps}<span className="unit">tool calls</span></span><span className="caption">{b.median_seconds}s · {b.median_tokens.toLocaleString()} tokens</span></div>
          </section>
          <section className="bench">
            <div className="card">
              <div className="card-head">
                <span className="card-title">By fault type</span>
                <div className="legend">
                  <span><i style={{ background: "var(--series-upstream)" }} />Alert only</span>
                  <span><i style={{ background: "var(--series-cache)" }} />Agent with tools</span>
                </div>
              </div>
              {Object.entries(b.by_fault).map(([f, r]) => (
                <div key={f} className="diff-row">
                  <div><div>{FAULT_LABEL[f] ?? f}</div><div className="caption">{r.n} incidents</div></div>
                  <div className="tracks">
                    <div className="t"><i style={{ width: `${r.baseline * 100}%`, background: "var(--series-upstream)" }} /></div>
                    <div className="t"><i style={{ width: `${r.agent * 100}%`, background: "var(--series-cache)" }} /></div>
                  </div>
                  <div className="pct">{fmtPct(r.agent, 0)}</div>
                </div>
              ))}
            </div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Tool</th><th className="num">Calls</th></tr></thead>
                <tbody>
                  {Object.entries(b.tool_usage).map(([t, n]) => (
                    <tr key={t} style={{ cursor: "default" }}><td className="tool-name">{t}</td><td className="num">{n}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
