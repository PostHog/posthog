//! The cascade re-evaluation handler.
//!
//! [`handle_cascades`] re-evaluates every cohort that references a flipped cohort
//! ([`TeamFilters::cohorts_referencing`]), emits each referrer's flip to `cohort_membership_changed`,
//! and continues the chain to `cohort_cascade_events`, depth- and cycle-bounded by [`should_emit`].
//! `cohort_cascade_events` is co-partitioned with `cohort_stream_events` so the worker that owns
//! the person's `cf_stage2` always handles it.
//!
//! **One group per sub-batch.** The messages of a worker sub-batch share one produce round trip and
//! one `cf_stage2` write batch. A message whose person already has an unwritten bit in the group
//! settles the group first, so the message reads the written bit instead of the stale one. A group
//! that holds [`CASCADE_GROUP_WRITES`] writes also settles before its next message.
//!
//! **Produce-before-state, per message.** A message's new `cf_stage2` bits are committed only after
//! all of its records ack; a message with a failed record holds its own offset without writing, so
//! replay re-detects the still-old bits and re-emits (the downstream UPSERT is idempotent). The rest
//! of its group still commits, because a message reads and writes only its own person's rows. The
//! cascade input is a fixed message that recomputes the same flip on replay — unlike Stage 2
//! composition, which dedupes by `cf_behavioral`'s applied-offset and writes state-before-produce
//! (at-most-once).

use std::collections::HashSet;
use std::sync::Arc;

use chrono::NaiveDateTime;
use futures::future::join_all;
use metrics::{counter, gauge, histogram};
use tracing::{debug, warn};
use uuid::Uuid;

use crate::cascade::{should_emit, CascadeDecision, CascadeMessage, DropReason};
use crate::filters::manager::CatalogHandle;
use crate::filters::reverse_index::TeamFilters;
use crate::filters::{CohortId, FilterCatalog, TeamId};
use crate::observability::metrics::{
    CASCADE_BATCH_MESSAGES, CASCADE_CYCLE_DETECTED_RUNTIME_TOTAL, CASCADE_DEPTH_EXCEEDED_TOTAL,
    CASCADE_DEPTH_OBSERVED, CASCADE_FANOUT_CAPPED_TOTAL, CASCADE_HELD_OFFSET_GAUGE,
    COHORT_STREAM_OFFSET_AHEAD_OF_DISPATCH,
};
use crate::partitions::offset_tracker::{MarkOutcome, OffsetTracker};
use crate::producer::{CohortMembershipChange, LastUpdatedClock, MembershipSink};
use crate::stage2::state::Stage2State;
use crate::store::{ReadLane, Stage2Key, StagedBatch, StoreHandle};
use crate::workers::merge_path::MergeWorkerDeps;
use crate::workers::stage2_path::recompute_and_diff;
use crate::workers::worker::{produce_cascades, produce_membership};

/// The `cf_stage2` writes at which a cascade group settles before it takes another message. One
/// message adds at most `fanout_cap` writes, so this bounds the output a group holds in memory,
/// which the sub-batch length times the fan-out cap would not.
const CASCADE_GROUP_WRITES: usize = 1_000;

/// Re-evaluate every referrer of the cohorts flipped by one worker sub-batch of
/// `cohort_cascade_events` messages, emit their flips, continue the chains, and settle the cascade
/// offsets. `batch` is in offset order.
#[allow(clippy::too_many_arguments)]
#[hotpath::measure]
pub(crate) async fn handle_cascades(
    partition_id: u16,
    handle: &StoreHandle,
    catalog: &CatalogHandle,
    sink: &Arc<dyn MembershipSink>,
    merge: &MergeWorkerDeps,
    clock: &mut LastUpdatedClock,
    batch: Vec<(Box<CascadeMessage>, i64)>,
) {
    let Some(&(_, last)) = batch.last() else {
        return;
    };
    // A config flip can leave cascades queued after the gate closed; drain them rather than wedge.
    if merge.cascade.enabled {
        let snapshot = catalog.load();
        let mut group = CascadeGroup::open(clock);
        for (message, offset) in batch {
            histogram!(CASCADE_DEPTH_OBSERVED).record(f64::from(message.depth));
            let Some((filters, person_id, referrers)) =
                referrers_to_reevaluate(&snapshot, &message, merge.cascade.fanout_cap)
            else {
                continue;
            };
            if group.touched.contains(&person_id) || group.writes >= CASCADE_GROUP_WRITES {
                group.settle(partition_id, handle, sink, merge).await;
                group = CascadeGroup::open(clock);
            }
            group
                .reevaluate(
                    partition_id,
                    handle,
                    filters,
                    merge,
                    &message,
                    offset,
                    person_id,
                    referrers,
                )
                .await;
        }
        group.settle(partition_id, handle, sink, merge).await;
    }
    // A message whose read, produce or write failed is held, and the hold caps this mark.
    mark_processed(&merge.cascade_tracker, partition_id, last);
}

/// The team filters, person and referrers one cascade message re-evaluates. `None` when there is
/// nothing to re-evaluate: an unknown team, an unparseable person, or no referrer.
fn referrers_to_reevaluate<'a>(
    catalog: &'a FilterCatalog,
    message: &CascadeMessage,
    fanout_cap: usize,
) -> Option<(&'a TeamFilters, Uuid, &'a [CohortId])> {
    let filters: &TeamFilters = catalog.team(TeamId(message.change.team_id))?;
    let person_id = Uuid::parse_str(&message.change.person_id).ok()?;
    let referrers = filters.cohorts_referencing(CohortId(message.change.cohort_id));
    if referrers.is_empty() {
        return None;
    }
    // The capped remainder is recovered only when each dropped referrer is re-evaluated on its next
    // event; the sweep does not re-evaluate cohort-ref shapes with no behavioral leaf.
    if referrers.len() > fanout_cap {
        let dropped = (referrers.len() - fanout_cap) as u64;
        counter!(CASCADE_FANOUT_CAPPED_TOTAL).increment(dropped);
        debug!(
            upstream_cohort_id = message.change.cohort_id,
            dropped, "cascade fan-out capped",
        );
        return Some((filters, person_id, &referrers[..fanout_cap]));
    }
    Some((filters, person_id, referrers))
}

/// Cascade messages of one sub-batch whose flips share one produce round trip and whose bits one
/// write batch commits.
struct CascadeGroup {
    /// One stamp for every change in the group. A group holds at most one message per person, so no
    /// two of its changes share a cohort and person.
    last_updated: String,
    evaluated_at_ms: i64,
    /// The persons of `messages`, whose `cf_stage2` writes are not committed yet.
    touched: HashSet<Uuid>,
    /// The `cf_stage2` writes across `messages`.
    writes: usize,
    messages: Vec<Reevaluated>,
}

/// One message's output. Its bits commit only if all of its records ack.
struct Reevaluated {
    offset: i64,
    writes: Vec<(Stage2Key, Stage2State)>,
    changes: Vec<CohortMembershipChange>,
    outgoing: Vec<CascadeMessage>,
}

impl CascadeGroup {
    fn open(clock: &mut LastUpdatedClock) -> Self {
        let last_updated = clock.next();
        Self {
            evaluated_at_ms: clickhouse_millis(&last_updated),
            last_updated,
            touched: HashSet::new(),
            writes: 0,
            messages: Vec::new(),
        }
    }

    /// Recompose each referrer for `person_id` and collect its bit, its flip and its onward hop. The
    /// message joins the group only if it writes a bit, and every flip writes one.
    #[allow(clippy::too_many_arguments)]
    async fn reevaluate(
        &mut self,
        partition_id: u16,
        handle: &StoreHandle,
        filters: &TeamFilters,
        merge: &MergeWorkerDeps,
        message: &CascadeMessage,
        offset: i64,
        person_id: Uuid,
        referrers: &[CohortId],
    ) {
        let mut reevaluated = Reevaluated {
            offset,
            writes: Vec::new(),
            changes: Vec::new(),
            outgoing: Vec::new(),
        };
        for &referrer in referrers {
            // The reverse index includes excluded referrers (cycle members, unresolved refs); only
            // re-evaluate cohorts maintained in `cf_stage2`, else a cycle member would re-enter the
            // chain.
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
            let diff = match recompute_and_diff(
                partition_id,
                person_id,
                tree,
                filters,
                handle,
                ReadLane::Event,
            )
            .await
            {
                Ok(diff) => diff,
                Err(error) => {
                    warn!(
                        partition_id,
                        offset,
                        team_id = message.change.team_id,
                        referrer = referrer.0,
                        error = %error,
                        "cascade recompute read failed; holding the cascade offset for redelivery",
                    );
                    hold(&merge.cascade_tracker, partition_id, offset);
                    return;
                }
            };
            if diff.requires_write() {
                reevaluated.writes.push((
                    diff.stage2_key,
                    Stage2State {
                        in_cohort: diff.new_bit,
                        last_evaluated_at_ms: self.evaluated_at_ms,
                    },
                ));
            }
            if !diff.flipped() {
                continue;
            }
            let status = diff.status();
            reevaluated.changes.push(CohortMembershipChange {
                team_id: message.change.team_id,
                cohort_id: referrer.0,
                person_id: message.change.person_id.clone(),
                last_updated: self.last_updated.clone(),
                status,
                origin: message.change.origin,
                run_id: None,
            });
            // The external flip above is unconditional; only the onward hop is depth/cycle bounded.
            match should_emit(
                message,
                referrer,
                status,
                &self.last_updated,
                merge.cascade.depth_cap,
            ) {
                CascadeDecision::Emit { outgoing: hop } => reevaluated.outgoing.push(hop),
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
        if !reevaluated.writes.is_empty() {
            self.touched.insert(person_id);
            self.writes += reevaluated.writes.len();
            self.messages.push(reevaluated);
        }
    }

    /// Produce the group's flips and onward hops, then commit the bits of every message whose records
    /// all acked. A message with a failed record holds its own offset.
    async fn settle(
        self,
        partition_id: u16,
        handle: &StoreHandle,
        sink: &Arc<dyn MembershipSink>,
        merge: &MergeWorkerDeps,
    ) {
        let Some(first) = self.messages.first().map(|message| message.offset) else {
            return;
        };
        histogram!(CASCADE_BATCH_MESSAGES).record(self.messages.len() as f64);
        // One produce per message and topic, so each message learns whether its own records acked.
        // Every produce is in flight at once, so the group still costs one round trip.
        let produced = join_all(self.messages.into_iter().map(|message| async move {
            // Produce-before-state: both legs must ack before the message's bits commit (see the
            // module doc).
            let (membership_errors, cascade_errors) = tokio::join!(
                produce_membership(sink, message.changes),
                produce_cascades(merge, message.outgoing),
            );
            (
                message.offset,
                message.writes,
                membership_errors,
                cascade_errors,
            )
        }))
        .await;
        let mut staged = StagedBatch::default();
        for (offset, writes, membership_errors, cascade_errors) in produced {
            if membership_errors + cascade_errors > 0 {
                warn!(
                    partition_id,
                    offset,
                    membership_errors,
                    cascade_errors,
                    "cascade produce failed; holding the cascade offset for redelivery",
                );
                hold(&merge.cascade_tracker, partition_id, offset);
                continue;
            }
            for (key, state) in &writes {
                staged.put_stage2(key, &state.encode());
            }
        }
        if staged.is_empty() {
            return;
        }
        if let Err(error) = handle.commit(staged).await {
            warn!(
                partition_id,
                error = %error,
                "cascade cf_stage2 write failed; holding the cascade group for redelivery",
            );
            hold(&merge.cascade_tracker, partition_id, first);
        }
    }
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
    use cohort_core::seed::RunId;
    use serde_json::{json, Value};
    use tempfile::TempDir;

    use crate::cascade::first_cascade;
    use crate::filters::{FilterCatalog, TeamFiltersBuilder};
    use crate::producer::{
        CaptureCascadeSink, CaptureSink, CaptureStreamEventSink, CaptureTransferSink, ChangeOrigin,
        MembershipStatus,
    };
    use crate::stage1::key::LeafStateKey;
    use crate::stage1::person_record::{MatchedSet, PersonRecord};
    use crate::stage1::state::{AppliedOffsets, Stage1State, StatefulRecord};
    use crate::stage2::state::Stage2Ownership;
    use crate::store::{
        Behavioral, BehavioralKey, CohortStore, OffloadConfig, OffloadMode, PersonRecordKey,
        PersonRecords, StoreConfig,
    };
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

    /// Wraps the store so `handle_cascades` exercises the same blocking-pool transport as
    /// production.
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

    fn person(n: u128) -> Uuid {
        Uuid::from_u128(n)
    }

    fn write_behavioral(store: &CohortStore, lsk: LeafStateKey, who: Uuid, state: Stage1State) {
        let key = BehavioralKey::new(PARTITION, TEAM as u64, who, lsk);
        let record = StatefulRecord::new(state, AppliedOffsets::default());
        store
            .write_batch(|b| b.put::<Behavioral>(&key, &record.encode()))
            .unwrap();
    }

    fn write_person_record(store: &CohortStore, who: Uuid, matched: &[[u8; 16]]) {
        let key = PersonRecordKey::new(PARTITION, TEAM as u64, who);
        let mut record = PersonRecord::absent();
        record.matched = MatchedSet::from_iter(matched.iter().copied());
        store
            .write_batch(|b| b.put::<PersonRecords>(&key, &record.encode()))
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
            seed_tile_sink: Arc::new(crate::producer::CaptureSeedTileSink::new()),
            seed_tracker: Arc::new(crate::partitions::offset_tracker::OffsetTracker::new()),
            live_watermarks: Arc::new(crate::partitions::watermarks::LiveWatermarks::new()),
            register_transfer_enabled: false,
            reconcile: crate::workers::ReconcileDeps::default(),
            person_seed: crate::workers::PersonSeedDeps::default(),
            seed_budget: crate::workers::seed_run::RunBudget::default(),
        };
        (sink, deps)
    }

    /// Handle `messages` as one worker sub-batch at offsets `OFFSET`, `OFFSET + 1`, and so on.
    async fn run(
        store: &CohortStore,
        catalog: &CatalogHandle,
        sink: &Arc<dyn MembershipSink>,
        deps: &MergeWorkerDeps,
        messages: Vec<CascadeMessage>,
    ) {
        let batch: Vec<(Box<CascadeMessage>, i64)> = (OFFSET..)
            .zip(messages)
            .map(|(offset, message)| (Box::new(message), offset))
            .collect();
        // The cascades were dispatched this tenure, so their ceiling is raised, as the dispatcher
        // does.
        deps.cascade_tracker
            .mark_dispatched(PARTITION as i32, OFFSET + batch.len() as i64);
        handle_cascades(
            PARTITION,
            &handle(store),
            catalog,
            sink,
            deps,
            &mut LastUpdatedClock::default(),
            batch,
        )
        .await;
    }

    fn incoming(flipped: i32, who: Uuid, depth: u8, chain: Vec<i32>) -> CascadeMessage {
        CascadeMessage {
            change: CohortMembershipChange {
                team_id: TEAM,
                cohort_id: flipped,
                person_id: who.to_string(),
                last_updated: TS.to_string(),
                status: MembershipStatus::Entered,
                origin: None,
                run_id: None,
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
        write_behavioral(&store, behavioral_lsk(&catalog), alice, behavioral_match());
        write_person_record(&store, alice, &[PERSON_HASH]);

        let membership = CaptureSink::new();
        let cascade = CaptureCascadeSink::new();
        let (sink, deps) = deps(&membership, &cascade, true, 1000);
        let mut flipped = incoming(2, alice, 1, vec![2]).change;
        flipped.origin = Some(ChangeOrigin::Seed);
        flipped.run_id = Some(RunId(Uuid::nil()));
        let msg = first_cascade(flipped, 99);

        run(&store, &catalog, &sink, &deps, vec![msg]).await;

        let changes = membership.changes();
        assert_eq!(changes.len(), 1, "B's external flip");
        assert_eq!(changes[0].cohort_id, 1);
        assert_eq!(changes[0].status, MembershipStatus::Entered);
        assert_eq!(changes[0].person_id, alice.to_string());
        assert_eq!(
            changes[0].origin,
            Some(ChangeOrigin::Seed),
            "a seed flip's cascade stays a seed change"
        );
        assert_eq!(changes[0].run_id, None, "B is not part of A's run");

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
        write_behavioral(&store, behavioral_lsk(&catalog), alice, behavioral_match());
        write_person_record(&store, alice, &[PERSON_HASH]);
        write_stage2(&store, 1, alice, true); // B already a member

        let membership = CaptureSink::new();
        let cascade = CaptureCascadeSink::new();
        let (sink, deps) = deps(&membership, &cascade, true, 1000);
        let msg = first_cascade(incoming(2, alice, 1, vec![2]).change, 99);

        run(&store, &catalog, &sink, &deps, vec![msg]).await;

        assert!(membership.changes().is_empty(), "no flip, no membership");
        assert!(cascade.messages().is_empty(), "no flip, no onward cascade");
        assert_eq!(committed(&deps), Some(OFFSET + 1), "still advances");
    }

    #[tokio::test]
    async fn cascade_noop_claims_a_transferred_fallback_without_emitting() {
        let (_dir, store) = temp_store();
        let catalog = catalog(
            vec![
                (2, vec![behavioral_leaf()]),
                (1, vec![person_leaf(), cohort_ref(2)]),
            ],
            true,
        );
        let alice = person(1);
        write_behavioral(&store, behavioral_lsk(&catalog), alice, behavioral_match());
        write_person_record(&store, alice, &[PERSON_HASH]);
        let key = Stage2Key {
            partition_id: PARTITION,
            team_id: TEAM as u64,
            cohort_id: 1,
            person_id: alice,
        };
        store
            .write_batch(|batch| {
                batch.put_stage2(
                    &key,
                    &Stage2State {
                        in_cohort: true,
                        last_evaluated_at_ms: 0,
                    }
                    .encode_transferred_fallback(),
                );
            })
            .unwrap();

        let membership = CaptureSink::new();
        let cascade = CaptureCascadeSink::new();
        let (sink, deps) = deps(&membership, &cascade, true, 1000);
        let msg = first_cascade(incoming(2, alice, 1, vec![2]).change, 99);

        run(&store, &catalog, &sink, &deps, vec![msg]).await;

        let bytes = store.get_stage2(&key).unwrap().unwrap();
        let (state, ownership) = Stage2State::decode_with_ownership(&bytes).unwrap();
        assert!(state.in_cohort);
        assert_eq!(ownership, Stage2Ownership::Local);
        assert!(
            membership.changes().is_empty(),
            "ownership settlement is not a flip"
        );
        assert!(
            cascade.messages().is_empty(),
            "ownership settlement does not cascade"
        );
        assert_eq!(committed(&deps), Some(OFFSET + 1));
    }

    #[tokio::test]
    async fn no_referrers_drains_without_emitting() {
        let (_dir, store) = temp_store();
        // Cohort 2 is single-leaf and referenced by nothing.
        let catalog = catalog(vec![(2, vec![behavioral_leaf()])], true);
        let alice = person(1);
        write_behavioral(&store, behavioral_lsk(&catalog), alice, behavioral_match());

        let membership = CaptureSink::new();
        let cascade = CaptureCascadeSink::new();
        let (sink, deps) = deps(&membership, &cascade, true, 1000);
        let msg = first_cascade(incoming(2, alice, 1, vec![2]).change, 99);

        run(&store, &catalog, &sink, &deps, vec![msg]).await;

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
        write_behavioral(&store, behavioral_lsk(&catalog), alice, behavioral_match());
        write_person_record(&store, alice, &[PERSON_HASH]);

        let membership = CaptureSink::new();
        let cascade = CaptureCascadeSink::new();
        let (sink, deps) = deps(&membership, &cascade, false, 1000); // gate OFF
        let msg = first_cascade(incoming(2, alice, 1, vec![2]).change, 99);

        run(&store, &catalog, &sink, &deps, vec![msg]).await;

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
        write_behavioral(&store, behavioral_lsk(&catalog), alice, behavioral_match());
        write_person_record(&store, alice, &[PERSON_HASH]);

        let membership = CaptureSink::new();
        let cascade = CaptureCascadeSink::new();
        let (sink, deps) = deps(&membership, &cascade, true, 1000);
        // Incoming depth == cap (8): the external flip still emits, the onward cascade drops.
        let msg = incoming(2, alice, 8, vec![2, 90, 91, 92, 93, 94, 95, 96]);

        run(&store, &catalog, &sink, &deps, vec![msg]).await;

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
        write_behavioral(&store, behavioral_lsk(&catalog), alice, behavioral_match());
        write_person_record(&store, alice, &[PERSON_HASH]);

        let membership = CaptureSink::new();
        let cascade = CaptureCascadeSink::new();
        let (sink, deps) = deps(&membership, &cascade, true, 1000);
        // B (cohort 1) is already in the chain: the onward hop is a runtime cycle.
        let msg = incoming(2, alice, 2, vec![2, 1]);

        run(&store, &catalog, &sink, &deps, vec![msg]).await;

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
        write_behavioral(&store, behavioral_lsk(&catalog), alice, behavioral_match());
        write_person_record(&store, alice, &[PERSON_HASH]);

        let membership = CaptureSink::new();
        let cascade = CaptureCascadeSink::new();
        let (sink, deps) = deps(&membership, &cascade, true, 2); // cap 2 of 4 referrers
        let msg = first_cascade(incoming(100, alice, 1, vec![100]).change, 99);

        run(&store, &catalog, &sink, &deps, vec![msg]).await;

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
        write_behavioral(&store, behavioral_lsk(&catalog), alice, behavioral_match());
        write_person_record(&store, alice, &[PERSON_HASH]);

        let membership = CaptureSink::new();
        let cascade = CaptureCascadeSink::new();
        let (sink, deps) = deps(&membership, &cascade, true, 1000);
        let msg = first_cascade(incoming(2, alice, 1, vec![2]).change, 99);

        run(&store, &catalog, &sink, &deps, vec![msg.clone()]).await;
        assert_eq!(membership.changes().len(), 1, "first pass emits");

        run(&store, &catalog, &sink, &deps, vec![msg]).await;
        assert_eq!(
            membership.changes().len(),
            1,
            "replay re-detects no flip (B's bit is now set) and emits nothing",
        );
    }

    /// Alice, Bob and Carol each enter cohort 2, which cohort 1 references.
    fn three_flips(
        store: &CohortStore,
        catalog: &CatalogHandle,
    ) -> (Vec<Uuid>, Vec<CascadeMessage>) {
        let people = vec![person(1), person(2), person(3)];
        let messages = people
            .iter()
            .map(|&who| {
                write_behavioral(store, behavioral_lsk(catalog), who, behavioral_match());
                write_person_record(store, who, &[PERSON_HASH]);
                first_cascade(incoming(2, who, 1, vec![2]).change, 99)
            })
            .collect();
        (people, messages)
    }

    #[tokio::test]
    async fn a_batch_of_flips_commits_every_bit() {
        let (_dir, store) = temp_store();
        let catalog = catalog(
            vec![
                (2, vec![behavioral_leaf()]),
                (1, vec![person_leaf(), cohort_ref(2)]),
            ],
            true,
        );
        let (people, messages) = three_flips(&store, &catalog);

        let membership = CaptureSink::new();
        let cascade = CaptureCascadeSink::new();
        let (sink, deps) = deps(&membership, &cascade, true, 1000);
        run(&store, &catalog, &sink, &deps, messages).await;

        let changes = membership.changes();
        assert_eq!(changes.len(), 3);
        assert!(
            changes
                .iter()
                .all(|change| change.last_updated == changes[0].last_updated),
            "the three flips settle as one group, which stamps them once",
        );
        assert_eq!(cascade.messages().len(), 3);
        for who in people {
            assert_eq!(
                read_stage2(&store, 1, who),
                Some(true),
                "{who}'s bit committed"
            );
        }
        assert_eq!(committed(&deps), Some(OFFSET + 3), "the last offset marked");
    }

    /// C references B, which references A. The second message is B's flip coming back for the same
    /// person, so recomposing C must read the bit the first message writes for B.
    #[tokio::test]
    async fn a_second_cascade_for_a_touched_person_reads_the_committed_bit() {
        let (_dir, store) = temp_store();
        let catalog = catalog(
            vec![
                (3, vec![behavioral_leaf()]),
                (2, vec![person_leaf(), cohort_ref(3)]),
                (1, vec![person_leaf(), cohort_ref(2)]),
            ],
            true,
        );
        let alice = person(1);
        write_behavioral(&store, behavioral_lsk(&catalog), alice, behavioral_match());
        write_person_record(&store, alice, &[PERSON_HASH]);

        let membership = CaptureSink::new();
        let cascade = CaptureCascadeSink::new();
        let (sink, deps) = deps(&membership, &cascade, true, 1000);
        run(
            &store,
            &catalog,
            &sink,
            &deps,
            vec![
                first_cascade(incoming(3, alice, 1, vec![3]).change, 99),
                incoming(2, alice, 2, vec![3, 2]),
            ],
        )
        .await;

        let cohorts: Vec<i32> = membership.changes().iter().map(|c| c.cohort_id).collect();
        assert_eq!(
            cohorts,
            vec![2, 1],
            "B enters, then C enters on B's written bit"
        );
        assert_eq!(read_stage2(&store, 2, alice), Some(true));
        assert_eq!(read_stage2(&store, 1, alice), Some(true));
        assert_eq!(committed(&deps), Some(OFFSET + 2));
    }

    /// Alice's records fail and Bob's and Carol's ack in the same round trip.
    #[tokio::test]
    async fn a_failed_produce_leg_holds_only_its_own_message() {
        for (failing_leg, membership, cascade) in [
            (
                "membership",
                CaptureSink::failing_first(1),
                CaptureCascadeSink::new(),
            ),
            (
                "cascade",
                CaptureSink::new(),
                CaptureCascadeSink::failing_first(1),
            ),
        ] {
            let (_dir, store) = temp_store();
            let catalog = catalog(
                vec![
                    (2, vec![behavioral_leaf()]),
                    (1, vec![person_leaf(), cohort_ref(2)]),
                ],
                true,
            );
            let (people, messages) = three_flips(&store, &catalog);
            let (sink, deps) = deps(&membership, &cascade, true, 1000);

            run(&store, &catalog, &sink, &deps, messages).await;

            assert_eq!(
                read_stage2(&store, 1, people[0]),
                None,
                "{failing_leg} leg failed: produce-before-state leaves alice's bit for the replay",
            );
            for who in &people[1..] {
                assert_eq!(
                    read_stage2(&store, 1, *who),
                    Some(true),
                    "{failing_leg} leg failed for alice only: {who}'s acked flip keeps its bit",
                );
            }
            assert_eq!(
                committed(&deps),
                Some(OFFSET),
                "{failing_leg} leg failed: the floor pins alice's offset under the run's mark",
            );
        }
    }
}
