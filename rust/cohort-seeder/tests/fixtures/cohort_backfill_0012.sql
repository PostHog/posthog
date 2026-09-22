-- Snapshot pinned to
-- products/cohorts/backend/migrations/0012_cohortbackfillchunk_next_attempt_at_and_more.py, the last
-- migration that changed this DDL. 0010 alters only `marker_watch`'s help_text, which emits no SQL,
-- and 0011 touches posthog_cohort columns this projection does not carry.
-- External Team/Cohort foreign keys are omitted so the contract test stays schema-local.
--
-- Nothing enforces this snapshot against Django. No test diffs it with `sqlmigrate`, and the
-- filename appears at one call site, so a later migration that changes these tables and forgets
-- this file passes CI and diverges from production. Re-derive it by hand when you touch the
-- `cohort_backfill_*` DDL: `python manage.py sqlmigrate cohorts <number>` prints the statements the
-- migration emits (CI runs the same command to post migration SQL on a PR). Fold them in, drop the
-- external Team/Cohort foreign key lines to keep the projection schema-local, and rename this file
-- and its `include_str!` to the new number.

CREATE TABLE cohort_backfill_runs (
    id uuid PRIMARY KEY,
    created_by_id bigint,
    backfill_kind varchar(32) NOT NULL DEFAULT 'behavioral',
    trigger_kind varchar(32) NOT NULL,
    scope varchar(16) NOT NULL,
    status varchar(32) NOT NULL DEFAULT 'awaiting_boundary',
    timezone varchar(240) NOT NULL,
    boundary_at timestamptz,
    person_scan_since timestamptz,
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
    team_id integer NOT NULL,
    -- 0006 completion columns.
    chunks_planned_at timestamptz,
    reconcile_dispatched_at timestamptz,
    reconcile_observed_at timestamptz,
    marker_watch jsonb
);

CREATE INDEX cohort_bfr_team_status_idx ON cohort_backfill_runs(team_id, status);
CREATE INDEX cohort_bfr_team_created_idx ON cohort_backfill_runs(team_id, created_at DESC);
CREATE INDEX cohort_bfr_reconciling_idx
    ON cohort_backfill_runs(backfill_kind, reconcile_observed_at)
    WHERE status = 'reconciling';
CREATE UNIQUE INDEX cohort_bfr_active_cohort_kind_uq
    ON cohort_backfill_runs(cohort_id, backfill_kind)
    WHERE cohort_id IS NOT NULL
      AND status IN ('awaiting_boundary', 'blocked', 'seeding', 'reconciling');
CREATE UNIQUE INDEX cohort_bfr_active_team_kind_uq
    ON cohort_backfill_runs(team_id, backfill_kind)
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
    person_range_lo uuid,
    person_range_hi uuid,
    attempts integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz,
    last_error text NOT NULL DEFAULT '',
    tiles_produced bigint NOT NULL DEFAULT 0,
    -- 0012 scan-volume columns. The DEFAULT is the contract `plan_chunks` leans on: it inserts an
    -- explicit column list that names neither, so dropping the default would break planning.
    scan_received_bytes bigint NOT NULL DEFAULT 0,
    scan_decoded_bytes bigint NOT NULL DEFAULT 0,
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
    behavioral_filters_shape_hash varchar(64) NOT NULL DEFAULT '',
    person_filters_shape_hash varchar(64) NOT NULL DEFAULT '',
    pinned_filters jsonb NOT NULL,
    stamped_at timestamptz,
    superseded_at timestamptz,
    error text NOT NULL DEFAULT '',
    cohort_id integer NOT NULL,
    run_id uuid NOT NULL REFERENCES cohort_backfill_runs(id),
    team_id integer NOT NULL,
    -- 0006 completion columns.
    reconcile_completed_at timestamptz,
    reconcile_marker_bits bigint NOT NULL DEFAULT 0,
    CONSTRAINT cohort_bfrc_run_cohort_uq UNIQUE (run_id, cohort_id)
);

-- A minimal projection of posthog_cohort, present only so load_current_behavioral_hashes can read a
-- cohort's current behavioral shape hash when attributing a shortfall. Not part of the cohorts app's
-- backfill migrations.
CREATE TABLE posthog_cohort (
    id integer PRIMARY KEY,
    team_id integer NOT NULL,
    behavioral_filters_shape_hash varchar(64),
    person_filters_shape_hash varchar(64),
    deleted boolean NOT NULL DEFAULT false
);
