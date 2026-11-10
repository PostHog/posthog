-- The subscription matcher deletes a watcher when its conversion counts and rewrites person_id on a
-- person merge, and the janitor deletes expired watchers in batches. person_id is indexed, so none of
-- these writes is a HOT update. Vacuum starts at 1000 dead rows plus 2% of the live rows, so a janitor
-- sweep is reclaimed soon after it finishes instead of after a large fraction of the table is dead.
--
-- This is a separate migration from the cyclotron_jobs one because each migration runs in its own
-- transaction. If an anti-wraparound vacuum of this table is running, this ALTER waits for it to
-- finish, because that vacuum does not yield its lock. In a shared transaction, the lock already taken
-- on cyclotron_jobs would stop autovacuum on that table for the whole wait.

ALTER TABLE conversion_watchers SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 1000,
    autovacuum_analyze_scale_factor = 0.02,
    autovacuum_analyze_threshold = 1000
);
