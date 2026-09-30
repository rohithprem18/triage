# Failures after a configuration change

## Symptoms
A service starts failing immediately after a config or environment-variable change, with connection errors that name a host or setting: "getaddrinfo ENOTFOUND <host>", "connection refused", "unknown database", "invalid credentials". The dependency itself is healthy but receives far less traffic, because the service can no longer reach it. No code was deployed.

## Confirm
- The change log shows a config edit on the failing service at the onset minute.
- The value in the error message matches the new configuration (look for typos in host names, ports and secrets).

## Mitigate
Revert the configuration change. Then add validation to the config pipeline (resolve hosts, check required keys) so a bad value cannot ship.
