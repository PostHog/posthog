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
-- no-op there, and skips the table scan the DELETE would otherwise cost. On fresh
-- or small databases (dev, CI, hobby) both steps are cheap inline. Idempotent and
-- safe to re-run.

DO $$
BEGIN
    IF to_regclass('posthog_cohortpeople_cohort_id_person_id_uniq') IS NOT NULL THEN
        RETURN;
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
