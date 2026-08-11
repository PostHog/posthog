-- Shadow tables for the lifecycle-manager saga state (see
-- 20260727000001_add_lifecycle_op_tables.sql), used to dual-write saga rows
-- against the validation table set. The FK stays inside the tmp namespace so
-- the shadow pair is self-contained: op rows and their per-person claims
-- cascade together without touching the real tables.
--
-- SAFE: creates new empty tables and indexes only; takes no locks on
-- existing tables. This migration is idempotent and safe to re-run.

CREATE TABLE IF NOT EXISTS lifecycle_op_tmp (
    op_id            UUID,
    op_type          TEXT NOT NULL CHECK (op_type IN ('merge', 'delete')),
    team_id          INTEGER NOT NULL,
    step             TEXT NOT NULL,
    attempt          INTEGER NOT NULL DEFAULT 0,
    lease_expires_at TIMESTAMP WITH TIME ZONE,
    request          JSONB NOT NULL,
    outcome          JSONB,
    created_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    completed_at     TIMESTAMP WITH TIME ZONE,
    parked_at        TIMESTAMP WITH TIME ZONE,
    parked_reason    TEXT,
    CONSTRAINT lifecycle_op_tmp_pkey PRIMARY KEY (op_id)
);

-- Sweeper scan: incomplete ops whose lease has expired.
CREATE INDEX IF NOT EXISTS lifecycle_op_tmp_sweep ON lifecycle_op_tmp (lease_expires_at)
    WHERE completed_at IS NULL;

-- Garbage collection: completed ops past retention.
CREATE INDEX IF NOT EXISTS lifecycle_op_tmp_gc ON lifecycle_op_tmp (completed_at)
    WHERE completed_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS lifecycle_op_person_tmp (
    op_id       UUID NOT NULL,
    team_id     INTEGER NOT NULL,
    person_id   BIGINT NOT NULL,
    person_uuid UUID NOT NULL,
    role        TEXT NOT NULL,
    ordinal     INTEGER,
    status      TEXT NOT NULL,
    sealed      JSONB,
    moved       JSONB,
    CONSTRAINT lifecycle_op_person_tmp_pkey PRIMARY KEY (op_id, person_id),
    CONSTRAINT lifecycle_op_person_tmp_op_id_fkey
        FOREIGN KEY (op_id) REFERENCES lifecycle_op_tmp (op_id) ON DELETE CASCADE
);

-- The mark: at most one live op may claim a person.
-- Inserting a row is marking; a unique violation IS the conflict.
CREATE UNIQUE INDEX IF NOT EXISTS lifecycle_op_person_tmp_mark
    ON lifecycle_op_person_tmp (team_id, person_id)
    WHERE status IN ('marked', 'sealed');
