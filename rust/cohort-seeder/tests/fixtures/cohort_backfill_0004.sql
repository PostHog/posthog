-- Snapshot pinned to products/cohorts/backend/migrations/0004_cohort_backfill_tables.py.
-- External Team/Cohort foreign keys are omitted so the contract test stays schema-local.

CREATE TABLE cohort_backfill_runs (
    id uuid PRIMARY KEY,
    created_by_id bigint,
    backfill_kind varchar(32) NOT NULL DEFAULT 'behavioral',
    trigger_kind varchar(32) NOT NULL,
    scope varchar(16) NOT NULL,
    status varchar(32) NOT NULL DEFAULT 'awaiting_boundary',
    timezone varchar(240) NOT NULL,
    boundary_at timestamptz,
    boundary_established_at timestamptz,
    pinned jsonb NOT NULL DEFAULT '{}'::jsonb,
    preconditions jsonb NOT NULL DEFAULT '{}'::jsonb,
    reconcile_hwms jsonb,
    blocked_reason text NOT NULL DEFAULT '',
    error text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    cohort_id integer,
    superseded_by_id uuid REFERENCES cohort_backfill_runs(id),
    team_id integer NOT NULL
);

CREATE INDEX cohort_bfr_team_status_idx ON cohort_backfill_runs(team_id, status);
CREATE INDEX cohort_bfr_team_created_idx ON cohort_backfill_runs(team_id, created_at DESC);
CREATE UNIQUE INDEX cohort_bfr_active_cohort_uq
    ON cohort_backfill_runs(cohort_id)
    WHERE cohort_id IS NOT NULL
      AND status IN ('awaiting_boundary', 'blocked', 'seeding', 'reconciling');
CREATE UNIQUE INDEX cohort_bfr_active_team_uq
    ON cohort_backfill_runs(team_id)
    WHERE scope = 'team'
      AND status IN ('awaiting_boundary', 'blocked', 'seeding', 'reconciling');

CREATE TABLE cohort_backfill_chunks (
    id uuid PRIMARY KEY,
    day date NOT NULL,
    band smallint NOT NULL DEFAULT 0,
    status varchar(16) NOT NULL DEFAULT 'pending',
    claim_epoch integer NOT NULL DEFAULT 0,
    claimed_by varchar(255) NOT NULL DEFAULT '',
    claimed_at timestamptz,
    lease_expires_at timestamptz,
    s_chunk_at timestamptz,
    attempts integer NOT NULL DEFAULT 0,
    last_error text NOT NULL DEFAULT '',
    tiles_produced bigint NOT NULL DEFAULT 0,
    produce_hwms jsonb,
    confirmed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    team_id integer NOT NULL,
    run_id uuid NOT NULL REFERENCES cohort_backfill_runs(id),
    CONSTRAINT cohort_bfc_run_day_band_uq UNIQUE (run_id, day, band)
);

CREATE INDEX cohort_bfc_run_status_day_idx ON cohort_backfill_chunks(run_id, status, day);

CREATE TABLE cohort_backfill_run_cohorts (
    id uuid PRIMARY KEY,
    filters_shape_hash varchar(64) NOT NULL,
    pinned_filters jsonb NOT NULL,
    stamped_at timestamptz,
    superseded_at timestamptz,
    error text NOT NULL DEFAULT '',
    cohort_id integer NOT NULL,
    run_id uuid NOT NULL REFERENCES cohort_backfill_runs(id),
    team_id integer NOT NULL,
    CONSTRAINT cohort_bfrc_run_cohort_uq UNIQUE (run_id, cohort_id)
);
