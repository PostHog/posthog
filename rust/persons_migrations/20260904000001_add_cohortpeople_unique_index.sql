-- Enforce one row per (cohort_id, person_id) in posthog_cohortpeople.
--
-- The table only had plain btrees, so nothing stopped a second row for the same
-- pair. Duplicates inflate count_cohort_members, a plain COUNT(*), so the cohort
-- size a user reads is too large. The unique index also covers the composite
-- lookups posthog_coh_cohort__89c25f_idx serves today; that index is now
-- redundant, and can go out-of-band with DROP INDEX CONCURRENTLY.
--
-- The DELETE removes rows that duplicate a surviving row. It keeps the highest
-- version for each pair, because the async cohort sweep removes members below a
-- cohort's current version. The merge paths made these rows, and they now drop a
-- colliding row instead of moving it, so this cleanup runs once.
--
-- LOCKING: a plain CREATE INDEX takes a SHARE lock that blocks writes for the
-- build, and the migration runner wraps each file in a transaction, so
-- CONCURRENTLY cannot be used here. On the large production posthog_cohortpeople,
-- do both steps out-of-band FIRST: delete the duplicates in bounded batches, then
-- CREATE UNIQUE INDEX CONCURRENTLY. The guard below then makes this migration a
-- no-op there, and skips the table scan the DELETE would otherwise cost. A
-- concurrent build that fails leaves an invalid index that must be dropped with
-- DROP INDEX CONCURRENTLY, because the guard below refuses it. On fresh or small
-- databases (dev, CI, hobby) both steps are cheap inline. Idempotent and safe to
-- re-run.
--
-- ORDER: the out-of-band build needs the new merge statements in place first. An
-- older merge writer repoints a source membership blind, so the index turns a
-- cohort the target already holds into a 23505 error. That error aborts the
-- merge, and it repeats on each retry because the colliding row stays. Deploy
-- the collision-safe statements to both merge writers, move_cohort_membership in
-- personhog-identity and updateCohortsAndFeatureFlagsForMerge in the Node person
-- repository, and then build the index. The bulk insert needs no ordering,
-- because its untargeted ON CONFLICT DO NOTHING starts to skip duplicates as
-- soon as the index exists.

DO $$
DECLARE
    existing oid := to_regclass('posthog_cohortpeople_cohort_id_person_id_uniq');
    enforced boolean;
BEGIN
    -- A failed CREATE UNIQUE INDEX CONCURRENTLY leaves an index behind that
    -- to_regclass finds but that enforces nothing, because Postgres marks it
    -- invalid and not ready. Read the catalog instead of trusting the name, so
    -- that state stops the migration rather than passing as done.
    IF existing IS NOT NULL THEN
        SELECT i.indisunique AND i.indisvalid AND i.indisready AND i.indpred IS NULL
               AND (SELECT array_agg(a.attname::text ORDER BY k.ord)
                    FROM unnest(i.indkey::int2[]) WITH ORDINALITY AS k(attnum, ord)
                    JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum)
                   = ARRAY['cohort_id', 'person_id']
        INTO enforced
        FROM pg_index i
        WHERE i.indexrelid = existing
          AND i.indrelid = 'posthog_cohortpeople'::regclass;

        IF enforced THEN
            RETURN;
        END IF;

        RAISE EXCEPTION 'posthog_cohortpeople_cohort_id_person_id_uniq exists but does not enforce one row per (cohort_id, person_id)'
            USING HINT = 'A failed CREATE UNIQUE INDEX CONCURRENTLY leaves an index in this state. Remove it with DROP INDEX CONCURRENTLY, delete the duplicate rows, then build the index again.';
    END IF;

    DELETE FROM posthog_cohortpeople cp
    WHERE EXISTS (
        SELECT 1 FROM posthog_cohortpeople other
        WHERE other.cohort_id = cp.cohort_id
          AND other.person_id = cp.person_id
          AND (COALESCE(other.version, -1), other.id) > (COALESCE(cp.version, -1), cp.id)
    );

    CREATE UNIQUE INDEX posthog_cohortpeople_cohort_id_person_id_uniq
        ON posthog_cohortpeople (cohort_id, person_id);
END $$;
