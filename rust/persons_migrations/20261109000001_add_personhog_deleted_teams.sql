-- Projects whose persons personhog-replica hard-deleted, for the property store
-- writer to erase their SlateDB keys. The replica records a team on the first
-- delete batch and prunes rows older than its retention window, so the table
-- holds only recent deletions.
--
-- SAFE: creates a new empty table only; takes no locks on existing tables.
-- Idempotent and safe to re-run.

CREATE TABLE IF NOT EXISTS personhog_deleted_teams (
    team_id    INTEGER     PRIMARY KEY,
    deleted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
