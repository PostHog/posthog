-- Decouple the mark uniqueness constraint from the status column to
-- enable HOT (Heap-Only Tuple) updates for status transitions.
--
-- The existing partial unique index (lifecycle_op_person_mark) predicates
-- on status IN ('marked', 'sealed'), which PostgreSQL counts as indexing
-- the status column, blocking HOT for every status UPDATE.  A new boolean
-- mark_active column carries the same semantics (true while the row is in
-- the mark set, false after settlement) but changes value only twice per
-- row lifetime — INSERT true then complete false — so the intermediate
-- status transitions (marked → sealed, plus the JSONB seal/move writes)
-- no longer trigger index maintenance.
--
-- The old index is kept until all callers migrate to the new predicate.
-- A follow-up migration drops it once both identity and leader are
-- deployed.
--
-- SAFE: ADD COLUMN with a non-volatile DEFAULT is metadata-only in
-- PostgreSQL 11+ (no table rewrite).  The backfill UPDATE touches only
-- rows with active marks (small fraction).  The new index covers only
-- those same rows.

-- Real table ---------------------------------------------------------
ALTER TABLE lifecycle_op_person
    ADD COLUMN IF NOT EXISTS mark_active BOOLEAN NOT NULL DEFAULT false;

UPDATE lifecycle_op_person
   SET mark_active = true
 WHERE status IN ('marked', 'sealed')
   AND mark_active = false;

CREATE UNIQUE INDEX IF NOT EXISTS lifecycle_op_person_mark_active
    ON lifecycle_op_person (team_id, person_id)
    WHERE mark_active = true;

-- Shadow table -------------------------------------------------------
ALTER TABLE lifecycle_op_person_tmp
    ADD COLUMN IF NOT EXISTS mark_active BOOLEAN NOT NULL DEFAULT false;

UPDATE lifecycle_op_person_tmp
   SET mark_active = true
 WHERE status IN ('marked', 'sealed')
   AND mark_active = false;

CREATE UNIQUE INDEX IF NOT EXISTS lifecycle_op_person_tmp_mark_active
    ON lifecycle_op_person_tmp (team_id, person_id)
    WHERE mark_active = true;
