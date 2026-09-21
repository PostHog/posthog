-- Production carries this foreign key with ON DELETE CASCADE. The partition
-- migration dropped the original single-column key and nothing re-added one,
-- so a database built from these migrations kept override rows after a person
-- delete. Skipped when any foreign key to posthog_person already exists, so a
-- copy of production is left alone. Where the key is added, the rows the
-- missing cascade left behind are removed first so the key validates.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'posthog_featureflaghashkeyoverride'::regclass
          AND contype = 'f'
          AND confrelid = 'posthog_person'::regclass
    ) THEN
        DELETE FROM posthog_featureflaghashkeyoverride o
        WHERE NOT EXISTS (
            SELECT 1 FROM posthog_person p
            WHERE p.team_id = o.team_id AND p.id = o.person_id
        );
        ALTER TABLE posthog_featureflaghashkeyoverride
            ADD CONSTRAINT posthog_featureflagh_person_id_7e517f7c_fk_posthog_p
            FOREIGN KEY (team_id, person_id) REFERENCES posthog_person (team_id, id)
            ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED NOT VALID;
        ALTER TABLE posthog_featureflaghashkeyoverride
            VALIDATE CONSTRAINT posthog_featureflagh_person_id_7e517f7c_fk_posthog_p;
    END IF;
END
$$;
