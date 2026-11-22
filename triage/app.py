"""HTTP surface.

GET  /api/incidents               featured incidents (opaque codes: the fault is not revealed)
POST /api/incidents/new           a fresh random incident
GET  /api/incidents/{code}        alert, service health, metrics and changes for the console
POST /api/investigate             NDJSON stream of the agent's investigation
GET  /api/runbooks                the runbooks the agent can search
GET  /api/benchmark               accuracy on 35 simulated incidents
GET  /api/health
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from triage import __version__, runbooks, tools
from triage.agent import Agent
from triage.config import Settings, get_settings
from triage.limits import Limiter
from triage.llm import LLM
from triage.simulator import FAULTS, SERVICES, WINDOW, build

HERE = Path(__file__).resolve().parent
BENCHMARK = HERE / "benchmark.json"
MAX_SEED = 40
FEATURED = [(f, 1) for f in FAULTS]


# Opaque, stable incident numbers: a fixed shuffle of every (fault, seed), so the code
# never hints at the fault and never collides.
_ALL = [(f, s) for f in FAULTS for s in range(1, MAX_SEED + 1)]
random.Random(20260930).shuffle(_ALL)
CODES = {f"INC-{1000 + i}": pair for i, pair in enumerate(_ALL)}
_BY_PAIR = {pair: code for code, pair in CODES.items()}


def code_of(fault: str, seed: int) -> str:
    return _BY_PAIR[(fault, seed)]


class Services:
    def __init__(self, s: Settings, llm=None, limiter: Limiter | None = None):
        self.settings = s
        self.agent = Agent(llm or LLM(s.llm_base_url, s.llm_api_key, s.llm_model))
        self.limiter = limiter or Limiter(s.redis_url, s.redis_token)


_svc: Services | None = None


def services() -> Services:
    global _svc
    if _svc is None:
        _svc = Services(get_settings())
    return _svc


def set_services(svc: Services | None) -> None:
    global _svc
    _svc = svc


app = FastAPI(
    title="Triage", version=__version__, description="Incident-response agent over a simulated production system"
)


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": {"message": message}}, status_code=status)


def _ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


def _card(code: str) -> dict:
    fault, seed = CODES[code]
    sc = build(fault, seed)
    affected = [r["service"] for r in tools.list_services(sc) if r["status"] != "healthy"]
    return {
        "code": code,
        "title": sc.title,
        "severity": sc.severity,
        "alert": sc.alert,
        "started_min_ago": sc.minutes_ago(sc.onset),
        "affected": affected,
    }


@app.get("/api/incidents")
async def incidents():
    return [_card(code_of(f, s)) for f, s in FEATURED]


@app.post("/api/incidents/new")
async def new_incident():
    fault = random.choice(list(FAULTS))
    seed = random.randint(6, MAX_SEED)  # seeds 1-5 are the benchmark set
    return _card(code_of(fault, seed))


@app.get("/api/incidents/{code}")
async def incident(code: str):
    if code not in CODES:
        return _error(404, f"unknown incident {code}")
    fault, seed = CODES[code]
    sc = build(fault, seed)
    wanted = {"error_rate": 100.0, "p95_ms": 1.0, "rps": 1.0, "memory": 1.0, "restarts": 1.0, "connections": 1.0}
    metrics = {
        svc: {
            m: [round(v * scale, 2) for v in series] for m, series in ms.items() if m in wanted for scale in [wanted[m]]
        }
        for svc, ms in sc.metrics.items()
    }
    return {
        **_card(code),
        "window_minutes": WINDOW,
        "services": tools.list_services(sc),
        "topology": {name: spec[1] for name, spec in SERVICES.items()},
        "metrics": metrics,
        "changes": tools.recent_changes(sc)["changes"],
    }


class InvestigateRequest(BaseModel):
    code: str


@app.post("/api/investigate")
async def investigate(body: InvestigateRequest, request: Request):
    if body.code not in CODES:
        return _error(404, f"unknown incident {body.code}")
    svc = services()
    s = svc.settings
    ok, remaining, reset = await svc.limiter.hit(f"ip:{_ip(request)}", s.runs_per_hour, 3600)
    if not ok:
        return _error(
            429, f"the demo allows {s.runs_per_hour} investigations per hour; try again in {reset // 60 + 1} min"
        )
    ok, _, _ = await svc.limiter.hit("all", s.runs_per_day_total, 86400)
    if not ok:
        return _error(429, "the demo's daily budget is used up; it resets at 00:00 UTC")
    fault, seed = CODES[body.code]
    sc = build(fault, seed)

    async def ndjson():
        async for ev in svc.agent.investigate(sc):
            if ev["type"] == "start":
                ev["scenario"] = body.code  # keep the fault hidden until the diagnosis
            yield (json.dumps(ev, default=str) + "\n").encode()

    return StreamingResponse(
        ndjson(),
        media_type="application/x-ndjson",
        headers={"cache-control": "no-cache", "x-remaining-hour": str(remaining)},
    )


@app.get("/api/runbooks")
async def list_runbooks():
    return runbooks.all_runbooks()


@app.get("/api/benchmark")
async def benchmark():
    if not BENCHMARK.exists():
        return _error(404, "benchmark results not generated yet")
    return json.loads(BENCHMARK.read_text(encoding="utf-8"))


@app.get("/api/health")
async def health():
    s = services().settings
    return {
        "status": "ok",
        "version": __version__,
        "environment": "simulated",
        "llm": {
            "endpoint": s.llm_base_url.split("//")[-1].split("/")[0],
            "via_sluice": "sluice" in s.llm_base_url,
            "model": s.llm_model,
        },
        "fault_types": len(FAULTS),
        "services": len(SERVICES),
        "runbooks": len(runbooks.all_runbooks()),
        "limits": {"runs_per_hour": s.runs_per_hour},
    }


_static = Path(os.getenv("TRIAGE_STATIC_DIR", HERE.parent / "web" / "dist"))
if (_static / "index.html").exists() and os.getenv("VERCEL") is None:
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_static, html=True), name="console")
