-- Make the mark index covering for the leader's fence takeover scan.
--
-- A leader taking partition ownership rebuilds its in-memory fence map from
-- the live marks (status marked/sealed, non-target roles) before the
-- partition accepts writes. INCLUDE (op_id, role) makes that scan an
-- index-only read of a partial index that contains nothing but live marks;
-- uniqueness stays on (team_id, person_id).
--
-- SAFE: the lifecycle tables are new and small (live marks only, bounded by
-- in-flight ops); a transactional drop-and-recreate is instantaneous. The
-- mark uniqueness guarantee is preserved within the single transaction the
-- migration runs in.

DROP INDEX IF EXISTS lifecycle_op_person_mark;
CREATE UNIQUE INDEX IF NOT EXISTS lifecycle_op_person_mark
    ON lifecycle_op_person (team_id, person_id)
    INCLUDE (op_id, role)
    WHERE status IN ('marked', 'sealed');
