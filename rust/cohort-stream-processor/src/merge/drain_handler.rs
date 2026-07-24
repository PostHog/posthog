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
//! range delete over its person prefix. P_old's `cf_stage2` keys are built from the catalog; when
//! register transfer is enabled ([`MembershipRegisterTransferMode`]) the existing membership rows
//! ride the cross-partition transfer so a no-op merge or catalog refresh cannot strand the survivor's
//! membership row. While it is disabled the drain ships leaves only.

use std::collections::BTreeMap;

use metrics::{counter, histogram};
use uuid::Uuid;

use crate::filters::reverse_index::TeamFilters;
use crate::filters::{CohortId, TeamId};
use crate::merge::apply_handler::{
    apply_leaves, merge_person_records, missing_transferred_register_writes, QueueEffects,
};
use crate::merge::tombstone_redirect::{resolve, Resolution};
use crate::merge::transfer::{
    DrainStamp, MergeStateTransfer, PendingTransfer, PersonMergeEvent, Tombstone, TransferLeaf,
    TransferMembershipRegister, TransferMembershipRegisterKind, TransferredRegisterProvenance,
};
use crate::observability::metrics::{
    MERGE_DRAINS_SKIPPED_REPLAY_TOTAL, MERGE_DRAIN_LEAVES_SCANNED, MERGE_HANDLED_TOTAL,
    MERGE_LEAVES_DROPPED_TOTAL, STAGE2_STATE_DECODE_ERROR,
};
use crate::partitions::partitioner::partition_of;
use crate::stage1::key::LeafStateKey;
use crate::stage1::person_record::{PersonDedup, PersonRecord};
use crate::stage1::state::StatefulRecord;
use crate::stage1::transition::LeafTransition;
use crate::stage2::{single_leaf_register_writes, MembershipRegisterSource, Stage2State};
use crate::store::{
    Behavioral, BehavioralKey, CohortStore, MergeDrainKey, PendingTransferKey, PersonPrefix,
    PersonRecords, Stage2Key, Stage2TransferredRegisterKey, Stage2TransferredRegisterPersonPrefix,
    StoreError, TombstoneKey,
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
    /// A transfer with no payload is not staged; the caller skips the produce and commits directly.
    /// `effects` cancels P_old's now-deleted keys (no schedules — the state left this partition).
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

/// Whether a cross-partition drain emits the additive membership-register payload.
///
/// Local register writes and receiver application are unconditional; only the sender is gated. While
/// the gate is off the drain carries no register bits: it transfers leaves only and never holds, so a
/// receiver that cannot apply the payload never sees one and merge consumption never stalls. P_new
/// re-derives its single-leaf registers locally from the transferred leaves; composable membership
/// falls back to lazy recompose on the survivor.
///
/// Once the gate is on the sender emits, and a receiver that does not understand `membership_registers`
/// (no `deny_unknown_fields`) silently drops it, deleting the survivor's only register row. So enable
/// the sender only once every pod can apply the transfer, and disable it before rolling the image back.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum MembershipRegisterTransferMode {
    Disabled,
    Enabled,
}

impl MembershipRegisterTransferMode {
    pub(crate) const fn from_enabled(enabled: bool) -> Self {
        if enabled {
            Self::Enabled
        } else {
            Self::Disabled
        }
    }

    const fn is_enabled(self) -> bool {
        matches!(self, Self::Enabled)
    }
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
    handle_merge_event_with_transfer_mode(
        partition_id,
        store,
        filters,
        event,
        msg_coords,
        partition_count,
        MembershipRegisterTransferMode::Enabled,
    )
}

/// Production entry with rollout-safe cross-partition register transfer.
#[allow(clippy::disallowed_methods)]
pub(crate) fn handle_merge_event_with_transfer_mode(
    partition_id: u16,
    store: &CohortStore,
    filters: &TeamFilters,
    event: &PersonMergeEvent,
    msg_coords: (i32, i64),
    partition_count: u32,
    register_transfer_mode: MembershipRegisterTransferMode,
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
    let transferred_inventory = store.scan_stage2_transferred_registers(
        Stage2TransferredRegisterPersonPrefix::new(partition_id, team_u64, old_person),
    )?;
    let old_transferred_register_keys: Vec<Stage2TransferredRegisterKey> = transferred_inventory
        .iter()
        .map(|(key, _value)| *key)
        .collect();
    let registering_cohorts = collect_registering_cohorts(filters, &transferred_inventory);
    let old_stage2_keys: Vec<Stage2Key> = registering_cohorts
        .iter()
        .map(|(cohort_id, _source)| Stage2Key {
            partition_id,
            team_id: team_u64,
            cohort_id: cohort_id.0 as u64,
            person_id: old_person,
        })
        .collect();
    // Gate off ⇒ carry no register bits (see [`MembershipRegisterTransferMode`]): the drain still
    // reclaims P_old's own register rows below but ships leaves only, so the read is skipped.
    let old_membership_registers = if register_transfer_mode.is_enabled() {
        read_membership_registers(store, &registering_cohorts, &old_stage2_keys)?
    } else {
        Vec::new()
    };

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
            &old_transferred_register_keys,
            &old_membership_registers,
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
        &old_transferred_register_keys,
        old_membership_registers,
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
    old_transferred_register_keys: &[Stage2TransferredRegisterKey],
    old_membership_registers: &[TransferMembershipRegister],
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
    let fallback_register_writes = missing_transferred_register_writes(
        partition_id,
        store,
        filters,
        event.team_id,
        effective_new_person,
        old_membership_registers,
        event.merged_at_ms,
    )?;
    store.write_batch(|batch| {
        batch.delete_behavioral_prefix(old_prefix);
        batch.delete::<PersonRecords>(&old_prefix.record_key());
        for key in old_stage2_keys {
            batch.delete_stage2(key);
        }
        for key in old_transferred_register_keys {
            batch.delete_stage2_transferred_register(key);
        }
        batch.put_tombstone(tombstone_key, &tombstone.encode());
        batch.put_merge_drain_applied(drain_key, &drain_stamp.encode());
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
                    team_id: TeamId(event.team_id),
                    person_id: effective_new_person,
                    leaf_state_key: leaf.key.lsk(),
                },
                leaf.in_cohort,
                event.merged_at_ms,
            ) {
                batch.put_stage2(&write.key, &write.state.encode());
            }
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
    old_transferred_register_keys: &[Stage2TransferredRegisterKey],
    old_membership_registers: Vec<TransferMembershipRegister>,
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
        membership_registers: old_membership_registers,
        forward_hops: 0,
        person_dedup,
    };
    // Stage iff the transfer carries state. A truly empty transfer is never staged — a duplicate
    // merge event at fresh coordinates could overwrite a still-pending, never-produced transfer.
    let pending = transfer.has_payload().then(|| PendingTransfer {
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
        for key in old_transferred_register_keys {
            batch.delete_stage2_transferred_register(key);
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

/// The team's cohorts that persist membership in `cf_stage2`, coupled to the source semantics a
/// receiver needs when its own catalog is missing or stale.
fn membership_registering_cohorts(
    filters: &TeamFilters,
) -> impl Iterator<Item = (CohortId, TransferMembershipRegisterKind)> + '_ {
    filters.eligibility.keys().filter_map(|&cohort_id| {
        TransferMembershipRegisterKind::from_filters(filters, cohort_id)
            .map(|kind| (cohort_id, kind))
    })
}

#[derive(Debug, Clone)]
struct DrainRegisterSource {
    catalog_kind: Option<TransferMembershipRegisterKind>,
    provenance: Option<TransferredRegisterProvenance>,
}

/// Assemble the cohorts whose `cf_stage2` register P_old may carry across the merge: the team's
/// catalog-declared registering cohorts, unioned with any transferred-register inventory keyed on
/// P_old (which survives a stale or missing catalog). Decoded provenance refines each source; an
/// undecodable inventory row still proves a register exists, defaulting to the conservative
/// composable kind when neither the value nor the catalog can name it.
fn collect_registering_cohorts(
    filters: &TeamFilters,
    transferred_inventory: &[(Stage2TransferredRegisterKey, Vec<u8>)],
) -> Vec<(CohortId, DrainRegisterSource)> {
    let mut registering_cohorts: BTreeMap<CohortId, DrainRegisterSource> =
        membership_registering_cohorts(filters)
            .map(|(cohort_id, kind)| {
                (
                    cohort_id,
                    DrainRegisterSource {
                        catalog_kind: Some(kind),
                        provenance: None,
                    },
                )
            })
            .collect();
    for (key, value) in transferred_inventory {
        let Ok(cohort_id) = i32::try_from(key.stage2_key().cohort_id) else {
            counter!(MERGE_LEAVES_DROPPED_TOTAL, "reason" => "register_inventory_cohort")
                .increment(1);
            continue;
        };
        let source =
            registering_cohorts
                .entry(CohortId(cohort_id))
                .or_insert(DrainRegisterSource {
                    catalog_kind: None,
                    provenance: None,
                });
        match TransferredRegisterProvenance::decode(value) {
            Some(provenance) => source.provenance = Some(provenance),
            None => {
                counter!(MERGE_LEAVES_DROPPED_TOTAL, "reason" => "register_inventory_decode")
                    .increment(1);
                source
                    .catalog_kind
                    .get_or_insert(TransferMembershipRegisterKind::Composable);
            }
        }
    }
    registering_cohorts.into_iter().collect()
}

#[allow(clippy::disallowed_methods)]
fn read_membership_registers(
    store: &CohortStore,
    cohorts: &[(CohortId, DrainRegisterSource)],
    keys: &[Stage2Key],
) -> Result<Vec<TransferMembershipRegister>, StoreError> {
    debug_assert_eq!(cohorts.len(), keys.len());
    Ok(cohorts
        .iter()
        .zip(store.multi_get_stage2(keys)?)
        .filter_map(|((cohort_id, source), bytes)| {
            let bytes = bytes?;
            let active_provenance = source
                .provenance
                .as_ref()
                .filter(|provenance| provenance.matches_primary(&bytes));
            let kind = active_provenance
                .map(|provenance| provenance.kind)
                .or(source.catalog_kind)
                .or_else(|| source.provenance.as_ref().map(|provenance| provenance.kind))
                .unwrap_or(TransferMembershipRegisterKind::Composable);
            let materialized_bit = match Stage2State::decode(&bytes) {
                Ok(state) => Some(state.in_cohort),
                Err(_) => {
                    counter!(STAGE2_STATE_DECODE_ERROR).increment(1);
                    None
                }
            };
            Some(TransferMembershipRegister {
                cohort_id: cohort_id.0,
                // An exact fingerprint means the receiver has not evaluated this register since
                // transfer, so retain the source bit. Otherwise the current primary row wins.
                in_cohort: active_provenance
                    .map(|provenance| provenance.in_cohort)
                    .or(materialized_bit)
                    .unwrap_or(false),
                kind,
            })
        })
        .collect())
}

#[cfg(test)]
#[allow(clippy::disallowed_methods)]
mod tests {
    use super::*;
    use chrono_tz::UTC;
    use serde_json::{json, Value};
    use tempfile::TempDir;

    use crate::filters::TeamFiltersBuilder;
    use crate::merge::apply_handler::{handle_transfer, ApplyOutcome};
    use crate::partitions::partitioner::COHORT_PARTITION_COUNT;
    use crate::stage2::state::Stage2Ownership;
    use crate::stage2::CohortEligibility;
    use crate::store::StoreConfig;

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
    fn membership_registering_cohorts_enumerates_single_leaf_and_composable_classes() {
        let mut builder = TeamFiltersBuilder::default();
        // 2: single-leaf referent — writes its direct membership register.
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
        let mut ids: Vec<i32> = membership_registering_cohorts(&filters)
            .map(|(cohort_id, _kind)| cohort_id.0)
            .collect();
        ids.sort_unstable();
        assert_eq!(
            ids,
            vec![1, 2, 3],
            "all membership-registering classes are reclaimed for the merged-away person",
        );
    }

    #[test]
    fn membership_registering_cohorts_excludes_a_ref_cohort_when_the_gate_is_off() {
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

        let ids: Vec<i32> = membership_registering_cohorts(&filters)
            .map(|(cohort_id, _kind)| cohort_id.0)
            .collect();
        assert_eq!(
            ids,
            vec![2],
            "gate off excludes the ref cohort but retains its single-leaf referent's register",
        );
    }

    #[test]
    fn disabled_register_transfer_drains_leaves_only_and_carries_no_register_bits() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(CohortId(1), TeamId(7), &cohort(vec![behavioral(7)]))
            .unwrap();
        let filters = builder.freeze(UTC);
        let old_person = Uuid::from_u128(1);
        let old_partition = partition_of(TeamId(7), &old_person, COHORT_PARTITION_COUNT) as u16;
        let new_person = (2u128..)
            .map(Uuid::from_u128)
            .find(|person| {
                partition_of(TeamId(7), person, COHORT_PARTITION_COUNT) as u16 != old_partition
            })
            .unwrap();
        let register_key = Stage2Key {
            partition_id: old_partition,
            team_id: 7,
            cohort_id: 1,
            person_id: old_person,
        };
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();
        store
            .write_batch(|batch| {
                batch.put_stage2(
                    &register_key,
                    &Stage2State {
                        in_cohort: true,
                        last_evaluated_at_ms: 1,
                    }
                    .encode(),
                )
            })
            .unwrap();

        let outcome = handle_merge_event_with_transfer_mode(
            old_partition,
            &store,
            &filters,
            &PersonMergeEvent {
                team_id: 7,
                old_person_uuid: old_person,
                new_person_uuid: new_person,
                merged_at_ms: 2,
                schema_version: crate::merge::transfer::MERGE_EVENT_SCHEMA_VERSION,
            },
            (3, 4),
            COHORT_PARTITION_COUNT,
            MembershipRegisterTransferMode::Disabled,
        )
        .unwrap();

        let DrainOutcome::Drained { transfer, .. } = outcome else {
            panic!("a disabled cross-partition merge drains like the pre-register pipeline");
        };
        assert!(
            transfer.membership_registers.is_empty(),
            "gate off ships no register bits, so an old receiver never sees a payload it can't apply",
        );
        assert!(
            store.get_stage2(&register_key).unwrap().is_none(),
            "P_old's register row is reclaimed by the drain, like the pre-register pipeline",
        );
    }

    #[test]
    fn catalogless_existing_row_seeds_provenance_from_the_survivor_bit() {
        let person = Uuid::from_u128(1);
        let partition = partition_of(TeamId(7), &person, COHORT_PARTITION_COUNT) as u16;
        let key = Stage2Key {
            partition_id: partition,
            team_id: 7,
            cohort_id: 1,
            person_id: person,
        };
        let inventory = Stage2TransferredRegisterKey::new(key);
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();
        store
            .write_batch(|batch| {
                batch.put_stage2(
                    &key,
                    &Stage2State {
                        in_cohort: true,
                        last_evaluated_at_ms: 1,
                    }
                    .encode(),
                );
            })
            .unwrap();

        handle_transfer(
            partition,
            &store,
            &TeamFilters::default(),
            &MergeStateTransfer {
                team_id: 7,
                old_person_uuid: Uuid::from_u128(99),
                new_person_uuid: person,
                merged_at_ms: 2,
                source_partition: 3,
                source_offset: 4,
                leaves: Vec::new(),
                membership_registers: vec![TransferMembershipRegister {
                    cohort_id: 1,
                    in_cohort: false,
                    kind: TransferMembershipRegisterKind::SingleLeafBehavioral,
                }],
                forward_hops: 0,
                person_dedup: None,
            },
            (partition.into(), 5),
            COHORT_PARTITION_COUNT,
        )
        .unwrap();

        assert!(
            Stage2State::decode(&store.get_stage2(&key).unwrap().unwrap())
                .unwrap()
                .in_cohort
        );
        assert_eq!(
            TransferredRegisterProvenance::decode(
                &store
                    .get_stage2_transferred_register(&inventory)
                    .unwrap()
                    .unwrap(),
            ),
            Some(TransferredRegisterProvenance::new(
                TransferMembershipRegister {
                    cohort_id: 1,
                    in_cohort: true,
                    kind: TransferMembershipRegisterKind::SingleLeafBehavioral,
                },
                &Stage2State {
                    in_cohort: true,
                    last_evaluated_at_ms: 1,
                }
                .encode_transferred_fallback(),
            )),
        );
    }

    #[test]
    fn catalogless_corrupt_existing_row_is_repaired_as_an_owned_fallback() {
        let person = Uuid::from_u128(1);
        let partition = partition_of(TeamId(7), &person, COHORT_PARTITION_COUNT) as u16;
        let key = Stage2Key {
            partition_id: partition,
            team_id: 7,
            cohort_id: 1,
            person_id: person,
        };
        let inventory = Stage2TransferredRegisterKey::new(key);
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();
        store
            .write_batch(|batch| batch.put_stage2(&key, b"corrupt"))
            .unwrap();

        let source_register = TransferMembershipRegister {
            cohort_id: 1,
            in_cohort: true,
            kind: TransferMembershipRegisterKind::Composable,
        };
        handle_transfer(
            partition,
            &store,
            &TeamFilters::default(),
            &MergeStateTransfer {
                team_id: 7,
                old_person_uuid: Uuid::from_u128(99),
                new_person_uuid: person,
                merged_at_ms: 2,
                source_partition: 3,
                source_offset: 4,
                leaves: Vec::new(),
                membership_registers: vec![source_register],
                forward_hops: 0,
                person_dedup: None,
            },
            (partition.into(), 5),
            COHORT_PARTITION_COUNT,
        )
        .unwrap();

        let primary = store.get_stage2(&key).unwrap().unwrap();
        assert_eq!(
            Stage2State::decode_with_ownership(&primary).unwrap(),
            (
                Stage2State {
                    in_cohort: false,
                    last_evaluated_at_ms: 2,
                },
                Stage2Ownership::TransferredFallback,
            ),
        );
        let provenance = TransferredRegisterProvenance::decode(
            &store
                .get_stage2_transferred_register(&inventory)
                .unwrap()
                .unwrap(),
        )
        .unwrap();
        assert_eq!(provenance.kind, source_register.kind);
        assert_eq!(provenance.in_cohort, source_register.in_cohort);
        assert!(provenance.matches_primary(&primary));
    }

    #[test]
    fn local_noop_stage2_update_supersedes_transfer_provenance_before_gc() {
        let old_person = Uuid::from_u128(1);
        let old_partition = partition_of(TeamId(7), &old_person, COHORT_PARTITION_COUNT) as u16;
        let new_person = (2u128..)
            .map(Uuid::from_u128)
            .find(|person| {
                partition_of(TeamId(7), person, COHORT_PARTITION_COUNT) as u16 != old_partition
            })
            .unwrap();
        let register_key = Stage2Key {
            partition_id: old_partition,
            team_id: 7,
            cohort_id: 1,
            person_id: old_person,
        };
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();
        let mut current_filters = TeamFilters::default();
        current_filters
            .eligibility
            .insert(CohortId(1), CohortEligibility::Stage2Composable);

        handle_transfer(
            old_partition,
            &store,
            &current_filters,
            &MergeStateTransfer {
                team_id: 7,
                old_person_uuid: Uuid::from_u128(99),
                new_person_uuid: old_person,
                merged_at_ms: 1,
                source_partition: 3,
                source_offset: 4,
                leaves: Vec::new(),
                membership_registers: vec![TransferMembershipRegister {
                    cohort_id: 1,
                    in_cohort: true,
                    kind: TransferMembershipRegisterKind::SingleLeafBehavioral,
                }],
                forward_hops: 0,
                person_dedup: None,
            },
            (old_partition.into(), 5),
            COHORT_PARTITION_COUNT,
        )
        .unwrap();

        store
            .write_batch(|batch| {
                batch.put_stage2(
                    &register_key,
                    &Stage2State {
                        in_cohort: false,
                        last_evaluated_at_ms: 1,
                    }
                    .encode(),
                );
            })
            .unwrap();

        let outcome = handle_merge_event_with_transfer_mode(
            old_partition,
            &store,
            &current_filters,
            &PersonMergeEvent {
                team_id: 7,
                old_person_uuid: old_person,
                new_person_uuid: new_person,
                merged_at_ms: 3,
                schema_version: crate::merge::transfer::MERGE_EVENT_SCHEMA_VERSION,
            },
            (old_partition.into(), 6),
            COHORT_PARTITION_COUNT,
            MembershipRegisterTransferMode::Enabled,
        )
        .unwrap();

        let DrainOutcome::Drained { transfer, .. } = outcome else {
            panic!("the ownership-settled register should drain");
        };
        assert_eq!(
            transfer.membership_registers,
            vec![TransferMembershipRegister {
                cohort_id: 1,
                in_cohort: false,
                kind: TransferMembershipRegisterKind::Composable,
            }],
            "removing only fallback ownership makes the current primary and catalog authoritative",
        );
    }

    #[test]
    fn catalogless_register_survives_a_stale_catalog_and_transfers_on_the_next_hop() {
        let middle_person = Uuid::from_u128(1);
        let middle_partition =
            partition_of(TeamId(7), &middle_person, COHORT_PARTITION_COUNT) as u16;
        let final_person = (2u128..)
            .map(Uuid::from_u128)
            .find(|person| {
                partition_of(TeamId(7), person, COHORT_PARTITION_COUNT) as u16 != middle_partition
            })
            .unwrap();
        let register_key = Stage2Key {
            partition_id: middle_partition,
            team_id: 7,
            cohort_id: 1,
            person_id: middle_person,
        };
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();

        let mut stale_receiver_filters = TeamFilters::default();
        stale_receiver_filters.eligibility.insert(
            CohortId(1),
            crate::stage2::CohortEligibility::Excluded(crate::stage2::ExcludedReason::NotMultiLeaf),
        );
        let applied = handle_transfer(
            middle_partition,
            &store,
            &stale_receiver_filters,
            &MergeStateTransfer {
                team_id: 7,
                old_person_uuid: Uuid::from_u128(99),
                new_person_uuid: middle_person,
                merged_at_ms: 1,
                source_partition: 3,
                source_offset: 4,
                leaves: Vec::new(),
                membership_registers: vec![TransferMembershipRegister {
                    cohort_id: 1,
                    in_cohort: true,
                    kind: TransferMembershipRegisterKind::SingleLeafBehavioral,
                }],
                forward_hops: 0,
                person_dedup: None,
            },
            (middle_partition.into(), 5),
            COHORT_PARTITION_COUNT,
        )
        .unwrap();
        assert!(matches!(applied, ApplyOutcome::Applied { .. }));
        assert!(
            Stage2State::decode(&store.get_stage2(&register_key).unwrap().unwrap())
                .unwrap()
                .in_cohort,
            "the wire register survives a stale receiver catalog that excludes the cohort",
        );
        let register_inventory = Stage2TransferredRegisterKey::new(register_key);
        assert_eq!(
            TransferredRegisterProvenance::decode(
                &store
                    .get_stage2_transferred_register(&register_inventory)
                    .unwrap()
                    .unwrap(),
            ),
            Some(TransferredRegisterProvenance::new(
                TransferMembershipRegister {
                    cohort_id: 1,
                    in_cohort: true,
                    kind: TransferMembershipRegisterKind::SingleLeafBehavioral,
                },
                &Stage2State {
                    in_cohort: true,
                    last_evaluated_at_ms: 1,
                }
                .encode_transferred_fallback(),
            )),
        );

        // A second catalogless source collides with the survivor. Both the primary bit and the
        // existing survivor provenance are fill-only; the incoming composable sentinel cannot
        // rewrite either one.
        handle_transfer(
            middle_partition,
            &store,
            &TeamFilters::default(),
            &MergeStateTransfer {
                team_id: 7,
                old_person_uuid: Uuid::from_u128(98),
                new_person_uuid: middle_person,
                merged_at_ms: 1,
                source_partition: 30,
                source_offset: 40,
                leaves: Vec::new(),
                membership_registers: vec![TransferMembershipRegister {
                    cohort_id: 1,
                    in_cohort: true,
                    kind: TransferMembershipRegisterKind::Composable,
                }],
                forward_hops: 0,
                person_dedup: None,
            },
            (middle_partition.into(), 41),
            COHORT_PARTITION_COUNT,
        )
        .unwrap();
        assert!(
            Stage2State::decode(&store.get_stage2(&register_key).unwrap().unwrap())
                .unwrap()
                .in_cohort,
        );
        assert_eq!(
            TransferredRegisterProvenance::decode(
                &store
                    .get_stage2_transferred_register(&register_inventory)
                    .unwrap()
                    .unwrap(),
            ),
            Some(TransferredRegisterProvenance::new(
                TransferMembershipRegister {
                    cohort_id: 1,
                    in_cohort: true,
                    kind: TransferMembershipRegisterKind::SingleLeafBehavioral,
                },
                &Stage2State {
                    in_cohort: true,
                    last_evaluated_at_ms: 1,
                }
                .encode_transferred_fallback(),
            )),
        );

        let empty_filters = TeamFilters::default();
        let second_event = PersonMergeEvent {
            team_id: 7,
            old_person_uuid: middle_person,
            new_person_uuid: final_person,
            merged_at_ms: 2,
            schema_version: crate::merge::transfer::MERGE_EVENT_SCHEMA_VERSION,
        };
        let drained = handle_merge_event_with_transfer_mode(
            middle_partition,
            &store,
            &empty_filters,
            &second_event,
            (middle_partition.into(), 6),
            COHORT_PARTITION_COUNT,
            MembershipRegisterTransferMode::Enabled,
        )
        .unwrap();
        let DrainOutcome::Drained { transfer, .. } = drained else {
            panic!("the enabled second hop should drain the catalogless register");
        };
        assert_eq!(
            transfer.membership_registers,
            vec![TransferMembershipRegister {
                cohort_id: 1,
                in_cohort: true,
                kind: TransferMembershipRegisterKind::SingleLeafBehavioral,
            }],
        );
        assert!(store.get_stage2(&register_key).unwrap().is_none());

        let final_partition = partition_of(TeamId(7), &final_person, COHORT_PARTITION_COUNT) as u16;
        let applied = handle_transfer(
            final_partition,
            &store,
            &empty_filters,
            &transfer,
            (final_partition.into(), 7),
            COHORT_PARTITION_COUNT,
        )
        .unwrap();
        assert!(matches!(applied, ApplyOutcome::Applied { .. }));
        let final_key = Stage2Key {
            partition_id: final_partition,
            person_id: final_person,
            ..register_key
        };
        assert!(
            Stage2State::decode(&store.get_stage2(&final_key).unwrap().unwrap())
                .unwrap()
                .in_cohort,
        );
        assert!(store
            .get_stage2_transferred_register(&Stage2TransferredRegisterKey::new(final_key))
            .unwrap()
            .is_some());
    }
}
