# Error spike after a deploy

## Symptoms
Error rate on one service jumps within a minute or two of a deploy of that same service. Logs show a new exception type (for example NullPointerException, TypeError, KeyError) that did not occur before. Latency may rise slightly. Callers of the service show a proportional increase in errors.

## Confirm
- The deploy time matches the onset (within about two minutes).
- The new errors appear only on the deployed service, and only after the deploy.
- The stack trace points into code touched by the release notes.

## Mitigate
Roll back the service to the previous release. Rollback is faster and safer than a forward fix during an incident. Then reproduce the failing request in staging, add a regression test and redeploy.
