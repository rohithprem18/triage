# General incident triage

## First five minutes
Acknowledge the page and read the alert: which service noticed the problem, which metric, and since when. The alerting service is where the symptom is visible, not necessarily where the fault is. Check the dependency graph: an error at the edge (gateway) or in an orchestrating service (checkout) usually comes from something it calls.

## Narrow down
1. Compare error rate and p95 latency for every service against their baselines. The fault is usually in the deepest service that is unhealthy.
2. Find when the change began and look at the change log (deploys and config edits) for anything within a few minutes before that moment. A change long before the onset, or on a service that is healthy, is probably unrelated.
3. Read the error logs of the suspected service. Exact error messages (exception names, TLS errors, DNS failures, timeouts) usually name the fault class.
4. Sample failing traces to see which span actually fails and which is merely waiting.

## Avoid
Do not blame the most recent deploy by default: confirm the timing and the affected service match. Do not restart everything: restarts destroy evidence and rarely fix the cause.
