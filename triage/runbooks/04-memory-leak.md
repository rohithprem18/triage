# Memory leak and OOM kills

## Symptoms
Memory for one service grows steadily in a sawtooth: it climbs to the limit, the container is OOM-killed (exit code 137) and restarts, and the cycle repeats every few minutes. Errors and 502s from callers spike at each restart. Logs show "OutOfMemoryError: Java heap space", "GC overhead limit exceeded" or "OOMKilled". Traffic is normal.

## Confirm
- Restart count increases on a schedule and each restart coincides with memory reaching the limit.
- Memory growth started after a deploy that added caching or buffering.

## Mitigate
Roll back the release that introduced the unbounded cache or buffer. Raising the memory limit only lengthens the cycle. Take a heap dump before rolling back if possible, then bound the cache (size or TTL) and add a memory-growth alert.
