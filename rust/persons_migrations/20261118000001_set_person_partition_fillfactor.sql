-- Postgres rejects storage parameters on a partitioned table, so set them on each partition.
-- Hobby keeps posthog_person unpartitioned, so also match the plain table.

SET LOCAL lock_timeout = '2s';

DO $$
DECLARE
    part regclass;
BEGIN
    FOR part IN
        SELECT c.oid::regclass FROM pg_class c
        WHERE c.relkind = 'r'
          AND (c.oid = 'posthog_person'::regclass
               OR c.oid IN (SELECT inhrelid FROM pg_inherits
                            WHERE inhparent = 'posthog_person'::regclass))
    LOOP
        EXECUTE format('ALTER TABLE %s SET (fillfactor = 90)', part);
    END LOOP;
END $$;
