"""Root-cause accuracy on 30 simulated incidents (6 fault types x 5 seeds).

    python bench/eval_incidents.py            # resumable
    python bench/eval_incidents.py --summarize

For each incident the agent investigates with tools; as an ablation the same
model also answers from the alert and the dependency graph alone. A diagnosis is
correct when both the root-cause service and the fault type match the injected
fault.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from triage.agent import Agent, alert_only_baseline  # noqa: E402
from triage.config import get_settings  # noqa: E402
from triage.llm import LLM, LLMError  # noqa: E402
from triage.simulator import FAULTS, load, scenario_ids  # noqa: E402

RESULTS = ROOT / "bench" / "results"
LOG = RESULTS / "incidents.jsonl"


async def run() -> None:
    s = get_settings()
    llm = LLM(s.llm_base_url, s.llm_api_key, s.llm_model)
    agent = Agent(llm)
    done = set()
    if LOG.exists():
        done = {json.loads(x)["id"] for x in LOG.read_text(encoding="utf-8").splitlines() if x}
    todo = [i for i in scenario_ids() if i not in done]
    print(f"{len(done)} done, {len(todo)} to run", flush=True)
    for n, sid in enumerate(todo, 1):
        sc = load(sid)
        t = time.perf_counter()
        diag, tools_used, error = None, [], None
        async for e in agent.investigate(sc):
            if e["type"] == "tool":
                tools_used.append(e["name"])
            elif e["type"] == "diagnosis":
                diag = e
            elif e["type"] == "error":
                error = e["message"]
        try:
            base = await alert_only_baseline(llm, sc)
        except LLMError as e:
            base = {"error": str(e)}
        rec = {
            "id": sid,
            "fault": sc.fault,
            "truth_service": sc.root_service,
            "agent_service": diag.get("root_cause_service") if diag else None,
            "agent_fault": diag.get("fault_type") if diag else None,
            "agent_correct": bool(diag and diag["truth"]["correct"]),
            "agent_service_correct": bool(diag and diag.get("root_cause_service") == sc.root_service),
            "confidence": diag.get("confidence") if diag else None,
            "steps": len(tools_used),
            "tools": tools_used,
            "tokens": diag.get("tokens") if diag else None,
            "seconds": round(time.perf_counter() - t, 1),
            "error": error,
            "baseline_service": base.get("root_cause_service"),
            "baseline_fault": base.get("fault_type"),
            "baseline_correct": base.get("root_cause_service") == sc.root_service
            and base.get("fault_type") == sc.fault,
            "baseline_service_correct": base.get("root_cause_service") == sc.root_service,
        }
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        print(
            f"[{n}/{len(todo)}] {sid:28s} agent={'OK' if rec['agent_correct'] else 'NO'} "
            f"baseline={'OK' if rec['baseline_correct'] else 'NO'} steps={rec['steps']} {rec['seconds']}s",
            flush=True,
        )
        await asyncio.sleep(3)


def summarize() -> dict:
    recs = [json.loads(x) for x in LOG.read_text(encoding="utf-8").splitlines() if x]

    def rate(key, items=None):
        items = recs if items is None else items
        return round(sum(r[key] for r in items) / len(items), 4) if items else None

    by_fault = {}
    for f in FAULTS:
        items = [r for r in recs if r["fault"] == f]
        by_fault[f] = {
            "n": len(items),
            "agent": rate("agent_correct", items),
            "baseline": rate("baseline_correct", items),
        }
    ok = [r for r in recs if r["agent_correct"]]
    summary = {
        "benchmark": "30 simulated incidents: 6 fault types x 5 seeds",
        "metric": "diagnosis correct = root-cause service AND fault type match the injected fault",
        "n": len(recs),
        "agent": {"accuracy": rate("agent_correct"), "service_accuracy": rate("agent_service_correct")},
        "baseline_alert_only": {
            "accuracy": rate("baseline_correct"),
            "service_accuracy": rate("baseline_service_correct"),
        },
        "by_fault": by_fault,
        "median_steps": sorted(r["steps"] for r in recs)[len(recs) // 2] if recs else None,
        "median_seconds": sorted(r["seconds"] for r in recs)[len(recs) // 2] if recs else None,
        "median_tokens": sorted(r["tokens"] or 0 for r in recs)[len(recs) // 2] if recs else None,
        "avg_confidence_correct": round(sum(r["confidence"] or 0 for r in ok) / len(ok), 3) if ok else None,
        "tool_usage": dict(collections.Counter(t for r in recs for t in r["tools"]).most_common()),
        "failures": [
            {"id": r["id"], "said": f"{r['agent_service']}/{r['agent_fault']}", "error": r["error"]}
            for r in recs
            if not r["agent_correct"]
        ],
    }
    (RESULTS / "incidents_summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--summarize", action="store_true")
    args = ap.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    if not args.summarize:
        asyncio.run(run())
    print(json.dumps(summarize(), indent=2))


if __name__ == "__main__":
    main()
