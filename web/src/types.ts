export interface Alert {
  service: string;
  metric: string;
  summary: string;
  detail: string;
}

export interface IncidentCard {
  code: string;
  title: string;
  severity: "critical" | "high";
  alert: Alert;
  started_min_ago: number;
  affected: string[];
}

export interface ServiceHealth {
  service: string;
  kind: string;
  depends_on: string[];
  status: "healthy" | "degraded" | "unhealthy";
  error_rate_pct: number;
  baseline_error_pct: number;
  p95_ms: number;
  baseline_p95_ms: number;
}

export interface Change {
  minutes_ago: number;
  service: string;
  kind: "deploy" | "config";
  summary: string;
  author: string;
}

export interface IncidentDetail extends IncidentCard {
  window_minutes: number;
  services: ServiceHealth[];
  topology: Record<string, string[]>;
  metrics: Record<string, Record<string, number[]>>;
  changes: Change[];
}

export interface Diagnosis {
  type: "diagnosis";
  root_cause_service: string;
  fault_type: string;
  summary: string;
  evidence: string[];
  remediation: string;
  confidence: number;
  steps: number;
  tokens: number;
  ms: number;
  model: string;
  postmortem: string;
  truth: { root_cause_service: string; fault_type: string; correct: boolean; reference_remediation: string };
}

export type InvestigationEvent =
  | { type: "start"; scenario: string; alert: Alert; severity: string }
  | { type: "tool"; step: number; name: string; args: Record<string, unknown>; summary: string; model: string; llm_ms: number; tool_ms: number }
  | { type: "thought"; text: string }
  | Diagnosis
  | { type: "error"; message: string };

export interface Runbook {
  id: string;
  title: string;
  markdown: string;
}

export interface Health {
  status: string;
  environment: string;
  llm: { endpoint: string; via_sluice: boolean; model: string };
  fault_types: number;
  services: number;
  runbooks: number;
  limits: { runs_per_hour: number };
}

export interface Benchmark {
  benchmark: string;
  metric: string;
  n: number;
  agent: { accuracy: number; service_accuracy: number };
  baseline_alert_only: { accuracy: number; service_accuracy: number };
  by_fault: Record<string, { n: number; agent: number; baseline: number }>;
  median_steps: number;
  median_seconds: number;
  median_tokens: number;
  avg_confidence_correct: number;
  tool_usage: Record<string, number>;
}
