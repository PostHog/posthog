-- Coordination state for mark-and-sweep deletion of stale `cohort_membership` rows.
--
-- A reconcile run replays a cohort's full current membership tagged `origin=reconcile` and then
-- emits one completion marker per processor partition. Once every partition's marker has arrived
-- AND the membership consumer has passed the snapshot those markers certify, the cohort's rows
-- older than the run can be deleted: the run just re-asserted everything that is still true.
CREATE TABLE IF NOT EXISTS cohort_membership_sweeps (
    run_id UUID NOT NULL,
    cohort_id BIGINT NOT NULL,
    team_id BIGINT NOT NULL,
    -- i64 bitmap of the partitions whose completion marker has arrived, same convention as the
    -- seeder's `reconcile_marker_bits`: all 64 bits set reads as -1. Bit union is monotone, so
    -- marker redelivery is a no-op.
    marker_bits BIGINT NOT NULL DEFAULT 0,
    min_marker_version TIMESTAMP,
    min_snapshot_version TIMESTAMP,
    -- Observability only. Double-counts on replay, so it must never gate a sweep.
    snapshot_rows BIGINT NOT NULL DEFAULT 0,
    -- Membership-topic high watermarks at the moment the marker set completed, per partition.
    membership_hwms JSONB,
    status TEXT NOT NULL DEFAULT 'collecting',
    claimed_at TIMESTAMP,
    swept_rows BIGINT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, cohort_id),
    CONSTRAINT cohort_membership_sweeps_status_check
        CHECK (status IN ('collecting', 'ready', 'sweeping', 'swept', 'abandoned'))
);

-- Every pod scans for claimable runs on each sweep tick.
CREATE INDEX IF NOT EXISTS idx_cohort_membership_sweeps_status
    ON cohort_membership_sweeps (status, created_at);

-- The sweep pages through one cohort's rows below a version. The unique constraint on
-- (team_id, cohort_id, person_id) can only prefix-match the cohort, leaving the version filter to
-- discard most of what it reads; carrying version in the index lets each page stop early.
CREATE INDEX IF NOT EXISTS idx_cohort_membership_sweep
    ON cohort_membership (team_id, cohort_id, version);

-- How far the membership consumer group has actually applied each partition, aggregated across
-- pods. A sweep waits until this passes the high watermarks its run captured, so it can never
-- delete rows whose re-asserting snapshot messages are still in flight.
CREATE TABLE IF NOT EXISTS cohort_membership_consumer_progress (
    partition INT PRIMARY KEY,
    -- The next offset to consume, not the last consumed one: Kafka's own committed-offset
    -- convention, which makes the comparison against a high watermark exact.
    next_offset BIGINT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
