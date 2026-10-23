-- Hobby only. The next migration adds a unique (team_id, uuid) index to posthog_person,
-- and a duplicate pair would leave that concurrent build INVALID. Stop first with a clear message.
DO $$
DECLARE
    duplicate_count BIGINT;
BEGIN
    SELECT count(*) INTO duplicate_count
    FROM (
        SELECT 1
        FROM posthog_person
        GROUP BY team_id, uuid
        HAVING count(*) > 1
    ) AS duplicates;

    IF duplicate_count > 0 THEN
        RAISE EXCEPTION 'posthog_person has % duplicate (team_id, uuid) pair(s), so the unique index that person merges need cannot be built', duplicate_count
            USING HINT = 'Find them with: SELECT team_id, uuid, count(*) FROM posthog_person GROUP BY team_id, uuid HAVING count(*) > 1; '
                'keep one row per pair, then re-run the migrations.';
    END IF;
END $$;
