import json

import pytest
from fastapi.testclient import TestClient

from triage.agent import Agent, text_tool_calls
from triage.app import CODES, Services, app, set_services
from triage.config import Settings
from triage.limits import Limiter
from triage.llm import Reply
from triage.simulator import build


def call(name, **args):
    return {"id": f"c_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class ScriptedLLM:
    """Plays a fixed investigation: each reply is a list of tool calls (or a string of text)."""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.seen: list[list[dict]] = []

    async def chat(self, messages, tools=None, tool_choice=None, max_tokens=900):
        self.seen.append(list(messages))
        turn = self.turns.pop(0)
        if isinstance(turn, str):
            return Reply(message={"role": "assistant", "content": turn}, model="fake", ms=1, tokens=10)
        return Reply(
            message={"role": "assistant", "content": None, "tool_calls": turn},
            model="fake",
            ms=1,
            tokens=10,
            tool_calls=turn,
        )


DIAGNOSIS = dict(
    root_cause_service="payments",
    fault_type="certificate_expired",
    summary="cert expired",
    evidence=["x509 errors"],
    remediation="renew",
    confidence=0.9,
)


@pytest.mark.asyncio
async def test_investigation_runs_tools_then_diagnoses():
    llm = ScriptedLLM(
        [call("list_services")],
        [call("search_logs", service="payments", level="ERROR")],
        [call("recent_changes")],
        [call("submit_diagnosis", **DIAGNOSIS)],
    )
    events = [e async for e in Agent(llm).investigate(build("certificate_expired", 1))]
    kinds = [e["type"] for e in events]
    assert kinds == ["start", "tool", "tool", "tool", "diagnosis"]
    assert "x509" in events[2]["summary"]
    final = events[-1]
    assert final["truth"]["correct"] and final["steps"] == 3
    assert "## Root cause" in final["postmortem"]
    # tool results were fed back to the model
    assert any(m["role"] == "tool" for m in llm.seen[-1])


@pytest.mark.asyncio
async def test_early_diagnosis_is_held_back_until_logs_and_changes_are_checked():
    llm = ScriptedLLM(
        [call("list_services")],
        [call("submit_diagnosis", **DIAGNOSIS)],  # too early: rejected
        [call("search_logs", service="payments")],
        [call("recent_changes")],
        [call("submit_diagnosis", **DIAGNOSIS)],
    )
    events = [e async for e in Agent(llm).investigate(build("certificate_expired", 1))]
    assert [e["type"] for e in events] == ["start", "tool", "thought", "tool", "tool", "diagnosis"]
    assert "search_logs" in events[2]["text"] and "recent_changes" in events[2]["text"]


@pytest.mark.asyncio
async def test_wrong_diagnosis_is_scored_wrong():
    llm = ScriptedLLM(
        [call("search_logs")],
        [call("recent_changes")],
        [call("list_services")],
        [call("submit_diagnosis", **{**DIAGNOSIS, "root_cause_service": "checkout"})],
    )
    events = [e async for e in Agent(llm).investigate(build("certificate_expired", 1))]
    assert events[-1]["truth"]["correct"] is False


@pytest.mark.asyncio
async def test_text_tool_calls_are_recovered():
    llm = ScriptedLLM(
        '[[{"name": "recent_changes", "parameters": {}}]]',
        [call("search_logs")],
        [call("list_services")],
        [call("submit_diagnosis", **DIAGNOSIS)],
    )
    events = [e async for e in Agent(llm).investigate(build("certificate_expired", 1))]
    assert [e["type"] for e in events] == ["start", "tool", "tool", "tool", "diagnosis"]
    assert events[1]["name"] == "recent_changes"


def test_text_tool_call_parser_ignores_prose():
    assert text_tool_calls("The payments service looks broken.") == []
    assert text_tool_calls('{"name": "not_a_tool", "parameters": {}}') == []


@pytest.fixture
def client():
    s = Settings(
        llm_base_url="http://fake", llm_api_key="", llm_model="m", redis_url="", redis_token="", runs_per_hour=1
    )
    llm = ScriptedLLM(
        [call("search_logs")],
        [call("recent_changes")],
        [call("list_services")],
        [call("submit_diagnosis", **DIAGNOSIS)],
    )
    set_services(Services(s, llm=llm, limiter=Limiter()))
    yield TestClient(app)
    set_services(None)


def test_incident_list_never_reveals_the_fault(client):
    cards = client.get("/api/incidents").json()
    assert len(cards) == 6 and all(c["code"].startswith("INC-") for c in cards)
    text = json.dumps(cards)
    for fault in ("certificate", "memory_leak", "bad_config", "db_connection"):
        assert fault not in text


def test_incident_detail_and_investigate_stream(client):
    code = next(c for c, (f, s) in CODES.items() if (f, s) == ("certificate_expired", 1))
    detail = client.get(f"/api/incidents/{code}").json()
    assert len(detail["metrics"]["payments"]["error_rate"]) == 60 and detail["topology"]["checkout"]
    r = client.post("/api/investigate", json={"code": code})
    events = [json.loads(x) for x in r.text.splitlines()]
    assert events[0]["scenario"] == code and events[-1]["type"] == "diagnosis"
    assert client.post("/api/investigate", json={"code": code}).status_code == 429  # 1 per hour in this test
    assert client.get("/api/incidents/INC-0000").status_code == 404


def test_runbooks_and_health(client):
    assert len(client.get("/api/runbooks").json()) == 7
    assert client.get("/api/health").json()["environment"] == "simulated"
