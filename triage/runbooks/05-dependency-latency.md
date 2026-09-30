# Slow external dependency

## Symptoms
A service that calls a third-party API (payment provider, SMS, shipping) shows rising p95 latency and timeout errors such as "ReadTimeout ... exceeded 5000ms", plus retries. Its own CPU and memory are normal and there is no recent deploy. Upstream callers see failures on the flows that need the dependency. Traces show the time spent inside the external call.

## Confirm
- The latency is in the span that calls the external host, not in internal work.
- No internal change lines up with the onset.
- The provider's status page or other customers report degradation.

## Mitigate
Fail over to the secondary provider if one exists, or degrade gracefully (queue payments for later capture). Tighten client timeouts and put a circuit breaker around the call so threads are not exhausted. Open a ticket with the provider. Rolling back internal services will not help.
