-- The partition migration dropped the foreign key from
-- posthog_featureflaghashkeyoverride to posthog_person and nothing put it back,
-- so databases built from these migrations kept override rows after a person
-- delete. This restores it in the shape production already has, NOT VALID
-- included. Skipped where a key to posthog_person exists, and where
-- posthog_person is not partitioned (hobby), because its (id) primary key
-- cannot back a composite key. lock_timeout bounds the wait for the partition
-- locks; on timeout the file aborts unrecorded and the next run retries it.
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
