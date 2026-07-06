//! Drain P_old on its own worker (phase 1 of cross-partition merge).
//!
//! Given a `PersonMergeEvent` (keyed by P_old), enumerates P_old's per-leaf state with one scan of
//! its person prefix, then either:
//!
//! - **fast path** (P_new co-resides on this partition): merges inline via the apply core in one
//!   atomic `WriteBatch`, returning P_new's transitions; or
//! - **slow path**: packages P_old's records into a [`MergeStateTransfer`] staged in
//!   `cf_pending_transfers`, deletes P_old's state, writes the tombstone + drain marker, and returns
//!   the transfer for the caller to produce.
//!
//! The drain emits no `Left` for P_old — it silently reclaims P_old's `cf_behavioral` slice with one
//! range delete over its person prefix. P_old's `cf_stage2` keys are built from the catalog (no
//! reads needed; deleting an absent key is a no-op).

use metrics::{counter, histogram};
use uuid::Uuid;

use crate::filters::reverse_index::TeamFilters;
use crate::filters::{CohortId, TeamId};
use crate::merge::apply_handler::{apply_leaves, merge_person_records, QueueEffects};
use crate::merge::tombstone_redirect::{resolve, Resolution};
use crate::merge::transfer::{
    DrainStamp, MergeStateTransfer, PendingTransfer, PersonMergeEvent, Tombstone, TransferLeaf,
};
use crate::observability::metrics::{
    MERGE_DRAINS_SKIPPED_REPLAY_TOTAL, MERGE_DRAIN_LEAVES_SCANNED, MERGE_HANDLED_TOTAL,
    MERGE_LEAVES_DROPPED_TOTAL,
};
use crate::partitions::partitioner::partition_of;
use crate::stage1::key::LeafStateKey;
use crate::stage1::person_record::{PersonDedup, PersonRecord};
use crate::stage1::state::StatefulRecord;
use crate::stage1::transition::LeafTransition;
use crate::store::{
    Behavioral, BehavioralKey, CohortStore, MergeDrainKey, PendingTransferKey, PersonPrefix,
    PersonRecords, Stage2Key, StoreError, TombstoneKey,
};

#[derive(Debug, Clone, PartialEq)]
pub enum DrainOutcome {
    /// Same-partition fast path: P_old merged into P_new inline. `effects` cancels P_old's keys and
    /// schedules P_new's new deadlines.
    FastPath {
        transitions: Vec<LeafTransition>,
        effects: QueueEffects,
    },
    /// Cross-partition slow path: state drained into `transfer`, staged in `cf_pending_transfers`.
    /// A transfer with no leaves and no person-record dedup is not staged; the caller skips the produce
    /// and commits directly. `effects` cancels P_old's now-deleted keys (no schedules — the state left
    /// this partition).
    Drained {
        transfer: MergeStateTransfer,
        effects: QueueEffects,
    },
    /// Idempotence hit — already drained. The caller re-produces any still-staged pending transfer.
    AlreadyDrained,
    /// Skipped before any state change (validation failure).
    Skipped(DrainSkip),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DrainSkip {
    SamePerson,
}

/// Drain the merge `event` on P_old's worker (`partition_id` owns P_old).
///
/// `partition_count` is the live co-partitioned topic count (production 64; test lanes lower it):
/// the fast-path-vs-slow-path decision turns on whether P_new hashes onto `partition_id` under this
/// count, so it must match the deploy's topology.
// Sync drain core; runs on the blocking pool inside `StoreHandle::run_section`, so its direct
// `CohortStore` I/O (and that of `fast_path`/`slow_path`) is already off the runtime threads.
#[allow(clippy::disallowed_methods)]
pub fn handle_merge_event(
    partition_id: u16,
    store: &CohortStore,
    filters: &TeamFilters,
    event: &PersonMergeEvent,
    msg_coords: (i32, i64),
    partition_count: u32,
) -> Result<DrainOutcome, StoreError> {
    let team_id = event.team_id;
    let team_u64 = team_id as u64;
    let old_person = event.old_person_uuid;
    let new_person = event.new_person_uuid;

    if old_person == new_person {
        counter!(MERGE_LEAVES_DROPPED_TOTAL, "reason" => "same_person").increment(1);
        return Ok(DrainOutcome::Skipped(DrainSkip::SamePerson));
    }

    let drain_key = MergeDrainKey {
        partition_id,
        team_id: team_u64,
        old_person,
        merge_msg_partition: msg_coords.0,
        merge_msg_offset: msg_coords.1,
    };
    if store.get_merge_drain_applied(&drain_key)?.is_some() {
        counter!(MERGE_DRAINS_SKIPPED_REPLAY_TOTAL).increment(1);
        return Ok(DrainOutcome::AlreadyDrained);
    }

    // Enumerate P_old's leaves by prefix-scanning its `cf_behavioral` slice. Scan order is lsk-byte
    // order, so transfer leaf ordering is stable. `old_keys` is kept for the eviction queue's per-key
    // cancels; the range delete below reclaims the rows in one tombstone.
    let old_prefix = PersonPrefix::new(partition_id, team_u64, old_person);
    let old_rows = store.scan_behavioral_prefix(old_prefix)?;
    histogram!(MERGE_DRAIN_LEAVES_SCANNED).record(old_rows.len() as f64);
    let old_keys: Vec<BehavioralKey> = old_rows.iter().map(|(key, _)| *key).collect();

    let mut present_leaves: Vec<(LeafStateKey, StatefulRecord)> = Vec::new();
    for (key, bytes) in &old_rows {
        match StatefulRecord::decode(bytes) {
            Ok(record) => present_leaves.push((key.lsk(), record)),
            Err(_) => {
                counter!(MERGE_LEAVES_DROPPED_TOTAL, "reason" => "decode").increment(1);
            }
        }
    }

    // P_old's person record carries only its replay-dedup offsets to P_new (never its matched set,
    // fingerprints, or stamp — P_new re-evaluates lazily). Absent or corrupt carries nothing.
    let person_dedup: Option<PersonDedup> =
        match store.get_person_record(&old_prefix.record_key())? {
            None => None,
            Some(bytes) => match PersonRecord::decode(&bytes) {
                Ok(record) => Some(record.dedup_carrier()),
                Err(_) => {
                    counter!(MERGE_LEAVES_DROPPED_TOTAL, "reason" => "record_decode").increment(1);
                    None
                }
            },
        };

    let tombstone = Tombstone {
        new_person,
        merged_at_ms: event.merged_at_ms,
    };
    let drain_stamp = DrainStamp {
        drained_at_ms: event.merged_at_ms,
    };
    let tombstone_key = TombstoneKey {
        partition_id,
        team_id: team_u64,
        person: old_person,
    };
    let old_stage2_keys: Vec<Stage2Key> = composable_cohort_ids(filters)
        .map(|cohort_id| Stage2Key {
            partition_id,
            team_id: team_u64,
            cohort_id: cohort_id.0 as u64,
            person_id: old_person,
        })
        .collect();

    // Same-slice assist: if P_new is itself tombstoned in *this* slice, drain straight to the live
    // survivor, skipping a hop the apply-side resolution would otherwise take. Only the routing/apply
    // target advances — P_old's stored tombstone still records `new_person` as the merge event gave
    // it, so the chain stays walkable hop-by-hop.
    let effective_new_person = match resolve(
        store,
        partition_id,
        TeamId(team_id),
        new_person,
        partition_count,
    )? {
        Resolution::NotMerged => new_person,
        Resolution::Inline { final_person, .. } => final_person,
        Resolution::CrossPartition { target_person, .. } => target_person,
    };

    let partition_new =
        partition_of(TeamId(team_id), &effective_new_person, partition_count) as u16;

    if partition_new == partition_id {
        return fast_path(
            partition_id,
            store,
            filters,
            event,
            effective_new_person,
            &drain_key,
            &drain_stamp,
            &tombstone_key,
            &tombstone,
            &old_keys,
            &old_prefix,
            &old_stage2_keys,
            &present_leaves,
            person_dedup.as_ref(),
        );
    }

    slow_path(
        partition_id,
        store,
        event,
        effective_new_person,
        msg_coords,
        &drain_key,
        &drain_stamp,
        &tombstone_key,
        &tombstone,
        &old_keys,
        &old_prefix,
        &old_stage2_keys,
        &present_leaves,
        person_dedup,
    )
}

/// Same-partition fast path: drain P_old and apply into P_new in one atomic batch.
#[allow(clippy::too_many_arguments, clippy::disallowed_methods)]
fn fast_path(
    partition_id: u16,
    store: &CohortStore,
    filters: &TeamFilters,
    event: &PersonMergeEvent,
    effective_new_person: Uuid,
    drain_key: &MergeDrainKey,
    drain_stamp: &DrainStamp,
    tombstone_key: &TombstoneKey,
    tombstone: &Tombstone,
    old_keys: &[BehavioralKey],
    old_prefix: &PersonPrefix,
    old_stage2_keys: &[Stage2Key],
    present_leaves: &[(LeafStateKey, StatefulRecord)],
    person_dedup: Option<&PersonDedup>,
) -> Result<DrainOutcome, StoreError> {
    counter!(MERGE_HANDLED_TOTAL, "path" => "same_partition").increment(1);

    let apply = apply_leaves(
        partition_id,
        store,
        filters,
        event.team_id,
        event.old_person_uuid,
        effective_new_person,
        present_leaves,
    )?;

    // Fold P_old's record dedup into P_new's record in the same batch; an absent/corrupt P_new record
    // writes nothing.
    let team_u64 = event.team_id as u64;
    let new_prefix = PersonPrefix::new(partition_id, team_u64, effective_new_person);
    let record_put = match person_dedup {
        Some(dedup) => merge_person_records(store, &new_prefix, event.old_person_uuid, dedup)?,
        None => None,
    };

    store.write_batch(|batch| {
        batch.delete_behavioral_prefix(old_prefix);
        batch.delete::<PersonRecords>(&old_prefix.record_key());
        for key in old_stage2_keys {
            batch.delete_stage2(key);
        }
        batch.put_tombstone(tombstone_key, &tombstone.encode());
        batch.put_merge_drain_applied(drain_key, &drain_stamp.encode());
        for (key, bytes) in &apply.puts {
            batch.put::<Behavioral>(key, bytes);
        }
        if let Some(bytes) = &record_put {
            batch.put::<PersonRecords>(&new_prefix.record_key(), bytes);
        }
    })?;

    Ok(DrainOutcome::FastPath {
        transitions: apply.transitions,
        effects: QueueEffects {
            cancels: old_keys.to_vec(),
            schedules: apply.schedules,
        },
    })
}

/// Cross-partition slow path: drain P_old, stage the transfer for the caller to produce.
#[allow(clippy::too_many_arguments, clippy::disallowed_methods)]
fn slow_path(
    partition_id: u16,
    store: &CohortStore,
    event: &PersonMergeEvent,
    effective_new_person: Uuid,
    msg_coords: (i32, i64),
    drain_key: &MergeDrainKey,
    drain_stamp: &DrainStamp,
    tombstone_key: &TombstoneKey,
    tombstone: &Tombstone,
    old_keys: &[BehavioralKey],
    old_prefix: &PersonPrefix,
    old_stage2_keys: &[Stage2Key],
    present_leaves: &[(LeafStateKey, StatefulRecord)],
    person_dedup: Option<PersonDedup>,
) -> Result<DrainOutcome, StoreError> {
    counter!(MERGE_HANDLED_TOTAL, "path" => "cross_partition").increment(1);

    let team_u64 = event.team_id as u64;
    let transfer = MergeStateTransfer {
        team_id: event.team_id,
        old_person_uuid: event.old_person_uuid,
        new_person_uuid: effective_new_person,
        merged_at_ms: event.merged_at_ms,
        source_partition: msg_coords.0,
        source_offset: msg_coords.1,
        leaves: present_leaves
            .iter()
            .map(|(lsk, record)| TransferLeaf::new(*lsk, record.clone()))
            .collect(),
        forward_hops: 0,
        person_dedup,
    };
    // Stage iff the transfer carries leaves or a person-record dedup; a record-only person would
    // otherwise lose its straggler-dedup ancestry. A truly empty transfer is never staged — a duplicate
    // merge event at fresh coordinates could overwrite a still-pending, never-produced transfer.
    let has_payload = !transfer.leaves.is_empty() || transfer.person_dedup.is_some();
    let pending = has_payload.then(|| PendingTransfer {
        transfer: transfer.clone(),
        merge_msg_partition: msg_coords.0,
        merge_msg_offset: msg_coords.1,
    });
    let pending_key = PendingTransferKey {
        partition_id,
        team_id: team_u64,
        old_person: event.old_person_uuid,
    };

    store.write_batch(|batch| {
        if let Some(pending) = &pending {
            batch.put_pending_transfer(&pending_key, &pending.encode());
        }
        batch.put_merge_drain_applied(drain_key, &drain_stamp.encode());
        batch.delete_behavioral_prefix(old_prefix);
        batch.delete::<PersonRecords>(&old_prefix.record_key());
        for key in old_stage2_keys {
            batch.delete_stage2(key);
        }
        batch.put_tombstone(tombstone_key, &tombstone.encode());
    })?;

    Ok(DrainOutcome::Drained {
        transfer,
        effects: QueueEffects {
            cancels: old_keys.to_vec(),
            schedules: Vec::new(),
        },
    })
}

/// The team's cohort ids that write `cf_stage2` rows (both composable classes). See
/// [`writes_cf_stage2`](crate::stage2::CohortEligibility::writes_cf_stage2).
fn composable_cohort_ids(filters: &TeamFilters) -> impl Iterator<Item = CohortId> + '_ {
    filters
        .eligibility
        .iter()
        .filter_map(|(&cohort_id, eligibility)| eligibility.writes_cf_stage2().then_some(cohort_id))
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono_tz::UTC;
    use serde_json::{json, Value};

    use crate::filters::TeamFiltersBuilder;
    use crate::stage2::CohortEligibility;

    fn behavioral(time_value: i64) -> Value {
        json!({
            "type": "behavioral", "value": "performed_event", "key": "$pageview",
            "time_value": time_value, "time_interval": "day",
            "conditionHash": "0123456789abcdef",
            "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
        })
    }

    fn person() -> Value {
        json!({
            "type": "person", "key": "email", "value": "a@b.com", "operator": "exact",
            "conditionHash": "fedcba9876543210",
            "bytecode": ["_H", 1, 32, "a@b.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
        })
    }

    fn cohort_ref(target: i32) -> Value {
        json!({ "type": "cohort", "value": target, "negation": false })
    }

    fn cohort(values: Vec<Value>) -> Value {
        json!({ "properties": { "type": "AND", "values": values } })
    }

    #[test]
    fn composable_cohort_ids_enumerates_both_composable_classes_for_row_deletion() {
        let mut builder = TeamFiltersBuilder::default();
        // 2: single-leaf referent — does NOT write cf_stage2.
        builder
            .add_cohort(CohortId(2), TeamId(7), &cohort(vec![behavioral(7)]))
            .unwrap();
        // 1: own leaf + ref to 2 → Stage2ComposableRef — writes cf_stage2.
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &cohort(vec![person(), cohort_ref(2)]),
            )
            .unwrap();
        // 3: plain composable — writes cf_stage2.
        builder
            .add_cohort(
                CohortId(3),
                TeamId(7),
                &cohort(vec![behavioral(7), person()]),
            )
            .unwrap();
        let filters = builder.freeze_with(UTC, true);

        assert_eq!(
            filters.eligibility[&CohortId(1)],
            CohortEligibility::Stage2ComposableRef,
        );
        let mut ids: Vec<i32> = composable_cohort_ids(&filters).map(|c| c.0).collect();
        ids.sort_unstable();
        assert_eq!(
            ids,
            vec![1, 3],
            "a Stage2ComposableRef writer is enumerated alongside Stage2Composable; the SingleLeaf referent is not",
        );
    }

    #[test]
    fn composable_cohort_ids_gate_off_drops_the_still_excluded_ref_cohort() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(CohortId(2), TeamId(7), &cohort(vec![behavioral(7)]))
            .unwrap();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &cohort(vec![person(), cohort_ref(2)]),
            )
            .unwrap();
        let filters = builder.freeze_with(UTC, false);

        let ids: Vec<i32> = composable_cohort_ids(&filters).map(|c| c.0).collect();
        assert!(
            ids.is_empty(),
            "gate off keeps the ref cohort Excluded(HasCohortRef), which writes no cf_stage2 row",
        );
    }
}
