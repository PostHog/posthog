-- Coordination state for mark-and-sweep deletion of stale `cohort_membership` rows.
--
-- A reconcile run emits one `origin=reconcile` row per person holding a `cf_stage2` register row
-- for the cohort, and then emits one completion marker per processor partition. Persons with no
-- register row get nothing, and their `cohort_membership` rows are exactly what the sweep deletes.
-- Once every partition's marker has arrived AND the membership consumer has passed the snapshot
-- those markers certify, the cohort's rows older than the run can be deleted: the run just
-- re-asserted everything that is still true.
CREATE TABLE IF NOT EXISTS cohort_membership_sweeps (
    run_id UUID NOT NULL,
    cohort_id BIGINT NOT NULL,
    team_id BIGINT NOT NULL,
    -- i64 bitmap of the partitions whose completion marker has arrived, same convention as the
    -- seeder's `reconcile_marker_bits`: all 64 bits set reads as -1. Bit union is monotone, so
    -- marker redelivery is a no-op.
    marker_bits BIGINT NOT NULL DEFAULT 0,
    -- The lowest stamp carried by the run's own completion markers. Bounds how far the marker set
    -- proves the run got, which is above the rows it emitted, never below.
    min_marker_version TIMESTAMP,
    -- The lowest stamp carried by the snapshot rows the run emitted. This is the sweep threshold:
    -- rows below it were not re-asserted by the run. `TIMESTAMP`, not `TIMESTAMPTZ`, because both
    -- sort against `cohort_membership.version`, which carries the producer's UTC stamp verbatim.
    min_snapshot_version TIMESTAMP,
    -- Observability only. Double-counts on replay, so it must never gate a sweep.
    snapshot_rows BIGINT NOT NULL DEFAULT 0,
    -- Membership-topic high watermarks at the moment the marker set completed, per partition.
    membership_hwms JSONB,
    -- Where those watermarks were read from. Offsets only mean something against the cluster and
    -- topic that produced them, and both can move under a run: the consumer's brokers change, or
    -- the processor's output topic flips from the shadow name to the real one. Without this the
    -- gate would compare a captured watermark against progress from a different feed and pass
    -- vacuously. Recording the provenance lets the sweep refuse a run it can no longer verify.
    membership_cluster TEXT,
    membership_topic TEXT,
    status TEXT NOT NULL DEFAULT 'collecting',
    -- The wall-clock columns are TIMESTAMPTZ so that they name the same instant on every pod. A
    -- bare TIMESTAMP stores whatever the writing session's TimeZone produced, so two pods that
    -- disagree on that setting would disagree about when a claim lease expired.
    --
    -- ready_at is when the marker set completed and the watermarks were captured. Never rewritten
    -- after, so gate-wait observability survives partial sweeps that bounce the row back to
    -- 'ready'.
    ready_at TIMESTAMPTZ,
    claimed_at TIMESTAMPTZ,
    -- Fences the claiming pod: the heartbeat and the finish update require the token, so a
    -- straggler whose claim timed out cannot overwrite the pod that reclaimed the run.
    claim_token UUID,
    swept_rows BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, cohort_id),
    CONSTRAINT cohort_membership_sweeps_status_check
        CHECK (status IN ('collecting', 'ready', 'sweeping', 'swept', 'abandoned'))
);

-- Every pod scans for claimable runs on each sweep tick.
CREATE INDEX IF NOT EXISTS idx_cohort_membership_sweeps_status
    ON cohort_membership_sweeps (status, created_at);

-- How far the membership consumer group has actually applied each partition, aggregated across
-- pods. A sweep waits until this passes the high watermarks its run captured, so it can never
-- delete rows whose re-asserting snapshot messages are still in flight.
CREATE TABLE IF NOT EXISTS cohort_membership_consumer_progress (
    -- The feed the consumer read the offsets from: broker list plus topic. Offsets only mean
    -- something against the exact feed that produced them. After a cluster move, rows keyed to
    -- the old brokers would report large retained offsets against the new cluster's small
    -- watermarks; after a topic rename on the same brokers, the old topic's offsets would stand
    -- in for the new one's. Either way the gate would pass vacuously. Keying by both makes a
    -- move start from no progress, which can only hold the gate closed, never open it early.
    cluster TEXT NOT NULL,
    topic TEXT NOT NULL,
    partition INT NOT NULL,
    -- The next offset to consume, not the last consumed one: Kafka's own committed-offset
    -- convention, which makes the comparison against a high watermark exact.
    next_offset BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (cluster, topic, partition)
);
