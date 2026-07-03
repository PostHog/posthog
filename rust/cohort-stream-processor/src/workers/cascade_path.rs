//! The cascade re-evaluation handler.
//!
//! [`handle_cascade`] re-evaluates every cohort that references the flipped cohort
//! ([`TeamFilters::cohorts_referencing`]), emits each referrer's flip to `cohort_membership_changed`,
//! and continues the chain to `cohort_cascade_events`, depth- and cycle-bounded by [`should_emit`].
//! `cohort_cascade_events` is co-partitioned with `cohort_stream_events` so the worker that owns
//! the person's `cf_stage2` always handles it.
//!
//! **Produce-before-state.** A referrer's new `cf_stage2` bit is committed only after both produces
//! ack; a failure holds without writing, so replay re-detects the still-old bit and re-emits (the
//! downstream UPSERT is idempotent). The cascade input is a fixed message that recomputes the same
//! flip on replay — unlike Stage 2 composition, which dedupes by `cf_stage1`'s applied-offset and
//! writes state-before-produce (at-most-once).

use std::sync::Arc;

use chrono::NaiveDateTime;
use metrics::{counter, gauge, histogram};
use tracing::{debug, warn};
use uuid::Uuid;

use crate::cascade::{should_emit, CascadeDecision, CascadeMessage, DropReason};
use crate::filters::manager::CatalogHandle;
use crate::filters::reverse_index::TeamFilters;
use crate::filters::{CohortId, TeamId};
use crate::observability::metrics::{
    CASCADE_CYCLE_DETECTED_RUNTIME_TOTAL, CASCADE_DEPTH_EXCEEDED_TOTAL, CASCADE_DEPTH_OBSERVED,
    CASCADE_FANOUT_CAPPED_TOTAL, CASCADE_HELD_OFFSET_GAUGE, COHORT_STREAM_OFFSET_AHEAD_OF_DISPATCH,
};
use crate::partitions::offset_tracker::{MarkOutcome, OffsetTracker};
use crate::producer::{CohortMembershipChange, MembershipSink};
use crate::stage2::state::Stage2State;
use crate::store::{Stage2Key, StagedBatch, StoreHandle};
use crate::workers::merge_path::MergeWorkerDeps;
use crate::workers::stage2_path::recompute_and_diff;
use crate::workers::worker::{produce_cascades, produce_membership};

/// Re-evaluate every referrer of the flipped cohort carried by one `cohort_cascade_events` message,
/// emit their flips, continue the chain, and settle the cascade offset.
#[allow(clippy::too_many_arguments)]
pub(crate) async fn handle_cascade(
    partition_id: u16,
    handle: &StoreHandle,
    catalog: &CatalogHandle,
    sink: &Arc<dyn MembershipSink>,
    merge: &MergeWorkerDeps,
    last_updated: &str,
    message: &CascadeMessage,
    offset: i64,
) {
    // A config flip can leave a cascade queued after the gate closed; drain it rather than wedge.
    if !merge.cascade.enabled {
        mark_processed(&merge.cascade_tracker, partition_id, offset);
        return;
    }

    histogram!(CASCADE_DEPTH_OBSERVED).record(f64::from(message.depth));

    let snapshot = catalog.load();
    let Some(filters) = snapshot.team(TeamId(message.change.team_id)) else {
        mark_processed(&merge.cascade_tracker, partition_id, offset);
        return;
    };
    let filters: &TeamFilters = filters;

    let Ok(person_id) = Uuid::parse_str(&message.change.person_id) else {
        mark_processed(&merge.cascade_tracker, partition_id, offset);
        return;
    };

    let flipped = CohortId(message.change.cohort_id);
    let referrers = filters.cohorts_referencing(flipped);
    if referrers.is_empty() {
        mark_processed(&merge.cascade_tracker, partition_id, offset);
        return;
    }

    // The capped remainder is recovered only when each dropped referrer is re-evaluated on its next
    // event; the sweep does not re-evaluate cohort-ref shapes with no behavioral leaf.
    let referrers: &[CohortId] = if referrers.len() > merge.cascade.fanout_cap {
        let dropped = (referrers.len() - merge.cascade.fanout_cap) as u64;
        counter!(CASCADE_FANOUT_CAPPED_TOTAL).increment(dropped);
        debug!(
            upstream_cohort_id = message.change.cohort_id,
            dropped, "cascade fan-out capped",
        );
        &referrers[..merge.cascade.fanout_cap]
    } else {
        referrers
    };

    let evaluated_at_ms = clickhouse_millis(last_updated);
    let mut writes: Vec<(Stage2Key, Stage2State)> = Vec::new();
    let mut changes: Vec<CohortMembershipChange> = Vec::new();
    let mut outgoing: Vec<CascadeMessage> = Vec::new();
    for &referrer in referrers {
        // The reverse index includes excluded referrers (cycle members, unresolved refs); only
        // re-evaluate cohorts maintained in `cf_stage2`, else a cycle member would re-enter the chain.
        let composes = filters
            .eligibility
            .get(&referrer)
            .is_some_and(|elig| elig.writes_cf_stage2());
        if !composes {
            continue;
        }
        let Some(tree) = filters.cohorts.get(&referrer) else {
            continue;
        };
        let diff = match recompute_and_diff(partition_id, person_id, tree, filters, handle).await {
            Ok(diff) => diff,
            Err(error) => {
                warn!(
                    partition_id,
                    team_id = message.change.team_id,
                    referrer = referrer.0,
                    error = %error,
                    "cascade recompute read failed; holding the cascade offset for redelivery",
                );
                hold(&merge.cascade_tracker, partition_id, offset);
                return;
            }
        };
        if !diff.flipped() {
            continue;
        }
        let status = diff.status();
        changes.push(CohortMembershipChange {
            team_id: message.change.team_id,
            cohort_id: referrer.0,
            person_id: message.change.person_id.clone(),
            last_updated: last_updated.to_string(),
            status,
        });
        writes.push((
            diff.stage2_key,
            Stage2State {
                in_cohort: diff.new_bit,
                last_evaluated_at_ms: evaluated_at_ms,
            },
        ));
        // The external flip above is unconditional; only the onward hop is depth/cycle bounded.
        match should_emit(
            message,
            referrer,
            status,
            last_updated,
            merge.cascade.depth_cap,
        ) {
            CascadeDecision::Emit { outgoing: hop } => outgoing.push(hop),
            CascadeDecision::Drop {
                reason: DropReason::DepthExceeded,
            } => {
                counter!(CASCADE_DEPTH_EXCEEDED_TOTAL).increment(1);
                debug!(
                    originating_cohort_id = message.originating_cohort_id,
                    "cascade depth cap reached",
                );
            }
            CascadeDecision::Drop {
                reason: DropReason::CycleDetectedRuntime,
            } => {
                counter!(CASCADE_CYCLE_DETECTED_RUNTIME_TOTAL).increment(1);
                debug!(
                    originating_cohort_id = message.originating_cohort_id,
                    cycle_cohort_id = referrer.0,
                    "cascade cycle detected at runtime",
                );
            }
        }
    }

    if changes.is_empty() {
        mark_processed(&merge.cascade_tracker, partition_id, offset);
        return;
    }

    // Produce-before-state: both legs must ack before the bits commit (see the module doc).
    let membership_errors = produce_membership(sink, changes).await;
    if membership_errors > 0 {
        warn!(
            partition_id,
            errors = membership_errors,
            "cascade membership produce failed; holding the cascade offset for redelivery",
        );
        hold(&merge.cascade_tracker, partition_id, offset);
        return;
    }
    let cascade_errors = produce_cascades(merge, outgoing).await;
    if cascade_errors > 0 {
        warn!(
            partition_id,
            errors = cascade_errors,
            "cascade onward produce failed; holding the cascade offset for redelivery",
        );
        hold(&merge.cascade_tracker, partition_id, offset);
        return;
    }

    let mut staged = StagedBatch::default();
    for (key, state) in &writes {
        staged.put_stage2(key, &state.encode());
    }
    if let Err(error) = handle.commit(staged).await {
        warn!(
            partition_id,
            error = %error,
            "cascade cf_stage2 write failed; holding the cascade offset for redelivery",
        );
        hold(&merge.cascade_tracker, partition_id, offset);
        return;
    }

    mark_processed(&merge.cascade_tracker, partition_id, offset);
}

/// Advance the cascade tracker past `offset`. A mark beyond the dispatch ceiling is capped and counted.
fn mark_processed(tracker: &OffsetTracker, partition_id: u16, offset: i64) {
    if let MarkOutcome::CappedAheadOfDispatch =
        tracker.mark_processed(partition_id as i32, offset + 1)
    {
        counter!(COHORT_STREAM_OFFSET_AHEAD_OF_DISPATCH).increment(1);
        warn!(
            partition_id,
            next_offset = offset + 1,
            "cascade offset mark exceeded the dispatch ceiling and was capped (F1 invariant violation)",
        );
    }
}

/// Pin the cascade commit floor at the failed offset so Kafka redelivers it; emit
/// [`CASCADE_HELD_OFFSET_GAUGE`] so the stall is visible.
fn hold(tracker: &OffsetTracker, partition_id: u16, offset: i64) {
    let floor = tracker.hold(partition_id as i32, offset);
    gauge!(CASCADE_HELD_OFFSET_GAUGE, "partition" => partition_id.to_string()).set(floor as f64);
}

/// Parse a ClickHouse `DateTime64(6)` string into epoch millis, `0` on a miss. Feeds only the
/// write-only `Stage2State::last_evaluated_at_ms`, so a miss costs a diagnostic timestamp, never
/// membership.
fn clickhouse_millis(ts: &str) -> i64 {
    NaiveDateTime::parse_from_str(ts, "%Y-%m-%d %H:%M:%S%.f")
        .map(|naive| naive.and_utc().timestamp_millis())
        .unwrap_or(0)
}

#[cfg(test)]
// Tests seed and assert against `CohortStore` directly, the sanctioned direct-store surface for tests.
#[allow(clippy::disallowed_methods)]
mod tests {
    use super::*;
    use chrono_tz::UTC;
    use serde_json::{json, Value};
    use tempfile::TempDir;

    use crate::cascade::first_cascade;
    use crate::filters::{FilterCatalog, TeamFiltersBuilder};
    use crate::producer::{
        CaptureCascadeSink, CaptureSink, CaptureStreamEventSink, CaptureTransferSink,
        MembershipStatus,
    };
    use crate::stage1::key::LeafStateKey;
    use crate::stage1::state::{AppliedOffsets, Stage1State, StatefulRecord};
    use crate::store::{CohortStore, OffloadConfig, OffloadMode, Stage1Key, StoreConfig};
    use crate::workers::{CascadeConfig, TransferRetryPolicy, DEFAULT_MERGE_GC_SCAN_LIMIT};

    const TEAM: i32 = 7;
    const PARTITION: u16 = 0;
    const HASH: [u8; 16] = *b"0123456789abcdef";
    const PERSON_HASH: [u8; 16] = *b"fedcba9876543210";
    const TS: &str = "2026-06-16 00:00:00.000000";
    const OFFSET: i64 = 5;

    fn temp_store() -> (TempDir, CohortStore) {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();
        (dir, store)
    }

    /// Wraps the store so `handle_cascade` exercises the same blocking-pool transport as production.
    fn handle(store: &CohortStore) -> StoreHandle {
        StoreHandle::new(
            store.clone(),
            OffloadConfig {
                mode: OffloadMode::All,
                event_read_permits: 16,
                maintenance_permits: 6,
            },
        )
    }

    fn behavioral_leaf() -> Value {
        json!({
            "type": "behavioral", "value": "performed_event", "key": "$pageview",
            "time_value": 7, "time_interval": "day",
            "conditionHash": "0123456789abcdef",
            "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
        })
    }

    fn person_leaf() -> Value {
        json!({
            "type": "person", "key": "email", "value": "u@p.com", "operator": "exact",
            "conditionHash": "fedcba9876543210",
            "bytecode": ["_H", 1, 32, "u@p.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
        })
    }

    fn cohort_ref(target: i32) -> Value {
        json!({ "type": "cohort", "value": target, "negation": false })
    }

    fn catalog(cohorts: Vec<(i32, Vec<Value>)>, cascade_enabled: bool) -> Arc<CatalogHandle> {
        let mut builder = TeamFiltersBuilder::default();
        for (id, values) in cohorts {
            let cohort = json!({ "properties": { "type": "AND", "values": values } });
            builder
                .add_cohort(CohortId(id), TeamId(TEAM), &cohort)
                .unwrap();
        }
        let filters = builder.freeze_with(UTC, cascade_enabled);
        Arc::new(CatalogHandle::from_catalog(FilterCatalog::from_teams([(
            TeamId(TEAM),
            filters,
        )])))
    }

    fn behavioral_lsk(catalog: &CatalogHandle) -> LeafStateKey {
        catalog
            .load()
            .team(TeamId(TEAM))
            .unwrap()
            .by_condition_to_lsk[&HASH][0]
    }

    fn person_lsk() -> LeafStateKey {
        LeafStateKey::for_person_property(&PERSON_HASH)
    }

    fn person(n: u128) -> Uuid {
        Uuid::from_u128(n)
    }

    fn write_stage1(store: &CohortStore, lsk: LeafStateKey, who: Uuid, state: Stage1State) {
        let key = Stage1Key {
            partition_id: PARTITION,
            team_id: TEAM as u64,
            leaf_state_key: lsk,
            person_id: who,
        };
        let record = StatefulRecord::new(state, AppliedOffsets::default());
        store
            .write_batch(|b| b.put_stage1(&key, &record.encode()))
            .unwrap();
    }

    fn write_stage2(store: &CohortStore, cohort: u64, who: Uuid, in_cohort: bool) {
        let key = Stage2Key {
            partition_id: PARTITION,
            team_id: TEAM as u64,
            cohort_id: cohort,
            person_id: who,
        };
        store
            .write_batch(|b| {
                b.put_stage2(
                    &key,
                    &Stage2State {
                        in_cohort,
                        last_evaluated_at_ms: 0,
                    }
                    .encode(),
                )
            })
            .unwrap();
    }

    fn read_stage2(store: &CohortStore, cohort: u64, who: Uuid) -> Option<bool> {
        let key = Stage2Key {
            partition_id: PARTITION,
            team_id: TEAM as u64,
            cohort_id: cohort,
            person_id: who,
        };
        store
            .get_stage2(&key)
            .unwrap()
            .map(|bytes| Stage2State::decode(&bytes).unwrap().in_cohort)
    }

    fn behavioral_match() -> Stage1State {
        Stage1State::BehavioralSingle {
            has_match: true,
            last_event_at_ms: 1,
            earliest_eviction_at_ms: i64::MAX,
        }
    }

    fn person_match() -> Stage1State {
        Stage1State::PersonProperty {
            matches: true,
            last_updated_at_ms: 1,
            last_updated_offset: 0,
        }
    }

    /// Worker deps with the cascade gate on, capturing both the membership and cascade sinks.
    fn deps(
        membership: &CaptureSink,
        cascade: &CaptureCascadeSink,
        enabled: bool,
        fanout_cap: usize,
    ) -> (Arc<dyn MembershipSink>, MergeWorkerDeps) {
        let sink: Arc<dyn MembershipSink> = Arc::new(membership.clone());
        let deps = MergeWorkerDeps {
            transfer_sink: Arc::new(CaptureTransferSink::new()),
            stream_event_sink: Arc::new(CaptureStreamEventSink::new()),
            merge_tracker: Arc::new(OffsetTracker::new()),
            transfer_tracker: Arc::new(OffsetTracker::new()),
            retry: TransferRetryPolicy::default(),
            gc_scan_limit: DEFAULT_MERGE_GC_SCAN_LIMIT,
            stage2_orphan_gc_enabled: true,
            cascade_sink: Arc::new(cascade.clone()),
            cascade_tracker: Arc::new(OffsetTracker::new()),
            cascade: CascadeConfig {
                enabled,
                depth_cap: 8,
                fanout_cap,
            },
            partition_count: crate::partitions::partitioner::COHORT_PARTITION_COUNT,
        };
        // The cascade was dispatched this tenure, so its ceiling is raised — mirrors the dispatcher.
        deps.cascade_tracker
            .mark_dispatched(PARTITION as i32, OFFSET + 1);
        (sink, deps)
    }

    fn incoming(flipped: i32, who: Uuid, depth: u8, chain: Vec<i32>) -> CascadeMessage {
        CascadeMessage {
            change: CohortMembershipChange {
                team_id: TEAM,
                cohort_id: flipped,
                person_id: who.to_string(),
                last_updated: TS.to_string(),
                status: MembershipStatus::Entered,
            },
            source_offset: 99,
            depth,
            originating_cohort_id: chain.first().copied().unwrap_or(flipped),
            cascade_chain: chain,
        }
    }

    fn committed(deps: &MergeWorkerDeps) -> Option<i64> {
        deps.cascade_tracker
            .committable_offsets()
            .get(&(PARTITION as i32))
            .copied()
    }

    /// A→B: B = AND(person, ref(A)) flips when A (single behavioral) becomes a member, emitting B's
    /// external Entered and a depth-2 onward cascade `chain=[A, B]`.
    #[tokio::test]
    async fn a_flip_reevaluates_b_emits_membership_and_a_depth_two_cascade() {
        let (_dir, store) = temp_store();
        let catalog = catalog(
            vec![
                (2, vec![behavioral_leaf()]),
                (1, vec![person_leaf(), cohort_ref(2)]),
            ],
            true,
        );
        let alice = person(1);
        write_stage1(&store, behavioral_lsk(&catalog), alice, behavioral_match());
        write_stage1(&store, person_lsk(), alice, person_match());

        let membership = CaptureSink::new();
        let cascade = CaptureCascadeSink::new();
        let (sink, deps) = deps(&membership, &cascade, true, 1000);
        let msg = first_cascade(incoming(2, alice, 1, vec![2]).change, 99);

        handle_cascade(
            PARTITION,
            &handle(&store),
            &catalog,
            &sink,
            &deps,
            TS,
            &msg,
            OFFSET,
        )
        .await;

        let changes = membership.changes();
        assert_eq!(changes.len(), 1, "B's external flip");
        assert_eq!(changes[0].cohort_id, 1);
        assert_eq!(changes[0].status, MembershipStatus::Entered);
        assert_eq!(changes[0].person_id, alice.to_string());

        let onward = cascade.messages();
        assert_eq!(onward.len(), 1, "one onward cascade for B");
        assert_eq!(onward[0].change.cohort_id, 1);
        assert_eq!(onward[0].depth, 2, "depth 1 → 2");
        assert_eq!(onward[0].cascade_chain, vec![2, 1]);
        assert_eq!(onward[0].originating_cohort_id, 2);

        assert_eq!(
            read_stage2(&store, 1, alice),
            Some(true),
            "B's bit committed"
        );
        assert_eq!(committed(&deps), Some(OFFSET + 1), "offset advanced");
    }

    #[tokio::test]
    async fn b_already_at_its_bit_emits_nothing_and_advances() {
        let (_dir, store) = temp_store();
        let catalog = catalog(
            vec![
                (2, vec![behavioral_leaf()]),
                (1, vec![person_leaf(), cohort_ref(2)]),
            ],
            true,
        );
        let alice = person(1);
        write_stage1(&store, behavioral_lsk(&catalog), alice, behavioral_match());
        write_stage1(&store, person_lsk(), alice, person_match());
        write_stage2(&store, 1, alice, true); // B already a member

        let membership = CaptureSink::new();
        let cascade = CaptureCascadeSink::new();
        let (sink, deps) = deps(&membership, &cascade, true, 1000);
        let msg = first_cascade(incoming(2, alice, 1, vec![2]).change, 99);

        handle_cascade(
            PARTITION,
            &handle(&store),
            &catalog,
            &sink,
            &deps,
            TS,
            &msg,
            OFFSET,
        )
        .await;

        assert!(membership.changes().is_empty(), "no flip, no membership");
        assert!(cascade.messages().is_empty(), "no flip, no onward cascade");
        assert_eq!(committed(&deps), Some(OFFSET + 1), "still advances");
    }

    #[tokio::test]
    async fn no_referrers_drains_without_emitting() {
        let (_dir, store) = temp_store();
        // Cohort 2 is single-leaf and referenced by nothing.
        let catalog = catalog(vec![(2, vec![behavioral_leaf()])], true);
        let alice = person(1);
        write_stage1(&store, behavioral_lsk(&catalog), alice, behavioral_match());

        let membership = CaptureSink::new();
        let cascade = CaptureCascadeSink::new();
        let (sink, deps) = deps(&membership, &cascade, true, 1000);
        let msg = first_cascade(incoming(2, alice, 1, vec![2]).change, 99);

        handle_cascade(
            PARTITION,
            &handle(&store),
            &catalog,
            &sink,
            &deps,
            TS,
            &msg,
            OFFSET,
        )
        .await;

        assert!(membership.changes().is_empty());
        assert!(cascade.messages().is_empty());
        assert_eq!(committed(&deps), Some(OFFSET + 1), "no-cross-talk drains");
    }

    #[tokio::test]
    async fn gate_off_drains_without_reevaluating() {
        let (_dir, store) = temp_store();
        let catalog = catalog(
            vec![
                (2, vec![behavioral_leaf()]),
                (1, vec![person_leaf(), cohort_ref(2)]),
            ],
            true,
        );
        let alice = person(1);
        write_stage1(&store, behavioral_lsk(&catalog), alice, behavioral_match());
        write_stage1(&store, person_lsk(), alice, person_match());

        let membership = CaptureSink::new();
        let cascade = CaptureCascadeSink::new();
        let (sink, deps) = deps(&membership, &cascade, false, 1000); // gate OFF
        let msg = first_cascade(incoming(2, alice, 1, vec![2]).change, 99);

        handle_cascade(
            PARTITION,
            &handle(&store),
            &catalog,
            &sink,
            &deps,
            TS,
            &msg,
            OFFSET,
        )
        .await;

        assert!(membership.changes().is_empty(), "gate off: no re-eval");
        assert!(cascade.messages().is_empty());
        assert_eq!(read_stage2(&store, 1, alice), None, "no bit written");
        assert_eq!(committed(&deps), Some(OFFSET + 1), "but the offset drains");
    }

    #[tokio::test]
    async fn depth_cap_drops_the_onward_cascade_but_still_emits_b_membership() {
        let (_dir, store) = temp_store();
        let catalog = catalog(
            vec![
                (2, vec![behavioral_leaf()]),
                (1, vec![person_leaf(), cohort_ref(2)]),
            ],
            true,
        );
        let alice = person(1);
        write_stage1(&store, behavioral_lsk(&catalog), alice, behavioral_match());
        write_stage1(&store, person_lsk(), alice, person_match());

        let membership = CaptureSink::new();
        let cascade = CaptureCascadeSink::new();
        let (sink, deps) = deps(&membership, &cascade, true, 1000);
        // Incoming depth == cap (8): the external flip still emits, the onward cascade drops.
        let msg = incoming(2, alice, 8, vec![2, 90, 91, 92, 93, 94, 95, 96]);

        handle_cascade(
            PARTITION,
            &handle(&store),
            &catalog,
            &sink,
            &deps,
            TS,
            &msg,
            OFFSET,
        )
        .await;

        assert_eq!(
            membership.changes().len(),
            1,
            "B's external flip still emits"
        );
        assert!(
            cascade.messages().is_empty(),
            "depth cap drops the onward hop"
        );
        assert_eq!(
            read_stage2(&store, 1, alice),
            Some(true),
            "B's bit still commits"
        );
        assert_eq!(committed(&deps), Some(OFFSET + 1));
    }

    #[tokio::test]
    async fn runtime_cycle_drops_the_onward_cascade_but_still_emits_b_membership() {
        let (_dir, store) = temp_store();
        let catalog = catalog(
            vec![
                (2, vec![behavioral_leaf()]),
                (1, vec![person_leaf(), cohort_ref(2)]),
            ],
            true,
        );
        let alice = person(1);
        write_stage1(&store, behavioral_lsk(&catalog), alice, behavioral_match());
        write_stage1(&store, person_lsk(), alice, person_match());

        let membership = CaptureSink::new();
        let cascade = CaptureCascadeSink::new();
        let (sink, deps) = deps(&membership, &cascade, true, 1000);
        // B (cohort 1) is already in the chain: the onward hop is a runtime cycle.
        let msg = incoming(2, alice, 2, vec![2, 1]);

        handle_cascade(
            PARTITION,
            &handle(&store),
            &catalog,
            &sink,
            &deps,
            TS,
            &msg,
            OFFSET,
        )
        .await;

        assert_eq!(
            membership.changes().len(),
            1,
            "B's external flip still emits"
        );
        assert!(
            cascade.messages().is_empty(),
            "runtime cycle drops the onward hop"
        );
        assert_eq!(read_stage2(&store, 1, alice), Some(true));
    }

    #[tokio::test]
    async fn fanout_cap_truncates_to_the_first_referrers() {
        let (_dir, store) = temp_store();
        // Cohort 100 (single behavioral) referenced by four cohorts, each sharing one person leaf.
        let catalog = catalog(
            vec![
                (100, vec![behavioral_leaf()]),
                (1, vec![person_leaf(), cohort_ref(100)]),
                (2, vec![person_leaf(), cohort_ref(100)]),
                (3, vec![person_leaf(), cohort_ref(100)]),
                (4, vec![person_leaf(), cohort_ref(100)]),
            ],
            true,
        );
        let alice = person(1);
        write_stage1(&store, behavioral_lsk(&catalog), alice, behavioral_match());
        write_stage1(&store, person_lsk(), alice, person_match());

        let membership = CaptureSink::new();
        let cascade = CaptureCascadeSink::new();
        let (sink, deps) = deps(&membership, &cascade, true, 2); // cap 2 of 4 referrers
        let msg = first_cascade(incoming(100, alice, 1, vec![100]).change, 99);

        handle_cascade(
            PARTITION,
            &handle(&store),
            &catalog,
            &sink,
            &deps,
            TS,
            &msg,
            OFFSET,
        )
        .await;

        let cohorts: Vec<i32> = membership.changes().iter().map(|c| c.cohort_id).collect();
        assert_eq!(
            cohorts,
            vec![1, 2],
            "only the first two (sorted) referrers re-evaluated"
        );
        assert_eq!(
            read_stage2(&store, 3, alice),
            None,
            "the capped remainder self-heals later"
        );
    }

    #[tokio::test]
    async fn replay_of_the_same_cascade_emits_only_once() {
        let (_dir, store) = temp_store();
        let catalog = catalog(
            vec![
                (2, vec![behavioral_leaf()]),
                (1, vec![person_leaf(), cohort_ref(2)]),
            ],
            true,
        );
        let alice = person(1);
        write_stage1(&store, behavioral_lsk(&catalog), alice, behavioral_match());
        write_stage1(&store, person_lsk(), alice, person_match());

        let membership = CaptureSink::new();
        let cascade = CaptureCascadeSink::new();
        let (sink, deps) = deps(&membership, &cascade, true, 1000);
        let msg = first_cascade(incoming(2, alice, 1, vec![2]).change, 99);

        handle_cascade(
            PARTITION,
            &handle(&store),
            &catalog,
            &sink,
            &deps,
            TS,
            &msg,
            OFFSET,
        )
        .await;
        assert_eq!(membership.changes().len(), 1, "first pass emits");

        handle_cascade(
            PARTITION,
            &handle(&store),
            &catalog,
            &sink,
            &deps,
            TS,
            &msg,
            OFFSET,
        )
        .await;
        assert_eq!(
            membership.changes().len(),
            1,
            "replay re-detects no flip (B's bit is now set) and emits nothing",
        );
    }

    #[tokio::test]
    async fn membership_produce_failure_holds_without_writing_state() {
        let (_dir, store) = temp_store();
        let catalog = catalog(
            vec![
                (2, vec![behavioral_leaf()]),
                (1, vec![person_leaf(), cohort_ref(2)]),
            ],
            true,
        );
        let alice = person(1);
        write_stage1(&store, behavioral_lsk(&catalog), alice, behavioral_match());
        write_stage1(&store, person_lsk(), alice, person_match());

        let membership = CaptureSink::failing_first(1);
        let cascade = CaptureCascadeSink::new();
        let (sink, deps) = deps(&membership, &cascade, true, 1000);
        let msg = first_cascade(incoming(2, alice, 1, vec![2]).change, 99);

        handle_cascade(
            PARTITION,
            &handle(&store),
            &catalog,
            &sink,
            &deps,
            TS,
            &msg,
            OFFSET,
        )
        .await;

        assert!(
            membership.changes().is_empty(),
            "the failed produce recorded nothing"
        );
        assert!(
            cascade.messages().is_empty(),
            "no onward cascade after a membership failure"
        );
        assert_eq!(read_stage2(&store, 1, alice), None, "no bit on a held flip");
        assert_eq!(committed(&deps), None, "the offset is held for redelivery");
    }

    /// The membership leg acks but the onward cascade fails, so the bit is not committed and the
    /// offset holds.
    #[tokio::test]
    async fn cascade_produce_failure_holds_without_writing_state() {
        let (_dir, store) = temp_store();
        let catalog = catalog(
            vec![
                (2, vec![behavioral_leaf()]),
                (1, vec![person_leaf(), cohort_ref(2)]),
            ],
            true,
        );
        let alice = person(1);
        write_stage1(&store, behavioral_lsk(&catalog), alice, behavioral_match());
        write_stage1(&store, person_lsk(), alice, person_match());

        let membership = CaptureSink::new();
        let cascade = CaptureCascadeSink::failing_always();
        let (sink, deps) = deps(&membership, &cascade, true, 1000);
        let msg = first_cascade(incoming(2, alice, 1, vec![2]).change, 99);

        handle_cascade(
            PARTITION,
            &handle(&store),
            &catalog,
            &sink,
            &deps,
            TS,
            &msg,
            OFFSET,
        )
        .await;

        assert_eq!(
            membership.changes().len(),
            1,
            "the membership leg already acked"
        );
        assert!(cascade.messages().is_empty(), "the onward cascade failed");
        assert_eq!(
            read_stage2(&store, 1, alice),
            None,
            "produce-before-state: the bit is not committed on a held flip, so replay recovers it",
        );
        assert_eq!(committed(&deps), None, "the offset is held for redelivery");
    }
}
