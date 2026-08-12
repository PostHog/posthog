//! Apply a `MergeStateTransfer` on P_new's worker (phase 2 of cross-partition merge).
//!
//! Given a transfer (P_old's drained per-leaf records), merges each leaf into P_new's state, commits
//! one atomic `WriteBatch` (merged puts and the `cf_merge_applied` idempotence marker), schedules
//! P_new's eviction deadlines, and returns the membership transitions for the caller to compose Stage
//! 2 and produce.
//!
//! Before applying, the target `new_person_uuid` is resolved through the local slice's tombstones:
//! in a chained merge `A → B → C` where `B → C` drained before `A → B` applies, P_new (= B) is
//! already tombstoned, so applying A's state into B would strand it. Resolving the target sends A's
//! state to the live survivor instead — inline when the survivor co-resides on this partition,
//! forwarded on `cohort_merge_state_transfer` when it lives on another.

use std::collections::BTreeMap;

use metrics::counter;
use uuid::Uuid;

use crate::filters::reverse_index::TeamFilters;
use crate::filters::{CohortId, TeamId};
use crate::merge::rules::merge_records;
use crate::merge::tombstone_redirect::{resolve, Resolution};
use crate::merge::transfer::{
    ApplyStamp, MergeStateTransfer, TransferMembershipRegister, TransferMembershipRegisterKind,
    TransferredRegisterProvenance,
};
use crate::observability::metrics::{
    MERGE_APPLIES_SKIPPED_REPLAY_TOTAL, MERGE_FORWARD_HOP_CAPPED_TOTAL, MERGE_LEAVES_DROPPED_TOTAL,
    MERGE_TRANSFER_FORWARDS_TOTAL,
};
use crate::stage1::key::LeafStateKey;
use crate::stage1::person_record::{PersonDedup, PersonRecord};
use crate::stage1::state::StatefulRecord;
use crate::stage1::transition::LeafTransition;
use crate::stage2::{
    leaf_membership, single_leaf_register_writes, MembershipRegisterSource, Stage2State,
};
use crate::store::{
    Behavioral, BehavioralKey, CohortStore, MergeAppliedKey, PersonPrefix, PersonRecords,
    Stage2Key, Stage2TransferredRegisterKey, StoreError,
};
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
    pub cancels: Vec<BehavioralKey>,
    pub schedules: Vec<(BehavioralKey, i64)>,
}

impl QueueEffects {
    /// Cancel first, then schedule. The two key sets are disjoint by construction (old person ≠ new
    /// person), so the order is defensive.
    pub fn apply_to(&self, queue: &mut EvictionQueue<BehavioralKey>) {
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
// `CohortStore` I/O (and that of `apply_into`/`apply_leaves`/`merge_person_records`) is already off
// the runtime threads.
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
/// commit the merged puts + the `cf_merge_applied` marker keyed by `target`, schedule deadlines, and
/// return the survivor's transitions. For the `NotMerged` case `target` is just `new_person_uuid`.
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

    // Fold P_old's person-record dedup into the target's record: a present record absorbs P_old as an
    // ancestor; an absent or corrupt one writes nothing.
    let target_prefix = PersonPrefix::new(partition_id, team_u64, target);
    let record_put = match &transfer.person_dedup {
        Some(dedup) => merge_person_records(store, &target_prefix, old_person, dedup)?,
        None => None,
    };

    let stamp = ApplyStamp {
        applied_at_ms: transfer.merged_at_ms,
    };
    let fallback_register_writes = missing_transferred_register_writes(
        partition_id,
        store,
        filters,
        transfer.team_id,
        target,
        &transfer.membership_registers,
        transfer.merged_at_ms,
    )?;
    store.write_batch(|batch| {
        for write in &fallback_register_writes {
            if let Some(state) = &write.state {
                batch.put_stage2(&write.key, &state.encode_transferred_fallback());
            }
            if let Some(provenance) = &write.provenance {
                batch.put_stage2_transferred_register(
                    &Stage2TransferredRegisterKey::new(write.key),
                    &provenance.encode(),
                );
            }
        }
        for leaf in &apply.puts {
            batch.put::<Behavioral>(&leaf.key, &leaf.bytes);
            for write in single_leaf_register_writes(
                filters,
                MembershipRegisterSource {
                    partition_id,
                    team_id: TeamId(transfer.team_id),
                    person_id: target,
                    leaf_state_key: leaf.key.lsk(),
                },
                leaf.in_cohort,
                transfer.merged_at_ms,
            ) {
                batch.put_stage2(&write.key, &write.state.encode());
            }
        }
        if let Some(bytes) = &record_put {
            batch.put::<PersonRecords>(&target_prefix.record_key(), bytes);
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

/// Merge P_old's person-record dedup into the target's record, returning the encoded record to put or
/// `None` to write nothing. A present target record absorbs P_old as an ancestor (idempotent under
/// redelivery). A target with no record — or a corrupt one — writes nothing: the person re-evaluates
/// lazily on their next event.
#[allow(clippy::disallowed_methods)]
pub(crate) fn merge_person_records(
    store: &CohortStore,
    target_prefix: &PersonPrefix,
    old_person: Uuid,
    dedup: &PersonDedup,
) -> Result<Option<Vec<u8>>, StoreError> {
    let bytes = store.get_person_record(&target_prefix.record_key())?;
    let Some(bytes) = bytes else {
        return Ok(None);
    };
    match PersonRecord::decode(&bytes) {
        Ok(mut record) => {
            record.absorb_ancestor(old_person, dedup);
            Ok(Some(record.encode()))
        }
        Err(_) => {
            // Corrupt target record: count and write nothing rather than clobbering it.
            counter!(MERGE_LEAVES_DROPPED_TOTAL, "reason" => "target_record_decode").increment(1);
            Ok(None)
        }
    }
}

/// One merge-carried register settlement. The logical state and person-first provenance are
/// fill-only. A decoded existing state may be rewritten only to mark its ownership as transferred,
/// preserving its bit and timestamp so a later receiver evaluation can settle the provenance.
pub(crate) struct TransferredRegisterWrite {
    pub key: Stage2Key,
    pub state: Option<Stage2State>,
    pub provenance: Option<TransferredRegisterProvenance>,
}

/// Fill only missing survivor rows from transferred membership registers. A recognized receiver
/// shape chooses the conservative local bit (so a real single-leaf-to-composable edit starts false);
/// otherwise the self-describing wire kind does. Source kind + bit remain in person-first provenance
/// for another catalogless hop. Applied leaf evaluation remains authoritative and is staged later.
#[allow(clippy::too_many_arguments, clippy::disallowed_methods)]
pub(crate) fn missing_transferred_register_writes(
    partition_id: u16,
    store: &CohortStore,
    filters: &TeamFilters,
    team_id: i32,
    person_id: Uuid,
    registers: &[TransferMembershipRegister],
    last_evaluated_at_ms: i64,
) -> Result<Vec<TransferredRegisterWrite>, StoreError> {
    let registers_by_cohort: BTreeMap<CohortId, TransferMembershipRegister> = registers
        .iter()
        .map(|register| (CohortId(register.cohort_id), *register))
        .collect();
    let keys: Vec<Stage2Key> = registers_by_cohort
        .keys()
        .map(|cohort_id| Stage2Key {
            partition_id,
            team_id: team_id as u64,
            cohort_id: cohort_id.0 as u64,
            person_id,
        })
        .collect();
    let existing = store.multi_get_stage2(&keys)?;
    let inventory_keys: Vec<Stage2TransferredRegisterKey> = keys
        .iter()
        .copied()
        .map(Stage2TransferredRegisterKey::new)
        .collect();
    let existing_provenance = store.multi_get_stage2_transferred_registers(&inventory_keys)?;

    Ok(keys
        .into_iter()
        .zip(registers_by_cohort.into_values())
        .zip(existing)
        .zip(existing_provenance)
        .map(|(((key, register), existing), existing_provenance)| {
            let receiver_kind =
                TransferMembershipRegisterKind::from_filters(filters, CohortId(register.cohort_id));
            let primary_missing = existing.is_none();
            let existing_state = existing
                .as_deref()
                .and_then(|bytes| Stage2State::decode(bytes).ok());
            let existing_bit = existing_state.as_ref().map(|state| state.in_cohort);
            let materialized_kind = receiver_kind.unwrap_or(register.kind);
            let install_existing_provenance =
                !primary_missing && existing_provenance.is_none() && receiver_kind.is_none();
            let state = if primary_missing {
                Some(Stage2State {
                    in_cohort: materialized_kind.materialized_bit(register.in_cohort),
                    last_evaluated_at_ms,
                })
            } else if install_existing_provenance {
                // A corrupt primary has no fill-only bit to preserve. Repair it with the same
                // conservative source fallback used for a missing catalogless primary.
                Some(existing_state.unwrap_or(Stage2State {
                    in_cohort: register.kind.materialized_bit(register.in_cohort),
                    last_evaluated_at_ms,
                }))
            } else {
                None
            };
            let provenance = (primary_missing || install_existing_provenance).then(|| {
                let source = TransferMembershipRegister {
                    // The survivor's existing primary is fill-only and therefore owns the bit. The
                    // incoming register supplies only the otherwise-unavailable kind clue.
                    in_cohort: existing_bit.unwrap_or(register.in_cohort),
                    ..register
                };
                let encoded_state = state.as_ref().map(Stage2State::encode_transferred_fallback);
                let expected_primary = encoded_state.as_deref().expect(
                    "installing provenance always materializes explicit fallback ownership",
                );
                TransferredRegisterProvenance::new(source, expected_primary)
            });
            TransferredRegisterWrite {
                key,
                state,
                // Fill-only applies to provenance too: an existing survivor inventory wins. If
                // neither inventory nor catalog can enumerate an existing row, the incoming
                // source is the only safe person-first provenance to install.
                provenance,
            }
        })
        .collect())
}

/// Computed writes from applying P_old's leaves into P_new, uncommitted so the caller can compose
/// the final batch.
#[derive(Debug, Default)]
pub(crate) struct LeafApply {
    pub puts: Vec<AppliedLeafWrite>,
    pub transitions: Vec<LeafTransition>,
    pub schedules: Vec<(BehavioralKey, i64)>,
}

/// One survivor leaf write coupled to the membership derived from those exact post-merge bytes.
#[derive(Debug)]
pub(crate) struct AppliedLeafWrite {
    pub key: BehavioralKey,
    pub bytes: Vec<u8>,
    pub in_cohort: bool,
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
    let p_new_keys: Vec<BehavioralKey> = leaves
        .iter()
        .map(|(lsk, _)| BehavioralKey::new(partition_new, team_u64, new_person, *lsk))
        .collect();
    let p_new_raw = store.multi_get_behavioral(&p_new_keys)?;

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
            out.puts.push(AppliedLeafWrite {
                key: p_new_key,
                bytes: record.encode(),
                in_cohort: leaf_membership(Some(&record.state), meta),
            });
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
