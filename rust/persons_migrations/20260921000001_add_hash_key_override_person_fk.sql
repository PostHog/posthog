-- Production carries this foreign key as ON DELETE CASCADE, NOT VALID, under the
-- constraint name below. The partition migration dropped the original
-- single-column key and nothing re-added one, so a database built from these
-- migrations kept override rows after a person delete. Skipped when any foreign
-- key to posthog_person already exists, so a copy of production is left alone.
-- Also skipped when posthog_person is not partitioned: hobby keeps the
-- unpartitioned Django table, whose primary key is (id) alone, and a composite
-- key cannot reference it. The key stays NOT VALID to match production: it
-- still checks new rows and still cascades, and adding it takes no scan.
-- ADD CONSTRAINT locks posthog_person and every partition against writes while
-- it waits, so the wait is bounded; on timeout the per-file transaction aborts,
-- nothing is recorded, and the next migration run retries this idempotent file.
SET LOCAL lock_timeout = '2s';

DO $$
BEGIN
    IF (SELECT relkind FROM pg_class WHERE oid = 'posthog_person'::regclass) = 'p'
       AND NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'posthog_featureflaghashkeyoverride'::regclass
          AND contype = 'f'
          AND confrelid = 'posthog_person'::regclass
    ) THEN
        ALTER TABLE posthog_featureflaghashkeyoverride
            ADD CONSTRAINT posthog_featureflagh_person_id_7e517f7c_fk_posthog_p
            FOREIGN KEY (team_id, person_id) REFERENCES posthog_person (team_id, id)
            ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED NOT VALID;
    END IF;
END
$$;
