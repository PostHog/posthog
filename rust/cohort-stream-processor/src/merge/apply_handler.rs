//! Apply a `MergeStateTransfer` on P_new's worker (phase 2 of cross-partition merge).
//!
//! Given a transfer (P_old's drained per-leaf records), merges each leaf into P_new's state, commits
//! one atomic `WriteBatch` (merged puts, `cf_person_index` appends, and the `cf_merge_applied`
//! idempotence marker), schedules P_new's eviction deadlines, and returns the membership transitions
//! for the caller to compose Stage 2 and produce.
//!
//! Before applying, the target `new_person_uuid` is resolved through the local slice's tombstones:
//! in a chained merge `A → B → C` where `B → C` drained before `A → B` applies, P_new (= B) is
//! already tombstoned, so applying A's state into B would strand it. Resolving the target sends A's
//! state to the live survivor instead — inline when the survivor co-resides on this partition,
//! forwarded on `cohort_merge_state_transfer` when it lives on another.

use metrics::counter;
use uuid::Uuid;

use crate::filters::reverse_index::TeamFilters;
use crate::filters::TeamId;
use crate::merge::rules::merge_records;
use crate::merge::tombstone_redirect::{resolve, Resolution};
use crate::merge::transfer::{ApplyStamp, MergeStateTransfer};
use crate::observability::metrics::{
    MERGE_APPLIES_SKIPPED_REPLAY_TOTAL, MERGE_FORWARD_HOP_CAPPED_TOTAL, MERGE_LEAVES_DROPPED_TOTAL,
    MERGE_TRANSFER_FORWARDS_TOTAL,
};
use crate::stage1::key::{LeafStateKey, Stage1Key};
use crate::stage1::state::StatefulRecord;
use crate::stage1::transition::LeafTransition;
use crate::store::{CohortStore, IndexOp, MergeAppliedKey, PersonIndexKey, StoreError};
use crate::sweep::EvictionQueue;
use crate::workers::event_path::schedule_deadline;
use tracing::warn;

/// The eviction-queue mutations a drain/apply commit implies. The handlers take owned inputs and no
/// queue borrow, so they hand these back for the caller (which owns the queue) to apply after the
/// atomic write commits and before any produce — a produce failure must never leave the queue ahead
/// of the store. `cancels` are the old person's now-deleted keys; `schedules` the survivor's new
/// eviction deadlines.
#[must_use]
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct QueueEffects {
    pub cancels: Vec<Stage1Key>,
    pub schedules: Vec<(Stage1Key, i64)>,
}

impl QueueEffects {
    /// Cancel first, then schedule. The two key sets are disjoint by construction (old person ≠ new
    /// person), so the order is defensive.
    pub fn apply_to(&self, queue: &mut EvictionQueue<Stage1Key>) {
        for key in &self.cancels {
            queue.cancel(key);
        }
        for &(key, deadline) in &self.schedules {
            queue.schedule(key, deadline);
        }
    }
}

/// Bound on cross-partition transfer-forward hops (`forward_hops` on the wire). Mirrors the
/// event-path [`crate::merge::tombstone_redirect::MAX_CROSS_PARTITION_REDIRECT_HOPS`] — prevents
/// infinite re-production between partitions in case of a corrupt cross-partition tombstone cycle.
pub const MAX_TRANSFER_FORWARD_HOPS: u8 = 8;

#[derive(Debug, Clone, PartialEq)]
pub enum ApplyOutcome {
    /// Transfer applied; `transitions` are the resolved survivor's per-leaf membership flips.
    /// `effects` carries the survivor's eviction schedules for the caller to apply to its queue.
    Applied {
        transitions: Vec<LeafTransition>,
        effects: QueueEffects,
    },
    /// Idempotence hit — this transfer was already applied (replay / crash-recovery).
    AlreadyApplied,
    /// `new_person_uuid` is tombstoned to a survivor on a different partition. The caller forwards
    /// `transfer` (already rewritten to the survivor, `forward_hops` incremented) on the transfer
    /// topic. No state and no marker are written here — redelivery re-resolves and re-produces, and
    /// the final target's marker is the dedup (the same ReKey posture the straggler re-key uses).
    Forward { transfer: Box<MergeStateTransfer> },
    /// The forward hop cap was hit (a corrupt tombstone cycle). No state written; the caller marks
    /// the offset so the partition does not wedge. Never expected in a clean system.
    HopCapped,
}

/// Apply `transfer` on the worker that owns `transfer.new_person_uuid` (`partition_id`).
///
/// Idempotence is keyed by the *source merge message's* coordinates (not the transfer message's
/// own), because duplicate transfer copies (redrive, crash-retry, forward) arrive at fresh
/// transfer-topic offsets but share the same source pair.
///
/// `partition_count` is the live co-partitioned topic count (production 64; test lanes lower it):
/// the forward-vs-inline target resolution turns on whether the survivor hashes onto `partition_id`
/// under this count, so it must match the deploy's topology.
// Sync apply core; runs on the blocking pool inside `StoreHandle::run_section`, so its direct
// `CohortStore` I/O (and that of `apply_into`/`apply_leaves`) is already off the runtime threads.
#[allow(clippy::disallowed_methods)]
pub fn handle_transfer(
    partition_id: u16,
    store: &CohortStore,
    filters: &TeamFilters,
    transfer: &MergeStateTransfer,
    _transfer_coords: (i32, i64),
    partition_count: u32,
) -> Result<ApplyOutcome, StoreError> {
    let team_id = transfer.team_id;
    let team_u64 = team_id as u64;
    let new_person = transfer.new_person_uuid;

    // Original-target idempotence: absorbs the ordered-case redelivery (marker written under B
    // before B was tombstoned), before the chain is resolved.
    if store
        .get_merge_applied(&applied_key(partition_id, team_u64, new_person, transfer))?
        .is_some()
    {
        counter!(MERGE_APPLIES_SKIPPED_REPLAY_TOTAL).increment(1);
        return Ok(ApplyOutcome::AlreadyApplied);
    }

    // Resolve the target through the local slice: if P_new is itself tombstoned (the raced chain),
    // the state belongs to the survivor, not to the drained P_new.
    match resolve(
        store,
        partition_id,
        TeamId(team_id),
        new_person,
        partition_count,
    )? {
        Resolution::NotMerged => apply_into(partition_id, store, filters, transfer, new_person),
        Resolution::Inline { final_person, .. } => {
            counter!(MERGE_TRANSFER_FORWARDS_TOTAL, "path" => "inline").increment(1);
            apply_into(partition_id, store, filters, transfer, final_person)
        }
        Resolution::CrossPartition { target_person, .. } => {
            if transfer.forward_hops >= MAX_TRANSFER_FORWARD_HOPS {
                counter!(MERGE_FORWARD_HOP_CAPPED_TOTAL).increment(1);
                warn!(
                    partition_id,
                    team_id,
                    new_person = %new_person,
                    target_person = %target_person,
                    forward_hops = transfer.forward_hops,
                    "transfer forward hit the hop cap; dropping and marking the offset (corrupt tombstone cycle)",
                );
                return Ok(ApplyOutcome::HopCapped);
            }
            let mut forwarded = transfer.clone();
            forwarded.new_person_uuid = target_person;
            forwarded.forward_hops = transfer.forward_hops + 1;
            Ok(ApplyOutcome::Forward {
                transfer: Box::new(forwarded),
            })
        }
    }
}

/// The `cf_merge_applied` key for `target` under this merge's source coordinates.
fn applied_key(
    partition_id: u16,
    team_u64: u64,
    target: Uuid,
    transfer: &MergeStateTransfer,
) -> MergeAppliedKey {
    MergeAppliedKey {
        partition_id,
        team_id: team_u64,
        new_person: target,
        source_partition: transfer.source_partition,
        source_offset: transfer.source_offset,
    }
}

/// Apply `transfer`'s leaves into `target` (the resolved survivor, co-resident on `partition_id`),
/// commit the merged puts + person-index appends + the `cf_merge_applied` marker keyed by `target`,
/// schedule deadlines, and return the survivor's transitions. For the `NotMerged` case `target` is
/// just `new_person_uuid`.
#[allow(clippy::disallowed_methods)]
fn apply_into(
    partition_id: u16,
    store: &CohortStore,
    filters: &TeamFilters,
    transfer: &MergeStateTransfer,
    target: Uuid,
) -> Result<ApplyOutcome, StoreError> {
    let team_u64 = transfer.team_id as u64;
    let old_person = transfer.old_person_uuid;

    // A forwarded copy may already have applied under the survivor at these source coords.
    let target_applied_key = applied_key(partition_id, team_u64, target, transfer);
    if target != transfer.new_person_uuid && store.get_merge_applied(&target_applied_key)?.is_some()
    {
        counter!(MERGE_APPLIES_SKIPPED_REPLAY_TOTAL).increment(1);
        return Ok(ApplyOutcome::AlreadyApplied);
    }

    let mut leaves: Vec<(LeafStateKey, StatefulRecord)> = Vec::with_capacity(transfer.leaves.len());
    for leaf in &transfer.leaves {
        match leaf.decode_leaf_state_key() {
            Some(lsk) => leaves.push((lsk, leaf.record.clone())),
            None => {
                counter!(MERGE_LEAVES_DROPPED_TOTAL, "reason" => "leaf_hex").increment(1);
            }
        }
    }

    // `old_person` stays as the transfer's original P_old so `compose_ancestor_dedup` registers it
    // as the ancestor of `target`, keeping the dedup chain walkable.
    let apply = apply_leaves(
        partition_id,
        store,
        filters,
        transfer.team_id,
        old_person,
        target,
        &leaves,
    )?;

    let target_index = PersonIndexKey {
        partition_id,
        team_id: team_u64,
        person_id: target,
    };
    let stamp = ApplyStamp {
        applied_at_ms: transfer.merged_at_ms,
    };
    store.write_batch(|batch| {
        for (key, bytes) in &apply.puts {
            batch.put_stage1(key, bytes);
        }
        for lsk in &apply.appends {
            batch.merge_person_index(&target_index, IndexOp::Append(*lsk));
        }
        batch.put_merge_applied(&target_applied_key, &stamp.encode());
        // Fixed-origin dedup: also stamp under the original `new_person_uuid` when the chain
        // retargeted (`target != new_person_uuid`). `new_person_uuid` is the one identity stable
        // across every redelivery of this merge's transfer, so a redelivered copy whose chain has
        // since extended further (C → D → …) hits the `handle_transfer` original-target probe and
        // dedups — even though the resolved-target marker now sits under a later survivor, not under
        // this `target`. Closes the same-partition raced-then-extended double-apply. One extra put,
        // atomic with the leaf writes and the target marker.
        //
        // Residual: a chain that later extends to a survivor on *another* partition still misses —
        // `cf_merge_applied` markers are partition-local and the cross-partition `Forward` path
        // writes none here. Bounded by `MAX_TRANSFER_FORWARD_HOPS` (short chains ⇒ rare); fully
        // closing it needs marker-forwarding during drain (deferred).
        if target != transfer.new_person_uuid {
            let original_key =
                applied_key(partition_id, team_u64, transfer.new_person_uuid, transfer);
            batch.put_merge_applied(&original_key, &stamp.encode());
        }
    })?;

    Ok(ApplyOutcome::Applied {
        transitions: apply.transitions,
        effects: QueueEffects {
            cancels: Vec::new(),
            schedules: apply.schedules,
        },
    })
}

/// Computed writes from applying P_old's leaves into P_new, uncommitted so the caller can compose
/// the final batch.
#[derive(Debug, Default)]
pub(crate) struct LeafApply {
    pub puts: Vec<(Stage1Key, Vec<u8>)>,
    pub appends: Vec<LeafStateKey>,
    pub transitions: Vec<LeafTransition>,
    pub schedules: Vec<(Stage1Key, i64)>,
}

/// Merge each of P_old's `leaves` into P_new's state on `partition_new`. Pure reads only — the
/// caller composes the final write batch. A leaf whose LSK left the catalog is skipped; a corrupt
/// P_new record is treated as absent.
#[allow(clippy::disallowed_methods)]
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

    // One batched read of every leaf's `p_new` state. Keys are built in `leaves` order so the zip
    // below stays aligned; a leaf later skipped by the drift check simply ignores its result.
    let p_new_keys: Vec<Stage1Key> = leaves
        .iter()
        .map(|(lsk, _)| Stage1Key {
            partition_id: partition_new,
            team_id: team_u64,
            leaf_state_key: *lsk,
            person_id: new_person,
        })
        .collect();
    let p_new_raw = store.multi_get_stage1(&p_new_keys)?;

    for ((lsk, old_record), (p_new_key, p_new_bytes)) in
        leaves.iter().zip(p_new_keys.into_iter().zip(p_new_raw))
    {
        let Some(meta) = filters.by_lsk.get(lsk) else {
            counter!(MERGE_LEAVES_DROPPED_TOTAL, "reason" => "leaf_drift").increment(1);
            continue;
        };
        let p_new_record = match p_new_bytes {
            None => None,
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
