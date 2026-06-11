//! Apply a `MergeStateTransfer` on P_new's worker (phase 2 of cross-partition merge).
//!
//! Given a transfer (P_old's drained per-leaf records), merges each leaf into P_new's state, commits
//! one atomic `WriteBatch` (merged puts, `cf_person_index` appends, and the `cf_merge_applied`
//! idempotence marker), schedules P_new's eviction deadlines, and returns the membership transitions
//! for the caller to compose Stage 2 and produce.

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

#[derive(Debug, Clone, PartialEq)]
pub enum ApplyOutcome {
    /// Transfer applied; `transitions` are P_new's per-leaf membership flips.
    Applied { transitions: Vec<LeafTransition> },
    /// Idempotence hit — this transfer was already applied (replay / crash-recovery).
    AlreadyApplied,
}

/// Apply `transfer` on P_new's worker (`partition_id` owns P_new).
///
/// Idempotence is keyed by the *source merge message's* coordinates (not the transfer message's
/// own), because duplicate transfer copies (redrive, crash-retry) arrive at fresh transfer-topic
/// offsets but share the same source pair.
pub fn handle_transfer(
    partition_id: u16,
    store: &CohortStore,
    filters: &TeamFilters,
    transfer: &MergeStateTransfer,
    _transfer_coords: (i32, i64),
    queue: &mut EvictionQueue<Stage1Key>,
) -> Result<ApplyOutcome, StoreError> {
    let team_u64 = transfer.team_id as u64;
    let new_person = transfer.new_person_uuid;
    let old_person = transfer.old_person_uuid;

    let applied_key = MergeAppliedKey {
        partition_id,
        team_id: team_u64,
        new_person,
        source_partition: transfer.source_partition,
        source_offset: transfer.source_offset,
    };
    if store.get_merge_applied(&applied_key)?.is_some() {
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

    let apply = apply_leaves(
        partition_id,
        store,
        filters,
        transfer.team_id,
        old_person,
        new_person,
        &leaves,
    )?;

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

    for (key, deadline) in &apply.schedules {
        queue.schedule(*key, *deadline);
    }

    Ok(ApplyOutcome::Applied {
        transitions: apply.transitions,
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
