-- A duplicate pair would fail the next migration's concurrent build and leave its index INVALID.
DO $$
DECLARE
    duplicate_pairs BIGINT;
BEGIN
    SELECT count(*) INTO duplicate_pairs
    FROM (
        SELECT 1
        FROM posthog_person
        GROUP BY team_id, uuid
        HAVING count(*) > 1
    ) AS duplicates;

    IF duplicate_pairs > 0 THEN
        RAISE EXCEPTION 'posthog_person has % duplicate (team_id, uuid) pairs. Remove the duplicates, then re-run the migrations; the unique (team_id, uuid) index cannot be built until they are gone.', duplicate_pairs;
    END IF;
END $$;
