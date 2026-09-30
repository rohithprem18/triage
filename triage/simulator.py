"""A deterministic simulated production environment for incident investigation.

An e-commerce system of eight services plus an external payment provider. Each
scenario injects one fault at an onset time and produces 60 minutes of metrics,
log templates with counts, sample traces, the change history (deploys and config
edits) and the alert that paged the on-call engineer. The alert describes the
symptom where it was noticed, not the cause, and every scenario carries red
herrings (unrelated deploys, noisy warnings), so finding the root cause takes
an actual investigation.

Everything is a pure function of (fault, seed): the same inputs always give the
same incident, which makes the benchmark reproducible.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

WINDOW = 60  # minutes of history

SERVICES = {
    # name: (kind, depends_on, baseline rps, baseline p95 ms, baseline cpu %, baseline memory %)
    "gateway": ("edge", ["checkout", "cart", "catalog"], 220, 180, 35, 48),
    "checkout": ("service", ["payments", "inventory", "cart"], 40, 240, 30, 52),
    "payments": ("service", ["psp"], 35, 300, 22, 45),
    "inventory": ("service", ["postgres"], 60, 60, 28, 50),
    "cart": ("service", ["redis"], 90, 25, 25, 40),
    "catalog": ("service", ["postgres"], 150, 80, 32, 55),
    "postgres": ("database", [], 480, 8, 40, 62),
    "redis": ("cache", [], 900, 1, 12, 35),
    "psp": ("external", [], 35, 260, 0, 0),
}

FAULTS = {
    "bad_deploy": "A new release introduced an application error",
    "db_connection_exhaustion": "The service exhausted its database connection pool",
    "memory_leak": "Memory grows until the process is OOM-killed and restarts",
    "dependency_latency": "An external dependency became slow and calls time out",
    "certificate_expired": "A TLS certificate expired and handshakes fail",
    "bad_config": "A configuration change broke connectivity",
}

METRICS = ["rps", "error_rate", "p95_ms", "cpu", "memory", "restarts", "connections"]


@dataclass
class LogTemplate:
    service: str
    level: str
    message: str
    per_minute: list[float]  # expected count per minute across the window

    @property
    def total(self) -> int:
        return int(round(sum(self.per_minute)))


@dataclass
class Change:
    minute: int
    service: str
    kind: str  # deploy | config
    summary: str
    author: str


@dataclass
class Scenario:
    id: str
    fault: str
    seed: int
    root_service: str
    onset: int  # minute index within the window
    alert: dict
    metrics: dict[str, dict[str, list[float]]]
    logs: list[LogTemplate]
    changes: list[Change]
    traces: list[dict]
    remediation: str
    title: str
    severity: str
    notes: list[str] = field(default_factory=list)

    def minutes_ago(self, minute: int) -> int:
        return WINDOW - 1 - minute


def _series(rng: random.Random, base: float, noise: float, n: int = WINDOW) -> list[float]:
    return [max(0.0, base * (1 + rng.gauss(0, noise))) for _ in range(n)]


def _ramp(onset: int, n: int = WINDOW, width: int = 3) -> list[float]:
    """0 before onset, rising to 1 over `width` minutes."""
    return [0.0 if i < onset else min(1.0, (i - onset + 1) / width) for i in range(n)]


def baseline(rng: random.Random) -> dict[str, dict[str, list[float]]]:
    m: dict[str, dict[str, list[float]]] = {}
    for name, (_kind, _deps, rps, p95, cpu, mem) in SERVICES.items():
        s = {
            "rps": _series(rng, rps, 0.06),
            "error_rate": [max(0.0, 0.002 + rng.gauss(0, 0.0008)) for _ in range(WINDOW)],
            "p95_ms": _series(rng, p95, 0.08),
            "cpu": _series(rng, cpu, 0.07) if cpu else [0.0] * WINDOW,
            "memory": _series(rng, mem, 0.02) if mem else [0.0] * WINDOW,
            "restarts": [0.0] * WINDOW,
        }
        if name == "postgres":
            s["connections"] = _series(rng, 34, 0.08)
        m[name] = s
    return m


def _noise_logs(rng: random.Random) -> list[LogTemplate]:
    def flat(rate):
        return [max(0.0, rate * (1 + rng.gauss(0, 0.3))) for _ in range(WINDOW)]

    return [
        LogTemplate("gateway", "INFO", "GET /api/products 200", flat(120)),
        LogTemplate("gateway", "WARN", "slow client: request body read took {ms}ms", flat(0.6)),
        LogTemplate("checkout", "INFO", "order {id} placed", flat(18)),
        LogTemplate("catalog", "INFO", "cache refresh completed in {ms}ms", flat(1)),
        LogTemplate("payments", "INFO", "charge {id} succeeded", flat(16)),
        LogTemplate("inventory", "INFO", "reserved stock for order {id}", flat(20)),
        LogTemplate("cart", "INFO", "cart {id} updated", flat(40)),
        LogTemplate("postgres", "WARN", "checkpoints are occurring too frequently", flat(0.05)),
        LogTemplate("catalog", "WARN", "deprecated field 'legacy_sku' requested by client", flat(0.3)),
    ]


def _propagate_errors(m, upstream: str, downstream_err: list[float], share: float) -> None:
    for i, e in enumerate(downstream_err):
        m[upstream]["error_rate"][i] = min(1.0, m[upstream]["error_rate"][i] + e * share)


def build(fault: str, seed: int) -> Scenario:
    if fault not in FAULTS:
        raise ValueError(f"unknown fault {fault}")
    rng = random.Random(f"{fault}:{seed}")
    m = baseline(rng)
    logs = _noise_logs(rng)
    onset = rng.randint(24, 44)
    r = _ramp(onset)
    changes: list[Change] = []
    traces: list[dict] = []
    notes: list[str] = []

    # red herrings: an unrelated deploy and config tweak on healthy services
    herring = rng.choice(["catalog", "gateway", "inventory"])
    changes.append(
        Change(
            max(2, onset - rng.randint(6, 14)),
            herring,
            "deploy",
            f"{herring} v{rng.randint(2, 4)}.{rng.randint(0, 20)}.{rng.randint(0, 9)}: copy changes, dependency bumps",
            "ci-bot",
        )
    )
    changes.append(Change(rng.randint(1, 10), "catalog", "config", "CACHE_TTL_S: 300 -> 600", "priya"))

    if fault == "bad_deploy":
        target = rng.choice(["checkout", "cart", "catalog"])
        ver = f"v{rng.randint(2, 5)}.{rng.randint(10, 40)}.0"
        changes.append(
            Change(onset, target, "deploy", f"{target} {ver}: new promotion engine, discount rules refactor", "ci-bot")
        )
        err = [0.14 * x + (0.03 * rng.random() if x else 0) for x in r]
        m[target]["error_rate"] = [a + b for a, b in zip(m[target]["error_rate"], err, strict=True)]
        m[target]["p95_ms"] = [p * (1 + 0.4 * x) for p, x in zip(m[target]["p95_ms"], r, strict=True)]
        _propagate_errors(m, "gateway", err, 0.35 if target != "checkout" else 0.2)
        logs.append(
            LogTemplate(
                target,
                "ERROR",
                "NullPointerException at PromotionService.applyDiscount(PromotionService.java:88)",
                [x * m[target]["rps"][i] * 60 * 0.14 / 10 for i, x in enumerate(r)],
            )
        )
        traces = [
            _trace(
                rng,
                "gateway",
                target,
                "POST /api/" + target,
                500,
                f"{target}: NullPointerException in PromotionService.applyDiscount",
            )
            for _ in range(3)
        ]
        root = target
        alert = {
            "service": "gateway",
            "metric": "error_rate",
            "summary": "Gateway 5xx rate above SLO",
            "detail": f"gateway 5xx error rate {100 * m['gateway']['error_rate'][-1]:.1f}% (SLO 1%)",
        }
        remediation = f"Roll back {target} to the previous release; add a regression test for applyDiscount with null promo codes."
        title = "Gateway 5xx errors"

    elif fault == "db_connection_exhaustion":
        root = "inventory"
        ver = f"v3.{rng.randint(2, 9)}.0"
        changes.append(
            Change(onset - 1, "inventory", "deploy", f"inventory {ver}: stock-movement report endpoint", "ci-bot")
        )
        m["postgres"]["connections"] = [c + (100 - c) * x for c, x in zip(m["postgres"]["connections"], r, strict=True)]
        m["inventory"]["p95_ms"] = [
            p + 5200 * x * (0.8 + 0.4 * rng.random()) for p, x in zip(m["inventory"]["p95_ms"], r, strict=True)
        ]
        err = [0.09 * x for x in r]
        m["inventory"]["error_rate"] = [a + b for a, b in zip(m["inventory"]["error_rate"], err, strict=True)]
        m["postgres"]["cpu"] = [c * (1 + 0.5 * x) for c, x in zip(m["postgres"]["cpu"], r, strict=True)]
        _propagate_errors(m, "checkout", err, 0.6)
        m["checkout"]["p95_ms"] = [p + 3000 * x for p, x in zip(m["checkout"]["p95_ms"], r, strict=True)]
        logs.append(
            LogTemplate(
                "inventory",
                "ERROR",
                "HikariPool-1 - Connection is not available, request timed out after 30000ms",
                [6 * x for x in r],
            )
        )
        logs.append(
            LogTemplate(
                "postgres",
                "FATAL",
                "remaining connection slots are reserved for non-replication superuser connections",
                [4 * x for x in r],
            )
        )
        logs.append(
            LogTemplate(
                "postgres",
                "LOG",
                "duration: 41250 ms  statement: SELECT * FROM stock_movements WHERE created_at > $1",
                [2 * x for x in r],
            )
        )
        traces = [
            _trace(
                rng,
                "checkout",
                "inventory",
                "POST /reserve",
                503,
                "inventory: timeout acquiring database connection",
                slow="inventory",
            )
            for _ in range(3)
        ]
        alert = {
            "service": "checkout",
            "metric": "p95_ms",
            "summary": "Checkout latency above SLO",
            "detail": f"checkout p95 latency {m['checkout']['p95_ms'][-1] / 1000:.1f}s (SLO 800ms)",
        }
        remediation = (
            "Roll back inventory to the previous release (the new report query holds connections for 40s+); "
            "kill the long-running queries and add an index on stock_movements.created_at."
        )
        title = "Checkout latency"

    elif fault == "memory_leak":
        root = "cart"
        changes.append(
            Change(
                max(1, onset - rng.randint(18, 24)),
                "cart",
                "deploy",
                "cart v2.8.0: session recommendations cache",
                "ci-bot",
            )
        )
        mem, restarts, period = [], [], rng.randint(7, 10)
        level = m["cart"]["memory"][0]
        for i in range(WINDOW):
            if i >= onset - 12:
                level += 58 / period
                if level >= 99:
                    level = 42
                    restarts.append(1.0)
                else:
                    restarts.append(0.0)
            else:
                restarts.append(0.0)
            mem.append(min(99.5, level))
        m["cart"]["memory"], m["cart"]["restarts"] = mem, restarts
        err = [0.25 if restarts[i] or (i and restarts[i - 1]) else 0.0 for i in range(WINDOW)]
        m["cart"]["error_rate"] = [a + b for a, b in zip(m["cart"]["error_rate"], err, strict=True)]
        m["cart"]["p95_ms"] = [p * (1 + 3 * (mm / 100) ** 6) for p, mm in zip(m["cart"]["p95_ms"], mem, strict=True)]
        _propagate_errors(m, "gateway", err, 0.3)
        logs.append(
            LogTemplate("cart", "ERROR", "java.lang.OutOfMemoryError: Java heap space", [3 * x for x in restarts])
        )
        logs.append(
            LogTemplate("cart", "WARN", "container cart killed: OOMKilled (exit code 137), restarting", restarts)
        )
        logs.append(
            LogTemplate(
                "cart", "WARN", "GC overhead limit exceeded, pause {ms}ms", [1.5 if mm > 85 else 0.0 for mm in mem]
            )
        )
        traces = [
            _trace(rng, "gateway", "cart", "PUT /api/cart", 502, "cart: upstream connection reset (pod restarting)")
            for _ in range(3)
        ]
        alert = {
            "service": "gateway",
            "metric": "error_rate",
            "summary": "Intermittent gateway 502s",
            "detail": "gateway 502 responses spiking every few minutes",
        }
        remediation = (
            "Roll back cart v2.8.0 (the recommendations cache is unbounded); cap the cache size and add a memory alert."
        )
        title = "Intermittent gateway 502s"

    elif fault == "dependency_latency":
        root = "psp"
        m["psp"]["p95_ms"] = [p + 8800 * x for p, x in zip(m["psp"]["p95_ms"], r, strict=True)]
        m["payments"]["p95_ms"] = [p + 4700 * x for p, x in zip(m["payments"]["p95_ms"], r, strict=True)]
        err = [0.32 * x for x in r]
        m["payments"]["error_rate"] = [a + b for a, b in zip(m["payments"]["error_rate"], err, strict=True)]
        _propagate_errors(m, "checkout", err, 0.85)
        m["checkout"]["p95_ms"] = [p + 5000 * x for p, x in zip(m["checkout"]["p95_ms"], r, strict=True)]
        logs.append(
            LogTemplate(
                "payments",
                "ERROR",
                "ReadTimeout: POST https://api.psp.example/v1/charges exceeded 5000ms",
                [9 * x for x in r],
            )
        )
        logs.append(LogTemplate("payments", "WARN", "retrying charge {id} (attempt 2/3)", [7 * x for x in r]))
        traces = [
            _trace(
                rng,
                "checkout",
                "payments",
                "POST /pay",
                504,
                "payments: ReadTimeout calling psp /v1/charges",
                slow="psp",
            )
            for _ in range(3)
        ]
        alert = {
            "service": "checkout",
            "metric": "error_rate",
            "summary": "Checkout failures above SLO",
            "detail": f"checkout error rate {100 * m['checkout']['error_rate'][-1]:.0f}% (SLO 1%)",
        }
        remediation = (
            "The external payment provider is slow: fail over payments to the secondary PSP, open a ticket "
            "with the provider, and tighten the client timeout with a circuit breaker."
        )
        title = "Checkout failures"
        notes.append("No internal deploy explains this; payments' own CPU and memory are normal.")

    elif fault == "certificate_expired":
        root = "payments"
        err = [0.97 * (1.0 if i >= onset else 0.0) for i in range(WINDOW)]
        m["payments"]["error_rate"] = [a + b for a, b in zip(m["payments"]["error_rate"], err, strict=True)]
        m["payments"]["p95_ms"] = [p * (0.3 if i >= onset else 1) for i, p in enumerate(m["payments"]["p95_ms"])]
        m["psp"]["rps"] = [p * (0.02 if i >= onset else 1) for i, p in enumerate(m["psp"]["rps"])]
        _propagate_errors(m, "checkout", err, 0.9)
        logs.append(
            LogTemplate(
                "payments",
                "ERROR",
                "x509: certificate has expired or is not yet valid: current time is after "
                "the certificate's NotAfter (client certificate payments-mtls)",
                [14.0 if i >= onset else 0.0 for i in range(WINDOW)],
            )
        )
        traces = [
            _trace(rng, "checkout", "payments", "POST /pay", 502, "payments: TLS handshake failed: certificate expired")
            for _ in range(3)
        ]
        alert = {
            "service": "checkout",
            "metric": "error_rate",
            "summary": "Checkout failures above SLO",
            "detail": f"checkout error rate {100 * m['checkout']['error_rate'][-1]:.0f}% (SLO 1%)",
        }
        remediation = (
            "Renew and deploy the payments mTLS client certificate; add certificate-expiry monitoring 30 days ahead."
        )
        title = "Checkout failures"
        notes.append("The failure starts on the minute with no deploy or config change at that time.")

    else:  # bad_config
        root = "cart"
        changes.append(Change(onset, "cart", "config", "REDIS_URL: redis-primary:6379 -> redis-primray:6379", "sam"))
        err = [1.0 * (1.0 if i >= onset else 0.0) for i in range(WINDOW)]
        m["cart"]["error_rate"] = [min(1.0, a + b) for a, b in zip(m["cart"]["error_rate"], err, strict=True)]
        m["redis"]["rps"] = [p * (0.1 if i >= onset else 1) for i, p in enumerate(m["redis"]["rps"])]
        _propagate_errors(m, "gateway", err, 0.3)
        _propagate_errors(m, "checkout", err, 0.5)
        logs.append(
            LogTemplate(
                "cart",
                "ERROR",
                "Error: getaddrinfo ENOTFOUND redis-primray",
                [30.0 if i >= onset else 0.0 for i in range(WINDOW)],
            )
        )
        traces = [
            _trace(rng, "gateway", "cart", "GET /api/cart", 500, "cart: getaddrinfo ENOTFOUND redis-primray")
            for _ in range(3)
        ]
        alert = {
            "service": "cart",
            "metric": "error_rate",
            "summary": "Cart error rate critical",
            "detail": "cart error rate 100% (SLO 1%)",
        }
        remediation = (
            "Revert the cart REDIS_URL change (typo: redis-primray); add config validation to the deploy pipeline."
        )
        title = "Cart errors"

    changes.sort(key=lambda c: c.minute)
    severity = "critical" if max(m[alert["service"]]["error_rate"][-5:]) > 0.2 else "high"
    return Scenario(
        id=f"{fault}-{seed}",
        fault=fault,
        seed=seed,
        root_service=root,
        onset=onset,
        alert=alert,
        metrics=m,
        logs=logs,
        changes=changes,
        traces=traces,
        remediation=remediation,
        title=title,
        severity=severity,
        notes=notes,
    )


def _trace(
    rng: random.Random, entry: str, failing: str, op: str, status: int, error: str, slow: str | None = None
) -> dict:
    tid = f"{rng.getrandbits(64):016x}"
    spans = [{"service": entry, "operation": op, "duration_ms": 0, "status": status}]
    chain = [entry]
    if entry != failing and failing not in SERVICES[entry][1]:
        mid = next(s for s in SERVICES[entry][1] if failing in SERVICES[s][1])
        chain.append(mid)
    chain.append(failing)
    if slow and slow not in chain:
        chain.append(slow)
    for s in chain[1:]:
        dur = rng.randint(4800, 9500) if s == slow or (slow and s == chain[-2]) else rng.randint(3, 40)
        spans.append(
            {
                "service": s,
                "operation": "call",
                "duration_ms": dur,
                "status": status if s == failing else (504 if s == slow else 200),
            }
        )
    next(sp for sp in spans if sp["service"] == failing)["error"] = error
    spans[0]["duration_ms"] = sum(sp["duration_ms"] for sp in spans[1:]) + rng.randint(2, 12)
    return {"trace_id": tid, "spans": spans}


def scenario_ids(seeds: range = range(1, 6)) -> list[str]:
    return [f"{f}-{s}" for f in FAULTS for s in seeds]


def load(scenario_id: str) -> Scenario:
    fault, _, seed = scenario_id.rpartition("-")
    return build(fault, int(seed))


def summarize_series(values: list[float], metric: str) -> dict:
    """Compact view for the agent: baseline vs now, onset estimate and a coarse sparkline."""
    base = values[:20]
    mean = sum(base) / len(base)
    sd = math.sqrt(sum((v - mean) ** 2 for v in base) / len(base)) or max(1e-9, abs(mean) * 0.05)
    onset = next(
        (
            i
            for i in range(20, WINDOW)
            if abs(values[i] - mean) > 4 * sd and abs(values[i] - mean) > 0.15 * abs(mean) + 1e-9
        ),
        None,
    )
    now = sum(values[-5:]) / 5
    fmt = (lambda v: round(v * 100, 2)) if metric == "error_rate" else (lambda v: round(v, 1))
    return {
        "unit": "%"
        if metric == "error_rate"
        else {
            "p95_ms": "ms",
            "rps": "req/s",
            "cpu": "%",
            "memory": "%",
            "restarts": "per min",
            "connections": "of 100",
        }.get(metric, ""),
        "baseline": fmt(mean),
        "now": fmt(now),
        "max": fmt(max(values)),
        "changed_minutes_ago": (WINDOW - 1 - onset) if onset is not None else None,
        "every_5_min": [fmt(sum(values[i : i + 5]) / 5) for i in range(0, WINDOW, 5)],
    }
