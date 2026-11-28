-- no-transaction
-- One transaction per partition: ADD CONSTRAINT on the parent would hold ACCESS EXCLUSIVE on all partitions at once.
-- Not validated, since existing rows can exceed the limit.

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
