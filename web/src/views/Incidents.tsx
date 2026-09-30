import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { fmtMs } from "../format";
import { FAULT_LABEL, useLoad } from "../hooks";
import type { Diagnosis, Health, IncidentCard, InvestigationEvent } from "../types";

type Step = Extract<InvestigationEvent, { type: "tool" | "thought" | "error" }>;

function argText(args: Record<string, unknown>): string {
  const parts = Object.entries(args).filter(([, v]) => v !== "" && v != null).map(([k, v]) => `${k}=${String(v)}`);
  return parts.length ? parts.join(" ") : "";
}

export function Incidents({ selected, onSelect, health }: { selected: string | null; onSelect: (code: string) => void; health: Health | null }) {
  const [featured] = useLoad((s) => api.incidents(s), []);
  const [extra, setExtra] = useState<IncidentCard[]>([]);
  const list = [...extra, ...(featured ?? [])];
  const current = list.find((i) => i.code === selected) ?? list[0] ?? null;
  const [steps, setSteps] = useState<Step[]>([]);
  const [diag, setDiag] = useState<Diagnosis | null>(null);
  const [busy, setBusy] = useState(false);
  const [showPm, setShowPm] = useState(false);
  const [copied, setCopied] = useState(false);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => { abort.current?.abort(); setSteps([]); setDiag(null); setBusy(false); setShowPm(false); }, [current?.code]);
  useEffect(() => () => abort.current?.abort(), []);

  const investigate = async () => {
    if (!current || busy) return;
    const c = new AbortController();
    abort.current = c;
    setBusy(true); setSteps([]); setDiag(null); setShowPm(false);
    try {
      await api.investigate(current.code, (e) => {
        if (e.type === "diagnosis") setDiag(e);
        else if (e.type === "tool" || e.type === "thought" || e.type === "error") setSteps((s) => [...s, e]);
      }, c.signal);
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) setSteps((s) => [...s, { type: "error", message: "Connection lost." }]);
    } finally {
      setBusy(false);
    }
  };

  const newIncident = async () => {
    try {
      const inc = await api.newIncident();
      setExtra((x) => [inc, ...x.filter((i) => i.code !== inc.code)].slice(0, 3));
      onSelect(inc.code);
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="view">
      <header className="view-head">
        <span className="eyebrow">Incidents</span>
        <div className="row">
          <h1 className="display">From page to root cause.</h1>
          <span className="caption">The agent investigates with metrics, logs, traces, changes and runbooks · {health?.limits.runs_per_hour ?? 10} runs per hour</span>
        </div>
      </header>

      <section className="inc">
        <div className="stack">
          <div className="card-head" style={{ marginBottom: 0 }}>
            <span className="mono-label">Open incidents</span>
            <button className="pill sm" onClick={newIncident}>New incident</button>
          </div>
          <div className="inc-list">
            {list.map((i) => (
              <button key={i.code} className={`inc-card ${current?.code === i.code ? "on" : ""}`} onClick={() => onSelect(i.code)}>
                <div className="row1">
                  <span className="mono-label">{i.code}</span>
                  <span className={`sev ${i.severity}`}>{i.severity}</span>
                </div>
                <div className="t">{i.title}</div>
                <div className="d">{i.alert.detail} · {i.started_min_ago} min ago</div>
              </button>
            ))}
          </div>
        </div>

        <div className="card" aria-live="polite">
          {current && (
            <>
              <div className={`alert-box ${current.severity}`}>
                <span className="mono-label">Page · {current.code} · {current.alert.service}</span>
                <div className="big">{current.alert.summary}</div>
                <div className="caption" style={{ marginTop: 4 }}>{current.alert.detail} · started about {current.started_min_ago} minutes ago · affected: {current.affected.join(", ")}</div>
              </div>
              <div className="composer-row" style={{ margin: "14px 0 6px" }}>
                <span className="caption">
                  <a href={`#/system?i=${current.code}`}>Open the system view →</a>
                </span>
                <div className="pill-group">
                  <button className="pill primary" onClick={investigate} disabled={busy}>{busy ? "Investigating…" : diag ? "Investigate again" : "Investigate"}</button>
                </div>
              </div>

              {steps.length > 0 && (
                <ol className="trace-list" style={{ maxHeight: "none" }}>
                  {steps.map((s, i) => (
                    <li key={i} className={`trace-item ${s.type === "error" ? "fail" : ""}`}>
                      <span className="idx">{String(i + 1).padStart(2, "0")}</span>
                      <div>
                        {s.type === "tool" ? (
                          <>
                            <div><span className="tool-name">{s.name}</span> <span className="tool-args">{argText(s.args)}</span></div>
                            <div className="detail">{s.summary}</div>
                          </>
                        ) : s.type === "thought" ? (
                          <div className="detail">{s.text}</div>
                        ) : (
                          <div className="title">{s.message}</div>
                        )}
                      </div>
                      <span className="ms">{s.type === "tool" ? fmtMs(s.llm_ms) : ""}</span>
                    </li>
                  ))}
                  {busy && <li className="trace-item"><span className="idx">··</span><div className="detail">Thinking…</div><span /></li>}
                </ol>
              )}

              {diag && (
                <div className="diag">
                  <div className="diag-head">
                    <div>
                      <span className="mono-label">Root cause</span>
                      <div className="root">{diag.root_cause_service} · {FAULT_LABEL[diag.fault_type] ?? diag.fault_type}</div>
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <span className="mono-label">Confidence {Math.round(diag.confidence * 100)}%</span>
                      <div className="conf" style={{ marginLeft: "auto" }}><i style={{ width: `${diag.confidence * 100}%` }} /></div>
                    </div>
                  </div>
                  <p className="body" style={{ marginTop: 10 }}>{diag.summary}</p>
                  <div className="mono-label" style={{ marginTop: 14 }}>Evidence</div>
                  <ul>{diag.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul>
                  <div className="mono-label" style={{ marginTop: 14 }}>Mitigation</div>
                  <p className="body" style={{ marginTop: 6 }}>{diag.remediation}</p>
                  <div className="composer-row" style={{ marginTop: 16 }}>
                    <span className={`verdict ${diag.truth.correct ? "ok" : "no"}`}>
                      {diag.truth.correct ? "Matches the injected fault" : `Missed: it was ${diag.truth.root_cause_service} · ${FAULT_LABEL[diag.truth.fault_type]}`}
                    </span>
                    <span className="caption">{diag.steps} tool calls · {fmtMs(diag.ms)} · {diag.tokens.toLocaleString()} tokens</span>
                  </div>
                  <div className="pill-group" style={{ marginTop: 12 }}>
                    <button className="pill sm" onClick={() => setShowPm((v) => !v)}>{showPm ? "Hide postmortem" : "Draft postmortem"}</button>
                    {showPm && (
                      <button className="pill sm" onClick={async () => { await navigator.clipboard.writeText(diag.postmortem); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
                        {copied ? "Copied" : "Copy markdown"}
                      </button>
                    )}
                  </div>
                  {showPm && <div className="pm">{diag.postmortem}</div>}
                </div>
              )}

              {!busy && steps.length === 0 && !diag && (
                <p className="caption" style={{ marginTop: 10 }}>
                  Press Investigate to watch the agent work. It starts from the alert, which names the symptom, not the cause, and has to find the
                  failing service, the moment it broke and the evidence, the way an on-call engineer would.
                </p>
              )}
            </>
          )}
        </div>
      </section>
    </div>
  );
}
