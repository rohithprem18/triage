# Disk full on the database host

## Symptoms
PostgreSQL starts failing writes all at once while reads keep working: "SQLSTATE 53200: could not write block N of relation base/.../...: No space left on device", "could not write to file ...: No space left on device", "checkpoint starting too late" warnings, and application-level 500s on INSERT/UPDATE/DELETE. The `disk_pct` metric on postgres ramps to 100% over several minutes and stays there. There is no deploy or config change on the database at the onset time.

## Confirm
- `get_metrics` postgres `disk_pct`: a ramp to 100% starting at the onset, flat before it.
- The error logs on postgres contain "No space left on device"; application services that write (catalog, inventory) show 500s in their traces, reads are unaffected.
- The growth is usually WAL segments, bloat from missing vacuuming, or a runaway table/log — check which files fill the volume.

## Mitigate
Free space now (archive or delete old WAL segments, run VACUUM FULL on bloated tables, move logs off the data volume) and extend the volume so it does not refill within minutes. Afterwards, alert on disk usage at 80% and on WAL directory growth, and put logs on a separate volume.
