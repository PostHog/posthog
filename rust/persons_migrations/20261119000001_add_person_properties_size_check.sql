-- no-transaction
--
-- Restore the person properties size limit on posthog_person.
--
-- The partitioned table was created with LIKE ... INCLUDING DEFAULTS, which does not copy CHECK
-- constraints, so check_properties_size stayed on posthog_person_old. Node ingestion matches the
-- exact name check_properties_size, and the personhog writer matches a name that contains it.
--
-- The constraint goes on each partition, not on the parent. ADD CONSTRAINT on the parent takes
-- ACCESS EXCLUSIVE on the parent and all 64 partitions in one transaction, and holds every lock
-- until commit. Each wait for the next partition would block all reads and writes to the
-- partitions that are already locked, on the primary and on the replicas that replay the locks.
-- A CHECK on every partition enforces the same limit, because every row is in a partition.
--
-- SAFE: each partition commits in its own transaction, so a partition is locked only for its own
-- brief catalog change. NOT VALID skips the scan of existing rows. lock_timeout bounds each wait,
-- and a timed-out partition is retried after a pause. If the retries run out, the migration
-- fails with no record in _sqlx_migrations, and the next run skips the partitions that are done.
--
-- Hobby keeps posthog_person unpartitioned with the constraint from the initial schema, so the
-- existence check makes this file a no-op there.
--
-- Do not VALIDATE this constraint. Rows written while the table had no limit can exceed it, and
-- VALIDATE fails on the first such row. New inserts and updates are checked without it.

DO $$
DECLARE
    max_attempts CONSTANT int := 10;
    part regclass;
    attempt int;
BEGIN
    FOR part IN
        SELECT c.oid::regclass
        FROM pg_class c
        WHERE c.relkind = 'r'
          AND (c.oid = 'posthog_person'::regclass
               OR c.oid IN (SELECT inhrelid FROM pg_inherits
                            WHERE inhparent = 'posthog_person'::regclass))
          AND NOT EXISTS (
              SELECT 1 FROM pg_constraint con
              WHERE con.conrelid = c.oid AND con.conname = 'check_properties_size'
          )
        ORDER BY c.relname
    LOOP
        attempt := 1;
        LOOP
            BEGIN
                PERFORM set_config('lock_timeout', '1s', true);
                EXECUTE format(
                    'ALTER TABLE %s ADD CONSTRAINT check_properties_size '
                    'CHECK (pg_column_size(properties) <= 655360) NOT VALID',
                    part
                );
                EXIT;
            EXCEPTION WHEN lock_not_available THEN
                IF attempt >= max_attempts THEN
                    RAISE;
                END IF;
                RAISE NOTICE 'lock timeout on %, attempt % of %', part, attempt, max_attempts;
                attempt := attempt + 1;
            END;
            PERFORM pg_sleep(2);
        END LOOP;
        COMMIT;
    END LOOP;
END $$;
