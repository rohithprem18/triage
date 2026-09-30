"""The tools the agent investigates with, and their OpenAI function schemas.

Outputs are compact on purpose: every tool result is resent to the model on each
step, and free tiers allow a few thousand tokens per minute.
"""

from __future__ import annotations

import json
import re

from triage import runbooks
from triage.simulator import FAULTS, METRICS, SERVICES, WINDOW, Scenario, summarize_series

SERVICE_NAMES = list(SERVICES)


def _fn(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required or []},
        },
    }


SCHEMAS = [
    _fn("list_services", "All services with their dependencies and current health versus baseline.", {}),
    _fn(
        "get_metrics",
        "One service's metric over the last 60 minutes: baseline, now, max, when it changed, 5-minute points.",
        {"service": {"type": "string", "enum": SERVICE_NAMES}, "metric": {"type": "string", "enum": METRICS}},
        ["service", "metric"],
    ),
    _fn(
        "search_logs",
        "Log messages grouped by template with counts, newest problems first. Filter by service, level and/or text.",
        {
            "service": {"type": "string", "enum": SERVICE_NAMES},
            "level": {"type": "string", "enum": ["ERROR", "FATAL", "WARN", "INFO", "LOG"]},
            "query": {"type": "string", "description": "case-insensitive text to match in the message"},
        },
    ),
    _fn(
        "get_traces",
        "Sample failing request traces: each span's service, status, duration and error.",
        {"service": {"type": "string", "enum": SERVICE_NAMES, "description": "only traces that touch this service"}},
    ),
    _fn("recent_changes", "Deploys and configuration changes in the last 60 minutes, with minutes ago.", {}),
    _fn(
        "search_runbooks",
        "Search the team's runbooks for guidance on symptoms or error messages.",
        {"query": {"type": "string"}},
        ["query"],
    ),
    _fn(
        "submit_diagnosis",
        "Finish the investigation with your conclusion. Call exactly once, when confident.",
        {
            "root_cause_service": {
                "type": "string",
                "enum": SERVICE_NAMES,
                "description": "the service where the fault originates (use psp for the external payment provider)",
            },
            "fault_type": {"type": "string", "enum": list(FAULTS)},
            "summary": {"type": "string", "description": "one or two sentences: what broke, why, and the impact"},
            "evidence": {
                "type": "array",
                "items": {"type": "string"},
                "description": "3-5 concrete observations that support it",
            },
            "remediation": {"type": "string", "description": "the immediate mitigation, then the follow-up fix"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        ["root_cause_service", "fault_type", "summary", "evidence", "remediation", "confidence"],
    ),
]


def _health(s: Scenario, name: str) -> dict:
    m = s.metrics[name]
    err = summarize_series(m["error_rate"], "error_rate")
    p95 = summarize_series(m["p95_ms"], "p95_ms")
    status = "healthy"
    if err["now"] > 5 or p95["now"] > 3 * max(1.0, p95["baseline"]):
        status = "unhealthy"
    elif err["now"] > 1 or p95["now"] > 1.6 * max(1.0, p95["baseline"]):
        status = "degraded"
    return {
        "service": name,
        "kind": SERVICES[name][0],
        "depends_on": SERVICES[name][1],
        "status": status,
        "error_rate_pct": err["now"],
        "baseline_error_pct": err["baseline"],
        "p95_ms": p95["now"],
        "baseline_p95_ms": p95["baseline"],
    }


def list_services(s: Scenario) -> list[dict]:
    return [_health(s, n) for n in SERVICE_NAMES]


def get_metrics(s: Scenario, service: str, metric: str) -> dict:
    if service not in s.metrics:
        return {"error": f"unknown service {service}"}
    series = s.metrics[service].get(metric)
    if series is None:
        return {"error": f"{service} has no {metric} metric", "available": list(s.metrics[service])}
    return {"service": service, "metric": metric, **summarize_series(series, metric)}


def search_logs(s: Scenario, service: str | None = None, level: str | None = None, query: str | None = None) -> dict:
    rows = []
    for t in s.logs:
        if service and t.service != service:
            continue
        if level and t.level != level:
            continue
        if query and query.lower() not in t.message.lower():
            continue
        active = [i for i, c in enumerate(t.per_minute) if c >= 0.5]
        if not active:
            continue
        rows.append(
            {
                "service": t.service,
                "level": t.level,
                "message": t.message,
                "count": t.total,
                "first_seen_min_ago": WINDOW - 1 - active[0],
                "last_seen_min_ago": WINDOW - 1 - active[-1],
            }
        )
    severity = {"FATAL": 0, "ERROR": 1, "WARN": 2, "LOG": 3, "INFO": 4}
    rows.sort(key=lambda r: (severity.get(r["level"], 5), -r["count"]))
    return {"matches": len(rows), "templates": rows[:8]}


def get_traces(s: Scenario, service: str | None = None) -> dict:
    tr = [t for t in s.traces if not service or any(sp["service"] == service for sp in t["spans"])]
    return {"traces": tr[:2], "note": "spans are listed caller first"}


def recent_changes(s: Scenario) -> dict:
    return {
        "changes": [
            {
                "minutes_ago": s.minutes_ago(c.minute),
                "service": c.service,
                "kind": c.kind,
                "summary": c.summary,
                "author": c.author,
            }
            for c in s.changes
        ]
    }


def search_runbooks(s: Scenario, query: str) -> dict:
    return {"results": runbooks.search(query, k=2)}


IMPLS = {
    "list_services": list_services,
    "get_metrics": get_metrics,
    "search_logs": search_logs,
    "get_traces": get_traces,
    "recent_changes": recent_changes,
    "search_runbooks": search_runbooks,
}


def call(s: Scenario, name: str, args: dict) -> dict | list:
    fn = IMPLS.get(name)
    if fn is None:
        return {"error": f"unknown tool {name}"}
    try:
        return fn(s, **{k: v for k, v in args.items() if v not in (None, "")})
    except TypeError as e:
        return {"error": f"bad arguments for {name}: {e}"}


def compact(result) -> str:
    text = json.dumps(result, separators=(",", ":"))
    return re.sub(r"\.0(?=[,}\]])", "", text)[:3500]
