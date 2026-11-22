import pytest

from triage import runbooks, tools
from triage.simulator import FAULTS, SERVICES, build, scenario_ids, summarize_series


def test_deterministic():
    a, b = build("memory_leak", 3), build("memory_leak", 3)
    assert a.metrics == b.metrics and [c.summary for c in a.changes] == [c.summary for c in b.changes]
    assert build("memory_leak", 4).metrics != a.metrics


def test_benchmark_set():
    ids = scenario_ids()
    assert len(ids) == 35 and len(set(ids)) == 35  # 7 fault types x 5 seeds


@pytest.mark.parametrize("fault", list(FAULTS))
def test_every_fault_is_discoverable(fault):
    s = build(fault, 2)
    assert s.root_service in SERVICES
    health = {r["service"]: r["status"] for r in tools.list_services(s)}
    assert health[s.alert["service"]] != "healthy", "the alerting service must look unhealthy"
    # some log evidence exists after the onset on the root service or its direct caller
    errors = tools.search_logs(s, level="ERROR")["templates"] + tools.search_logs(s, level="FATAL")["templates"]
    assert errors, "each fault leaves error logs"
    assert s.traces, "each fault has sample failing traces"


def test_alert_names_the_symptom_not_always_the_cause():
    mismatched = sum(build(f, 1).alert["service"] != build(f, 1).root_service for f in FAULTS)
    assert mismatched >= 4


def test_onset_detected_in_metrics():
    s = build("db_connection_exhaustion", 1)
    summary = summarize_series(s.metrics["postgres"]["connections"], "connections")
    assert summary["now"] > 95 and summary["changed_minutes_ago"] is not None
    assert abs(summary["changed_minutes_ago"] - s.minutes_ago(s.onset)) <= 3


@pytest.mark.parametrize(
    "fault,expected",
    [
        ("certificate_expired", "Expired TLS certificate"),
        ("db_connection_exhaustion", "Database connection pool exhaustion"),
        ("memory_leak", "Memory leak and OOM kills"),
        ("bad_config", "Failures after a configuration change"),
        ("dependency_latency", "Slow external dependency"),
        ("disk_full", "Disk full on the database host"),
    ],
)
def test_runbook_search_finds_the_right_runbook_from_the_error(fault, expected):
    s = build(fault, 1)
    top_error = next(t.message for t in s.logs if t.level in ("ERROR", "FATAL"))
    assert runbooks.search(top_error)[0]["runbook"] == expected


def test_tool_outputs_are_compact():
    s = build("bad_deploy", 1)
    for name, args in [
        ("list_services", {}),
        ("search_logs", {}),
        ("recent_changes", {}),
        ("get_metrics", {"service": "gateway", "metric": "error_rate"}),
        ("get_traces", {}),
    ]:
        assert len(tools.compact(tools.call(s, name, args))) < 2500, name
    assert "error" in tools.call(s, "get_metrics", {"service": "redis", "metric": "connections"})


def test_disk_full_scenario():
    s = build("disk_full", 1)
    assert s.root_service == "postgres"
    disk = s.metrics["postgres"]["disk_pct"]
    assert max(disk) >= 99 and max(disk[: s.onset]) < 60, "disk fills up at the onset and stays full"
    err = s.metrics["catalog"]["error_rate"]
    assert err[s.onset - 1] < 0.05 and err[-1] > 0.8, "writes fail after the onset, not before"
    assert any("No space left" in t.message for t in s.logs if t.level == "ERROR")
    assert any("No space left" in sp.get("error", "") for tr in s.traces for sp in tr["spans"])
    assert "disk" in s.remediation.lower()
    assert s.alert["service"] == "catalog" and s.alert["metric"] == "error_rate"


def test_disk_full_is_deterministic_and_onset_is_visible_in_metrics():
    a, b = build("disk_full", 2), build("disk_full", 2)
    assert a.metrics == b.metrics and a.remediation == b.remediation
    assert build("disk_full", 3).metrics != a.metrics
    summary = summarize_series(a.metrics["postgres"]["disk_pct"], "disk_pct")
    assert summary["now"] >= 99 and summary["changed_minutes_ago"] is not None
    out = tools.call(a, "get_metrics", {"service": "postgres", "metric": "disk_pct"})
    assert out["metric"] == "disk_pct" and out["now"] >= 99
