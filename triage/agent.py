"""The investigation loop.

The model is given the alert and the tools, and must call a tool on every turn,
so it investigates rather than guesses. It ends by calling submit_diagnosis
with a structured answer. Every step is yielded as an event for the console.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

from triage import tools
from triage.llm import LLM, LLMError
from triage.simulator import FAULTS, Scenario

MAX_STEPS = 10

SYSTEM = f"""You are the on-call SRE investigating a production alert. Find the root cause with the tools, then call
submit_diagnosis exactly once.

Method:
1. The alert names where the symptom was noticed; the fault is often in a service it depends on. Start with list_services.
2. For unhealthy services, check metrics and error logs. Establish when the problem started.
3. Check recent_changes: a change is only a suspect if it hits the right service within a few minutes before onset.
4. Use traces to see which service actually fails, and runbooks to confirm the pattern.
5. Name the service where the fault originates (use "psp" for the external payment provider) and the fault type.

Fault types: {"; ".join(f"{k} = {v}" for k, v in FAULTS.items())}.
Be efficient: usually 4 to 7 tool calls are enough. Every evidence item must come from a tool result you actually
received: quote numbers and log messages exactly, and never describe changes or events the tools did not show."""

# A diagnosis is only accepted once these were consulted: the error logs and the change
# history are where rushed investigations go wrong (wrong service, invented causes).
REQUIRED_BEFORE_SUBMIT = ("search_logs", "recent_changes")
MIN_TOOL_CALLS = 3


def text_tool_calls(content: str) -> list[dict]:
    """Some models write tool calls as JSON text instead of structured calls; recover them."""
    names = {t["function"]["name"] for t in tools.SCHEMAS}
    start = content.find("{")
    if start == -1:
        return []
    found, depth, begin = [], 0, None
    for i, ch in enumerate(content[start:], start):
        if ch == "{":
            depth += 1
            begin = i if depth == 1 else begin
        elif ch == "}":
            depth -= 1
            if depth == 0 and begin is not None:
                try:
                    obj = json.loads(content[begin : i + 1])
                except json.JSONDecodeError:
                    continue
                name = obj.get("name") or obj.get("function")
                args = obj.get("parameters", obj.get("arguments", {}))
                if name in names and isinstance(args, dict):
                    found.append(
                        {
                            "id": f"text_{len(found)}",
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args)},
                        }
                    )
    return found


def alert_prompt(s: Scenario) -> str:
    a = s.alert
    return (
        f"PAGE [{s.severity.upper()}] {a['summary']}\n{a['detail']}\nTriggered on service: {a['service']} "
        f"(metric {a['metric']}). Investigate and find the root cause."
    )


def describe(name: str, args: dict, result) -> str:
    """One-line human summary of a tool call, for the console timeline."""
    try:
        if name == "list_services":
            bad = [f"{r['service']} ({r['status']})" for r in result if r["status"] != "healthy"]
            return "Unhealthy: " + ", ".join(bad) if bad else "All services healthy"
        if name == "get_metrics":
            if "error" in result:
                return result["error"]
            when = (
                f", changed {result['changed_minutes_ago']} min ago"
                if result["changed_minutes_ago"] is not None
                else ", no change"
            )
            return f"{args['service']} {args['metric']}: {result['baseline']} → {result['now']} {result['unit']}{when}"
        if name == "search_logs":
            top = result["templates"][:1]
            return (
                f"{result['matches']} message types; top: [{top[0]['level']}] {top[0]['message'][:90]} ×{top[0]['count']}"
                if top
                else "No matching logs"
            )
        if name == "get_traces":
            errs = [sp.get("error") for t in result["traces"] for sp in t["spans"] if sp.get("error")]
            return (
                f"{len(result['traces'])} failing traces; {errs[0][:90]}" if errs else f"{len(result['traces'])} traces"
            )
        if name == "recent_changes":
            return (
                "; ".join(f"{c['service']} {c['kind']} {c['minutes_ago']} min ago" for c in result["changes"])
                or "No changes"
            )
        if name == "search_runbooks":
            return ", ".join(f"{r['runbook']} › {r['section']}" for r in result["results"]) or "No runbook matched"
    except (KeyError, IndexError, TypeError):
        pass
    return "done"


def postmortem(s: Scenario, d: dict, timeline: list[dict]) -> str:
    steps = "\n".join(
        f"{i}. `{t['name']}` {json.dumps(t['args']) if t['args'] else ''} → {t['summary']}"
        for i, t in enumerate(timeline, 1)
    )
    evidence = "\n".join(f"- {e}" for e in d.get("evidence", []))
    return (
        f"# Incident: {s.alert['summary']}\n\n"
        f"**Severity:** {s.severity} · **Detected on:** {s.alert['service']} · **Started:** about "
        f"{s.minutes_ago(s.onset)} minutes before the page\n\n"
        f"## Summary\n{d.get('summary', '')}\n\n"
        f"## Root cause\n`{d.get('root_cause_service')}`: {FAULTS.get(d.get('fault_type', ''), d.get('fault_type', ''))}\n\n"
        f"## Evidence\n{evidence}\n\n## Mitigation\n{d.get('remediation', '')}\n\n"
        f"## Investigation\n{steps}\n\n_Drafted by Triage; confidence {d.get('confidence', 0):.0%}. Review before sharing._\n"
    )


class Agent:
    def __init__(self, llm: LLM, max_steps: int = MAX_STEPS):
        self.llm, self.max_steps = llm, max_steps

    async def investigate(self, s: Scenario) -> AsyncIterator[dict]:
        t0 = time.perf_counter()
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": alert_prompt(s)}]
        yield {"type": "start", "scenario": s.id, "alert": s.alert, "severity": s.severity}
        timeline: list[dict] = []
        tokens = 0
        choice = "required"
        for step in range(1, self.max_steps + 1):
            if step == self.max_steps:
                messages.append({"role": "user", "content": "Step limit reached: call submit_diagnosis now."})
            try:
                reply = await self.llm.chat(messages, tools=tools.SCHEMAS, tool_choice=choice)
            except LLMError as e:
                if choice == "required" and "tool_choice" in str(e):
                    choice = "auto"  # provider without forced tool use
                    continue
                yield {"type": "error", "message": str(e)}
                return
            tokens += reply.tokens
            if reply.message.get("content") and not reply.tool_calls:
                reply.tool_calls = text_tool_calls(reply.message["content"])
            if reply.message.get("content") and not reply.tool_calls:
                messages.append({"role": "assistant", "content": reply.message["content"]})
                messages.append({"role": "user", "content": "Continue with the tools, or call submit_diagnosis."})
                yield {"type": "thought", "text": reply.message["content"][:400]}
                continue
            messages.append({"role": "assistant", "content": "", "tool_calls": reply.tool_calls})
            for tc in reply.tool_calls:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                if name == "submit_diagnosis":
                    used = {t["name"] for t in timeline}
                    missing = [r for r in REQUIRED_BEFORE_SUBMIT if r not in used]
                    if (missing or len(timeline) < MIN_TOOL_CALLS) and step < self.max_steps - 1:
                        need = ", ".join(missing) if missing else "more evidence"
                        note = (
                            f"Not accepted yet: verify with {need} before concluding, then submit again with "
                            "evidence taken only from tool results."
                        )
                        messages.append({"role": "tool", "tool_call_id": tc.get("id", f"call_{step}"), "content": note})
                        yield {"type": "thought", "text": f"Diagnosis held back for verification: check {need} first."}
                        continue
                    correct = args.get("root_cause_service") == s.root_service and args.get("fault_type") == s.fault
                    yield {
                        "type": "diagnosis",
                        **args,
                        "steps": len(timeline),
                        "tokens": tokens,
                        "ms": round((time.perf_counter() - t0) * 1000),
                        "model": reply.model,
                        "postmortem": postmortem(s, args, timeline),
                        "truth": {
                            "root_cause_service": s.root_service,
                            "fault_type": s.fault,
                            "correct": correct,
                            "reference_remediation": s.remediation,
                        },
                    }
                    return
                t = time.perf_counter()
                result = tools.call(s, name, args)
                entry = {"name": name, "args": args, "summary": describe(name, args, result)}
                timeline.append(entry)
                messages.append(
                    {"role": "tool", "tool_call_id": tc.get("id", f"call_{step}"), "content": tools.compact(result)}
                )
                yield {
                    "type": "tool",
                    "step": len(timeline),
                    **entry,
                    "model": reply.model,
                    "llm_ms": round(reply.ms),
                    "tool_ms": round((time.perf_counter() - t) * 1000, 1),
                }
        yield {"type": "error", "message": "no diagnosis within the step limit"}


async def alert_only_baseline(llm: LLM, s: Scenario) -> dict:
    """Ablation: the same model, the alert and the service graph, but no investigation tools."""
    graph = "; ".join(f"{k} -> {', '.join(v[1]) or 'none'}" for k, v in tools.SERVICES.items())
    messages = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": alert_prompt(s) + f"\nDependencies: {graph}\nNo other data is available: "
            "call submit_diagnosis with your best judgement.",
        },
    ]
    submit = [t for t in tools.SCHEMAS if t["function"]["name"] == "submit_diagnosis"]
    reply = await llm.chat(messages, tools=submit, tool_choice="required", max_tokens=600)
    for tc in reply.tool_calls:
        if tc["function"]["name"] == "submit_diagnosis":
            try:
                return json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                break
    return {}
