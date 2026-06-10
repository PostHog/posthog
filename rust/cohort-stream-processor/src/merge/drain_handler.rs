//! Phase 1 of the cross-partition merge protocol (TDD §4.5.1): drain P_old on its own worker.
//!
//! Sink-free and store-level — given a `PersonMergeEvent` (keyed by P_old, so it lands here) it reads
//! P_old's per-leaf state, then either:
//!
//! - **fast path** (P_new co-resides on this partition, ~1.6%): merges P_old into P_new via the apply
//!   core and commits one atomic `WriteBatch` (delete P_old's state + tombstone + drain marker +
//!   merged P_new puts + index appends), returning P_new's transitions; or
//! - **slow path** (~98.4%): packages P_old's records into a [`MergeStateTransfer`] staged in
//!   `cf_pending_transfers`, deletes P_old's state, writes the tombstone + drain marker, and returns
//!   the transfer for the caller (C2) to produce → clear the outbox → commit the merge offset.
//!
//! Per Decision 1 the drain emits **no `Left`** for P_old — it silently deletes P_old's
//! `cf_stage1` / `cf_person_index` / `cf_stage2` rows (the parity comparator scopes merged-away
//! persons out), and so needs no `cf_stage2` reads: P_old's `Stage2Key`s are built from the catalog's
//! composable-cohort list and deleting an absent key is a no-op.

use metrics::counter;

use crate::filters::reverse_index::TeamFilters;
use crate::filters::{CohortId, TeamId};
use crate::merge::apply_handler::apply_leaves;
use crate::merge::transfer::{
    DrainStamp, MergeStateTransfer, PendingTransfer, PersonMergeEvent, Tombstone, TransferLeaf,
};
use crate::observability::metrics::{
    MERGE_DRAINS_SKIPPED_REPLAY_TOTAL, MERGE_HANDLED_TOTAL, MERGE_LEAVES_DROPPED_TOTAL,
};
use crate::partitions::partitioner::{partition_of, COHORT_PARTITION_COUNT};
use crate::stage1::key::{LeafStateKey, Stage1Key};
use crate::stage1::state::StatefulRecord;
use crate::stage1::transition::LeafTransition;
use crate::stage2::CohortEligibility;
use crate::store::{
    CohortStore, IndexOp, MergeDrainKey, PendingTransferKey, PersonIndexKey, Stage2Key, StoreError,
    TombstoneKey,
};
use crate::sweep::EvictionQueue;

/// The result of draining a merge event.
#[derive(Debug, Clone, PartialEq)]
pub enum DrainOutcome {
    /// Same-partition fast path: P_old merged into P_new inline. `transitions` are P_new's per-leaf
    /// flips for the caller to compose Stage 2 + produce (acceptance #1).
    FastPath { transitions: Vec<LeafTransition> },
    /// Cross-partition slow path: P_old's state was drained into `transfer`, staged in
    /// `cf_pending_transfers`. The caller produces it to `cohort_merge_state_transfer`, clears the
    /// outbox, then commits the merge offset (acceptance #2).
    Drained { transfer: MergeStateTransfer },
    /// A `cf_merge_drains_applied` hit — this merge message was already drained (acceptance #3 / #6).
    /// The caller re-produces any still-staged `cf_pending_transfers` entry, then commits.
    AlreadyDrained,
    /// Skipped before any state change (validation failure).
    Skipped(DrainSkip),
}

/// Why a merge was skipped before draining.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DrainSkip {
    /// `old_person == new_person` — a degenerate self-merge the merge service never emits.
    SamePerson,
}

/// Drain the merge `event` on P_old's worker (`partition_id` owns P_old). `msg_coords` is the
/// triggering merge message's Kafka `(partition, offset)`, keying `cf_merge_drains_applied`.
pub fn handle_merge_event(
    partition_id: u16,
    store: &CohortStore,
    filters: &TeamFilters,
    event: &PersonMergeEvent,
    msg_coords: (i32, i64),
    queue: &mut EvictionQueue<Stage1Key>,
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

    // ── All reads before any write (red-team H1) ──────────────────────────────────
    let old_index = PersonIndexKey {
        partition_id,
        team_id: team_u64,
        person_id: old_person,
    };
    let lsks = store.get_person_index(&old_index)?;
    let old_keys: Vec<Stage1Key> = lsks
        .iter()
        .map(|&lsk| Stage1Key {
            partition_id,
            team_id: team_u64,
            leaf_state_key: lsk,
            person_id: old_person,
        })
        .collect();
    let raw = store.multi_get_stage1(&old_keys)?;

    let mut present_leaves: Vec<(LeafStateKey, StatefulRecord)> = Vec::new();
    for (&lsk, bytes) in lsks.iter().zip(raw) {
        match bytes {
            // A stale index entry pointing at deleted state — tolerate the hole (the row delete below
            // is still a no-op for it).
            None => {
                counter!(MERGE_LEAVES_DROPPED_TOTAL, "reason" => "stale_index").increment(1);
            }
            Some(bytes) => match StatefulRecord::decode(&bytes) {
                Ok(record) => present_leaves.push((lsk, record)),
                Err(_) => {
                    counter!(MERGE_LEAVES_DROPPED_TOTAL, "reason" => "decode").increment(1);
                }
            },
        }
    }

    // Values shared by both paths. P_old's `cf_stage2` rows are built from the catalog, not read.
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

    let partition_new = partition_of(TeamId(team_id), &new_person, COHORT_PARTITION_COUNT) as u16;

    if partition_new == partition_id {
        return fast_path(
            partition_id,
            store,
            filters,
            event,
            &drain_key,
            &drain_stamp,
            &tombstone_key,
            &tombstone,
            &old_keys,
            &old_index,
            &old_stage2_keys,
            &present_leaves,
            queue,
        );
    }

    slow_path(
        partition_id,
        store,
        event,
        msg_coords,
        &drain_key,
        &drain_stamp,
        &tombstone_key,
        &tombstone,
        &old_keys,
        &old_index,
        &old_stage2_keys,
        &present_leaves,
        queue,
    )
}

/// Same-partition fast path: drain P_old and apply into P_new in one atomic `WriteBatch`.
#[allow(clippy::too_many_arguments)]
fn fast_path(
    partition_id: u16,
    store: &CohortStore,
    filters: &TeamFilters,
    event: &PersonMergeEvent,
    drain_key: &MergeDrainKey,
    drain_stamp: &DrainStamp,
    tombstone_key: &TombstoneKey,
    tombstone: &Tombstone,
    old_keys: &[Stage1Key],
    old_index: &PersonIndexKey,
    old_stage2_keys: &[Stage2Key],
    present_leaves: &[(LeafStateKey, StatefulRecord)],
    queue: &mut EvictionQueue<Stage1Key>,
) -> Result<DrainOutcome, StoreError> {
    counter!(MERGE_HANDLED_TOTAL, "path" => "same_partition").increment(1);

    let team_u64 = event.team_id as u64;
    // The apply core reads P_new's records (still before any write).
    let apply = apply_leaves(
        partition_id,
        store,
        filters,
        event.team_id,
        event.old_person_uuid,
        event.new_person_uuid,
        present_leaves,
    )?;

    let new_index = PersonIndexKey {
        partition_id,
        team_id: team_u64,
        person_id: event.new_person_uuid,
    };
    store.write_batch(|batch| {
        // Drain P_old: delete its stage1 rows, person index, and composable cf_stage2 rows.
        for key in old_keys {
            batch.delete_stage1(key);
        }
        batch.delete_person_index(old_index);
        for key in old_stage2_keys {
            batch.delete_stage2(key);
        }
        // Tombstone + drain idempotence marker (a same-partition replay short-circuits via the latter).
        batch.put_tombstone(tombstone_key, &tombstone.encode());
        batch.put_merge_drain_applied(drain_key, &drain_stamp.encode());
        // Apply into P_new.
        for (key, bytes) in &apply.puts {
            batch.put_stage1(key, bytes);
        }
        for lsk in &apply.appends {
            batch.merge_person_index(&new_index, IndexOp::Append(*lsk));
        }
    })?;

    // Cancel P_old's pending evictions; (re)schedule P_new's merged deadlines.
    for key in old_keys {
        queue.cancel(key);
    }
    for (key, deadline) in &apply.schedules {
        queue.schedule(*key, *deadline);
    }

    Ok(DrainOutcome::FastPath {
        transitions: apply.transitions,
    })
}

/// Cross-partition slow path: drain P_old and stage the transfer for the caller to produce.
#[allow(clippy::too_many_arguments)]
fn slow_path(
    partition_id: u16,
    store: &CohortStore,
    event: &PersonMergeEvent,
    msg_coords: (i32, i64),
    drain_key: &MergeDrainKey,
    drain_stamp: &DrainStamp,
    tombstone_key: &TombstoneKey,
    tombstone: &Tombstone,
    old_keys: &[Stage1Key],
    old_index: &PersonIndexKey,
    old_stage2_keys: &[Stage2Key],
    present_leaves: &[(LeafStateKey, StatefulRecord)],
    queue: &mut EvictionQueue<Stage1Key>,
) -> Result<DrainOutcome, StoreError> {
    counter!(MERGE_HANDLED_TOTAL, "path" => "cross_partition").increment(1);

    let team_u64 = event.team_id as u64;
    let transfer = MergeStateTransfer {
        team_id: event.team_id,
        old_person_uuid: event.old_person_uuid,
        new_person_uuid: event.new_person_uuid,
        merged_at_ms: event.merged_at_ms,
        source_partition: msg_coords.0,
        source_offset: msg_coords.1,
        // Records carried whole, so `redirect_dedup` chains transfer for free on the apply side.
        leaves: present_leaves
            .iter()
            .map(|(lsk, record)| TransferLeaf::new(*lsk, record.clone()))
            .collect(),
    };
    let pending = PendingTransfer {
        transfer: transfer.clone(),
        merge_msg_partition: msg_coords.0,
        merge_msg_offset: msg_coords.1,
    };
    let pending_key = PendingTransferKey {
        partition_id,
        team_id: team_u64,
        old_person: event.old_person_uuid,
    };

    store.write_batch(|batch| {
        // Stage the outbox + drain marker, then delete P_old's state and write the tombstone — one
        // atomic batch, so a crash leaves either the full drain or none of it.
        batch.put_pending_transfer(&pending_key, &pending.encode());
        batch.put_merge_drain_applied(drain_key, &drain_stamp.encode());
        for key in old_keys {
            batch.delete_stage1(key);
        }
        batch.delete_person_index(old_index);
        for key in old_stage2_keys {
            batch.delete_stage2(key);
        }
        batch.put_tombstone(tombstone_key, &tombstone.encode());
    })?;

    for key in old_keys {
        queue.cancel(key);
    }

    Ok(DrainOutcome::Drained { transfer })
}

/// The team's `Stage2Composable` cohort ids — the only cohorts that ever wrote a `cf_stage2` row, so
/// deleting P_old's `Stage2Key` for each (a no-op when absent) reclaims its membership rows with no
/// reads.
fn composable_cohort_ids(filters: &TeamFilters) -> impl Iterator<Item = CohortId> + '_ {
    filters
        .eligibility
        .iter()
        .filter_map(|(&cohort_id, eligibility)| {
            matches!(eligibility, CohortEligibility::Stage2Composable).then_some(cohort_id)
        })
}
