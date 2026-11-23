-- Table age grows with the cluster-wide transaction counter, so the
-- posthog_person partitions that were last frozen together also cross
-- autovacuum_freeze_max_age together. With the default scale factors, the
-- large partitions rarely get a regular vacuum, so each forced vacuum
-- freezes all the unfrozen pages of its partition in one pass. Forced
-- vacuums do not yield to other sessions, and many of them at once saturate
-- the persons database.
--
-- These options start a vacuum on a partition once its dead tuples, or the
-- rows inserted since its last vacuum, exceed 10000 plus 0.1% of its rows.
-- Each of these vacuums freezes the rows older than 5M transactions on the
-- pages it scans, so fewer unfrozen pages are left for the aggressive vacuum
-- at vacuum_freeze_table_age. Because regular vacuums run often, that
-- aggressive vacuum starts before autovacuum_freeze_max_age, as a regular
-- autovacuum that yields to lock waiters:
-- https://www.postgresql.org/docs/15/routine-vacuuming.html#VACUUM-FOR-WRAPAROUND
--
-- RESET removes analyze options that were set outside the migrations, so
-- that ANALYZE runs at the cluster defaults in every environment.
--
-- ALTER TABLE ... SET for autovacuum options takes a SHARE UPDATE EXCLUSIVE
-- lock on the partition, which does not block reads or writes. A regular
-- autovacuum on the partition is cancelled after deadlock_timeout, but an
-- anti-wraparound vacuum or a manual VACUUM never yields. The loop alters
-- only the partitions whose options differ, so an environment that already
-- has these values takes no locks on the partitions. Elsewhere, lock_timeout
-- bounds the wait; on timeout the per-file transaction aborts and the next
-- migration run retries this idempotent file.

SET LOCAL lock_timeout = '2s';

DO $$
DECLARE
    wanted CONSTANT text[] := ARRAY[
        'autovacuum_vacuum_scale_factor=0.001',
        'autovacuum_vacuum_threshold=10000',
        'autovacuum_vacuum_insert_scale_factor=0.001',
        'autovacuum_vacuum_insert_threshold=10000',
        'autovacuum_freeze_min_age=5000000'
    ];
    part regclass;
BEGIN
    FOR part IN
        SELECT c.oid::regclass
        FROM pg_inherits i
        JOIN pg_class c ON c.oid = i.inhrelid
        WHERE i.inhparent = 'posthog_person'::regclass
          AND (
              NOT coalesce(c.reloptions, '{}') @> wanted
              OR EXISTS (
                  SELECT 1
                  FROM unnest(c.reloptions) AS opt
                  WHERE starts_with(opt, 'autovacuum_analyze_')
              )
          )
    LOOP
        EXECUTE format(
            'ALTER TABLE %s RESET (autovacuum_analyze_scale_factor, autovacuum_analyze_threshold), SET (%s)',
            part,
            array_to_string(wanted, ', ')
        );
    END LOOP;
END $$;
