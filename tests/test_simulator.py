import pytest

from triage import runbooks, tools
from triage.simulator import FAULTS, SERVICES, build, scenario_ids, summarize_series


def test_deterministic():
    a, b = build("memory_leak", 3), build("memory_leak", 3)
    assert a.metrics == b.metrics and [c.summary for c in a.changes] == [c.summary for c in b.changes]
    assert build("memory_leak", 4).metrics != a.metrics


def test_benchmark_set():
    ids = scenario_ids()
    assert len(ids) == 30 and len(set(ids)) == 30


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
