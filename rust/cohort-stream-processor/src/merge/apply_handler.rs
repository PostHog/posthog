//! Phase 2 of the cross-partition merge protocol (TDD §4.5.1): apply a `MergeStateTransfer` on
//! P_new's worker.
//!
//! Sink-free and store-level — given a transfer (P_old's drained per-leaf records) it merges each
//! leaf into P_new's state, commits one atomic `WriteBatch` (merged puts, `cf_person_index` appends,
//! and the `cf_merge_applied` idempotence marker), schedules P_new's eviction deadlines, and returns
//! the membership transitions for the caller to compose Stage 2 and produce. The Kafka consumer that
//! feeds it and the producer that ships its transitions are C2.

use metrics::counter;
use uuid::Uuid;

use crate::filters::reverse_index::TeamFilters;
use crate::filters::TeamId;
use crate::merge::rules::merge_records;
use crate::merge::transfer::{ApplyStamp, MergeStateTransfer};
use crate::observability::metrics::{
    MERGE_APPLIES_SKIPPED_REPLAY_TOTAL, MERGE_LEAVES_DROPPED_TOTAL,
};
use crate::stage1::key::{LeafStateKey, Stage1Key};
use crate::stage1::state::StatefulRecord;
use crate::stage1::transition::LeafTransition;
use crate::store::{CohortStore, IndexOp, MergeAppliedKey, PersonIndexKey, StoreError};
use crate::sweep::EvictionQueue;
use crate::workers::event_path::schedule_deadline;

/// The result of applying a transfer.
#[derive(Debug, Clone, PartialEq)]
pub enum ApplyOutcome {
    /// The transfer was applied; `transitions` are P_new's per-leaf flips (the caller composes Stage 2
    /// + produces them).
    Applied { transitions: Vec<LeafTransition> },
    /// A `cf_merge_applied` hit — this transfer message was already applied (replay / crash-recovery),
    /// so it is a no-op (acceptance #4 / #7).
    AlreadyApplied,
}

/// Apply `transfer` on P_new's worker (`partition_id` owns P_new). `transfer_coords` is the transfer
/// message's own Kafka `(partition, offset)`, keying `cf_merge_applied` for replay idempotence.
pub fn handle_transfer(
    partition_id: u16,
    store: &CohortStore,
    filters: &TeamFilters,
    transfer: &MergeStateTransfer,
    transfer_coords: (i32, i64),
    queue: &mut EvictionQueue<Stage1Key>,
) -> Result<ApplyOutcome, StoreError> {
    let team_u64 = transfer.team_id as u64;
    let new_person = transfer.new_person_uuid;
    let old_person = transfer.old_person_uuid;

    let applied_key = MergeAppliedKey {
        partition_id,
        team_id: team_u64,
        new_person,
        transfer_partition: transfer_coords.0,
        transfer_offset: transfer_coords.1,
    };
    if store.get_merge_applied(&applied_key)?.is_some() {
        counter!(MERGE_APPLIES_SKIPPED_REPLAY_TOTAL).increment(1);
        return Ok(ApplyOutcome::AlreadyApplied);
    }

    // Decode the hex LSK on each leaf; a malformed one is a counted skip (the wire is our own, so this
    // is purely defensive).
    let mut leaves: Vec<(LeafStateKey, StatefulRecord)> = Vec::with_capacity(transfer.leaves.len());
    for leaf in &transfer.leaves {
        match leaf.decode_leaf_state_key() {
            Some(lsk) => leaves.push((lsk, leaf.record.clone())),
            None => {
                counter!(MERGE_LEAVES_DROPPED_TOTAL, "reason" => "leaf_hex").increment(1);
            }
        }
    }

    let apply = apply_leaves(
        partition_id,
        store,
        filters,
        transfer.team_id,
        old_person,
        new_person,
        &leaves,
    )?;

    // One atomic batch: merged P_new puts + index appends + the applied marker. The stamp is the merge
    // instant (deterministic, no wall clock); the key's presence is the idempotence guard.
    let p_new_index = PersonIndexKey {
        partition_id,
        team_id: team_u64,
        person_id: new_person,
    };
    let stamp = ApplyStamp {
        applied_at_ms: transfer.merged_at_ms,
    };
    store.write_batch(|batch| {
        for (key, bytes) in &apply.puts {
            batch.put_stage1(key, bytes);
        }
        for lsk in &apply.appends {
            batch.merge_person_index(&p_new_index, IndexOp::Append(*lsk));
        }
        batch.put_merge_applied(&applied_key, &stamp.encode());
    })?;

    // Post-commit: schedule P_new's merged deadlines, mirroring the event path's ordering.
    for (key, deadline) in &apply.schedules {
        queue.schedule(*key, *deadline);
    }

    Ok(ApplyOutcome::Applied {
        transitions: apply.transitions,
    })
}

/// The writes one application of P_old's leaves into P_new produces, computed without committing so
/// the caller composes the final batch (the apply handler, or the drain's same-partition fast path).
#[derive(Debug, Default)]
pub(crate) struct LeafApply {
    /// P_new's merged `cf_stage1` records to put (`(key, encoded)`).
    pub puts: Vec<(Stage1Key, Vec<u8>)>,
    /// LSKs to append to P_new's `cf_person_index` (one per written leaf; the merge operator dedups).
    pub appends: Vec<LeafStateKey>,
    /// P_new's per-leaf membership flips, for the caller to fan into Stage 2 + the output producer.
    pub transitions: Vec<LeafTransition>,
    /// P_new's behavioral eviction deadlines to (re)schedule, post-commit.
    pub schedules: Vec<(Stage1Key, i64)>,
}

/// Merge each of P_old's `leaves` into P_new's state on `partition_new`, reading P_new's prior record
/// per leaf. Pure reads — emits no writes, so both the apply handler and the drain fast path call it
/// before composing their own batch (the "all reads before any write" discipline). A leaf whose LSK
/// left the catalog is a counted skip; a corrupt P_new record is treated as absent (re-created).
pub(crate) fn apply_leaves(
    partition_new: u16,
    store: &CohortStore,
    filters: &TeamFilters,
    team_id: i32,
    old_person: Uuid,
    new_person: Uuid,
    leaves: &[(LeafStateKey, StatefulRecord)],
) -> Result<LeafApply, StoreError> {
    let team_u64 = team_id as u64;
    let mut out = LeafApply::default();

    for (lsk, old_record) in leaves {
        let Some(meta) = filters.by_lsk.get(lsk) else {
            // The leaf left the catalog mid-flight (drift) — drop it, mirroring the sweep.
            counter!(MERGE_LEAVES_DROPPED_TOTAL, "reason" => "leaf_drift").increment(1);
            continue;
        };
        let p_new_key = Stage1Key {
            partition_id: partition_new,
            team_id: team_u64,
            leaf_state_key: *lsk,
            person_id: new_person,
        };
        let p_new_record = match store.get_stage1(&p_new_key)? {
            None => None,
            // A corrupt P_new record reads as absent: the merge re-creates it from P_old's side.
            Some(bytes) => StatefulRecord::decode(&bytes).ok(),
        };

        let merged = merge_records(
            old_person,
            old_record,
            p_new_record.as_ref(),
            meta,
            filters.timezone,
        );

        if let Some(record) = merged.record {
            if let Some(deadline) = schedule_deadline(&record.state) {
                out.schedules.push((p_new_key, deadline));
            }
            out.puts.push((p_new_key, record.encode()));
            out.appends.push(*lsk);
        }
        if let Some(kind) = merged.flip {
            out.transitions.push(LeafTransition {
                team_id: TeamId(team_id),
                leaf_state_key: *lsk,
                person_id: new_person,
                condition_hash: meta.condition_hash,
                kind,
            });
        }
    }

    Ok(out)
}
