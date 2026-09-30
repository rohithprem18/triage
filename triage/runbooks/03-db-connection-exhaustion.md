# Database connection pool exhaustion

## Symptoms
A service's p95 latency climbs to seconds and requests time out while its CPU stays moderate. Logs show pool errors such as "HikariPool - Connection is not available, request timed out" or "too many connections". The database reports "remaining connection slots are reserved" and its active connections sit at the maximum. Services that call the affected one see slow responses and timeouts.

## Confirm
- Database active connections are pinned at max_connections.
- Slow-query logs show long-running statements (tens of seconds) that hold connections, often from a new code path.
- Onset follows a deploy of the service that owns those queries.

## Mitigate
Roll back the release that introduced the long-running query, terminate the stuck queries (pg_terminate_backend), then fix the query (missing index, unbounded scan) or move it to a read replica. Do not simply raise max_connections: it hides the leak and can exhaust database memory.
