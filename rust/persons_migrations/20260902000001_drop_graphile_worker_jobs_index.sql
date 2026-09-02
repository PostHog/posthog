-- Drop a dead index left behind by the plugin server's old Postgres job queue.
--
-- That queue owned the `graphile_worker` schema, removed in #32758. Nothing in this
-- repository reads or writes it, but the schema rides along on persons databases that
-- descend from the old main application database, so pganalyze keeps filing "unused
-- index" notices for this index.
--
-- SAFE: plain DROP INDEX, not CONCURRENTLY, because both runners wrap each file in a
-- transaction and Postgres rejects DROP INDEX CONCURRENTLY there. The ACCESS EXCLUSIVE
-- lock is harmless: it covers only graphile_worker.jobs, a table with no reader or
-- writer, and the drop is a catalog change. IF EXISTS makes this a no-op where the
-- schema is absent, and safe to re-run.

DROP INDEX IF EXISTS graphile_worker.jobs_priority_run_at_id_locked_at_without_failures_idx;
