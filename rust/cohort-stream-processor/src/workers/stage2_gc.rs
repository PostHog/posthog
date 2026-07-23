//! Worker-side `cf_stage2` orphan garbage collection.
//!
//! [`handle_stage2_orphan_gc`] reclaims `cf_stage2` rows whose cohort no longer registers membership,
//! on the same
//! [`ShuffleMessage::MergeCfGc`](crate::partitions::shuffle_message::ShuffleMessage::MergeCfGc)
//! tick as [`handle_merge_gc`](crate::workers::merge_gc::handle_merge_gc). Two paths strand such rows:
//! an absent-team merge drain (the catalog provides no ids to delete) and a cohort deleted or made
//! non-realtime.
//!
//! The victim decision is **catalog absence, not a timestamp**: a `cf_stage2` value's
//! `last_evaluated_at_ms` records its latest evaluation, not its retention lifetime, so a time cutoff
//! would evict a still-live dormant member.
//!
//! Two gates keep the pass from deleting live state on an untrustworthy snapshot — a successful
//! *empty* refresh is indistinguishable from "every cohort vanished":
//! 1. [`CatalogHandle::is_loaded`] — never GC before the first successful refresh.
//! 2. non-empty catalog — skip the pass when `team_count() == 0`, so a transient empty load can't
//!    mass-delete. A team whose realtime cohorts are all gone then keeps its orphans until any
//!    composable cohort returns (or `delete_partition`/store retention reclaims them) — a space-only leak.

use metrics::counter;
use tracing::warn;

use crate::filters::manager::CatalogHandle;
use crate::filters::{CohortId, FilterCatalog, TeamId};
use crate::merge::transfer::{TransferMembershipRegisterKind, TransferredRegisterProvenance};
use crate::observability::metrics::{
    STAGE2_ORPHAN_GC_KEYS_DELETED_TOTAL, STAGE2_ORPHAN_GC_KEYS_SCANNED_TOTAL,
    STAGE2_ORPHAN_GC_SKIPPED_TOTAL, STAGE2_ORPHAN_GC_UNDECODABLE_KEYS_TOTAL,
};
use crate::store::{Cf, CohortStore, Stage2DirtyKey, Stage2Key, Stage2TransferredRegisterKey};

/// Per-worker resume cursor: the raw last-key scanned in this partition's `cf_stage2` slice; `None`
/// restarts at the prefix start. Loss on a rebalance is benign — a fresh tenure rescans and
/// re-deleting an absent key is a no-op.
#[derive(Default)]
pub struct Stage2GcCursor(Option<Vec<u8>>);

/// GC one partition's `cf_stage2` orphans for one tick: inspect at most `scan_limit` raw keys,
/// delete every Stage 2 row whose cohort no longer registers membership in `catalog`, and advance
/// the raw cursor (wrapping on exhaustion). Dirty and transferred-register metadata count against
/// the hard per-tick budget but are not membership rows. Inactive dirty metadata is reclaimed;
/// transferred-register metadata protects a catalog-skewed row until the catalog recognizes it. A
/// no-op before the first catalog load or against an empty catalog (the two safety gates).
// Sync GC core; runs on the blocking pool inside `StoreHandle::run_section`, so its direct
// `CohortStore` I/O is already off the runtime threads.
#[allow(clippy::disallowed_methods)]
pub fn handle_stage2_orphan_gc(
    partition_id: u16,
    store: &CohortStore,
    catalog: &CatalogHandle,
    cursor: &mut Stage2GcCursor,
    scan_limit: usize,
) {
    // Gate 1: never GC before the first successful refresh (fail closed).
    if !catalog.is_loaded() {
        counter!(STAGE2_ORPHAN_GC_SKIPPED_TOTAL, "reason" => "catalog_not_loaded").increment(1);
        return;
    }
    let snapshot = catalog.load();
    // Gate 2: an empty catalog is never a basis for deletion (a transient empty refresh must not
    // mass-delete).
    if snapshot.team_count() == 0 {
        counter!(STAGE2_ORPHAN_GC_SKIPPED_TOTAL, "reason" => "empty_catalog").increment(1);
        return;
    }

    let rows = match store.scan_merge_cf(Cf::Stage2, partition_id, cursor.0.as_deref(), scan_limit)
    {
        Ok(rows) => rows,
        Err(error) => {
            warn!(
                partition_id,
                error = %error,
                "cf_stage2 orphan GC scan failed; retrying next tick",
            );
            return;
        }
    };

    if rows.is_empty() {
        cursor.0 = None;
        return;
    }

    counter!(STAGE2_ORPHAN_GC_KEYS_SCANNED_TOTAL).increment(rows.len() as u64);
    let next_cursor = (rows.len() == scan_limit).then(|| {
        rows.last()
            .expect("a full raw page has a final key")
            .0
            .clone()
    });

    // Decode and classify before opening the batch, since the batch closure is infallible.
    let mut undecodable = 0u64;
    let mut victims: Vec<Stage2Key> = Vec::new();
    let mut stale_dirty: Vec<Stage2DirtyKey> = Vec::new();
    let mut settled_transferred: Vec<Stage2TransferredRegisterKey> = Vec::new();
    for (key_bytes, value) in &rows {
        if let Ok(dirty) = Stage2DirtyKey::decode(key_bytes) {
            if !store.is_stage2_dirty_tracking_active(dirty.stage2_key().cohort_prefix()) {
                stale_dirty.push(dirty);
            }
            continue;
        }
        if let Ok(transferred) = Stage2TransferredRegisterKey::decode(key_bytes) {
            let stage2_key = transferred.stage2_key();
            let primary = match store.get_stage2(&stage2_key) {
                Ok(row) => row,
                Err(error) => {
                    warn!(
                        partition_id,
                        error = %error,
                        "cf_stage2 orphan GC inventory read failed; retrying this page next tick",
                    );
                    return;
                }
            };
            // Exact primary bytes tie provenance to the receiver fallback it describes. A later
            // local evaluation supersedes that fallback without requiring an extra tombstone on
            // every Stage 2 write. Matching catalog semantics also make person-first enumeration
            // redundant. Missing primaries always leave stale inventory.
            let settled = match (
                primary.as_deref(),
                TransferredRegisterProvenance::decode(value),
            ) {
                (None, _) => true,
                (Some(primary), Some(provenance)) => {
                    !provenance.matches_primary(primary)
                        || Some(provenance.kind) == catalog_register_kind(&snapshot, &stage2_key)
                }
                (Some(_), None) => false,
            };
            if settled {
                settled_transferred.push(transferred);
            }
            continue;
        }
        match Stage2Key::decode(key_bytes) {
            Ok(key) => match is_orphan(&snapshot, &key) {
                Some(true) => {
                    let inventory = Stage2TransferredRegisterKey::new(key);
                    match store.get_stage2_transferred_register(&inventory) {
                        Ok(Some(_)) => {}
                        Ok(None) => victims.push(key),
                        Err(error) => {
                            warn!(
                                partition_id,
                                error = %error,
                                "cf_stage2 orphan GC protection read failed; retrying this page next tick",
                            );
                            return;
                        }
                    }
                }
                Some(false) => {}
                // An id outside `i32` can't be classified — leave it in place (not corruption).
                None => undecodable += 1,
            },
            Err(_) => {
                // A key the decoder rejects signals corruption, not expiry: leave it and warn.
                undecodable += 1;
                warn!(
                    partition_id,
                    "cf_stage2 orphan GC could not decode a key; leaving it in place",
                );
            }
        }
    }

    if !victims.is_empty() || !stale_dirty.is_empty() || !settled_transferred.is_empty() {
        let result = store.write_batch(|batch| {
            for key in &victims {
                batch.delete_stage2(key);
                // Orphan deletion does not need reconcile coverage. Clear both a pre-existing dirty
                // marker and the one `delete_stage2` just staged, in the same atomic batch.
                batch.delete_stage2_dirty(&Stage2DirtyKey::new(*key));
            }
            for key in &stale_dirty {
                batch.delete_stage2_dirty(key);
            }
            for key in &settled_transferred {
                batch.delete_stage2_transferred_register(key);
            }
        });
        match result {
            Ok(()) => {
                counter!(STAGE2_ORPHAN_GC_KEYS_DELETED_TOTAL).increment(victims.len() as u64);
            }
            Err(error) => {
                // Return without advancing the cursor so the keys are retried next tick.
                warn!(
                    partition_id,
                    error = %error,
                    "cf_stage2 orphan GC delete batch failed; leaving the keys for the next tick",
                );
                return;
            }
        }
    }

    if undecodable > 0 {
        counter!(STAGE2_ORPHAN_GC_UNDECODABLE_KEYS_TOTAL).increment(undecodable);
    }

    cursor.0 = next_cursor;
}

/// Whether a `cf_stage2` row is an orphan: its cohort does not register membership in `snapshot`.
/// Team-absent, cohort-absent, and excluded cohorts resolve to orphan. `None` when the id can't be
/// classified (outside `i32`), which the caller leaves in place.
fn is_orphan(snapshot: &FilterCatalog, key: &Stage2Key) -> Option<bool> {
    // Keys store `u64`; `TeamId`/`CohortId` are `i32`, so an overflowing id can't be matched.
    let team_id = i32::try_from(key.team_id).ok()?;
    let cohort_id = i32::try_from(key.cohort_id).ok()?;
    let live = snapshot
        .team(TeamId(team_id))
        .and_then(|team_filters| team_filters.eligibility.get(&CohortId(cohort_id)))
        .is_some_and(|eligibility| eligibility.registers_membership());
    Some(!live)
}

/// Catalog semantics for a register, when both ids are representable and the cohort is live.
fn catalog_register_kind(
    snapshot: &FilterCatalog,
    key: &Stage2Key,
) -> Option<TransferMembershipRegisterKind> {
    let team_id = TeamId(i32::try_from(key.team_id).ok()?);
    let cohort_id = CohortId(i32::try_from(key.cohort_id).ok()?);
    TransferMembershipRegisterKind::from_filters(snapshot.team(team_id)?, cohort_id)
}

// Tests seed and read stage-2 rows directly against the store.
#[cfg(test)]
#[allow(clippy::disallowed_methods)]
mod tests {
    use super::*;
    use tempfile::TempDir;
    use uuid::Uuid;

    use crate::filters::reverse_index::TeamFilters;
    use crate::merge::transfer::TransferMembershipRegister;
    use crate::stage1::key::LeafStateKey;
    use crate::stage2::state::Stage2State;
    use crate::stage2::{CohortEligibility, ExcludedReason};
    use crate::store::{OpaqueCf, StoreConfig};

    const PARTITION: u16 = 5;
    const ABSENT_TEAM: u64 = 7;
    const LIVE_TEAM: u64 = 8;
    const NO_CAP: usize = 10_000;

    fn temp_store() -> (TempDir, CohortStore) {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();
        (dir, store)
    }

    fn stage2_key(team_id: u64, cohort_id: u64, person: u128) -> Stage2Key {
        Stage2Key {
            partition_id: PARTITION,
            team_id,
            cohort_id,
            person_id: Uuid::from_u128(person),
        }
    }

    fn put_row(store: &CohortStore, key: &Stage2Key) {
        let value = Stage2State {
            in_cohort: true,
            last_evaluated_at_ms: 1_700_000_000_000,
        }
        .encode();
        store
            .write_batch(|batch| batch.put_stage2(key, &value))
            .unwrap();
    }

    fn exists(store: &CohortStore, key: &Stage2Key) -> bool {
        store.get_stage2(key).unwrap().is_some()
    }

    /// A `TeamFilters` with only its eligibility map populated — the one field the orphan GC reads.
    fn team_filters(eligibility: &[(i32, CohortEligibility)]) -> TeamFilters {
        let mut filters = TeamFilters::default();
        for &(cohort_id, class) in eligibility {
            filters.eligibility.insert(CohortId(cohort_id), class);
        }
        filters
    }

    /// A loaded catalog from `(team_id, [(cohort_id, class)])` pairs.
    fn loaded(teams: &[(i32, &[(i32, CohortEligibility)])]) -> CatalogHandle {
        CatalogHandle::from_catalog(FilterCatalog::from_teams(
            teams
                .iter()
                .map(|&(team_id, elig)| (TeamId(team_id), team_filters(elig))),
        ))
    }

    /// A non-empty catalog with `LIVE_TEAM` composable and `ABSENT_TEAM` absent.
    fn live_team_only() -> CatalogHandle {
        loaded(&[(
            LIVE_TEAM as i32,
            &[(1, CohortEligibility::Stage2Composable)],
        )])
    }

    fn single_leaf() -> CohortEligibility {
        CohortEligibility::SingleLeaf(LeafStateKey([0xAB; 16]))
    }

    #[test]
    fn orphan_row_for_an_absent_team_is_deleted() {
        let (_dir, store) = temp_store();
        let orphan = stage2_key(ABSENT_TEAM, 1, 100);
        put_row(&store, &orphan);

        let catalog = live_team_only();
        let mut cursor = Stage2GcCursor::default();
        handle_stage2_orphan_gc(PARTITION, &store, &catalog, &mut cursor, NO_CAP);

        assert!(
            !exists(&store, &orphan),
            "a row for a team absent from the catalog is an orphan and is reclaimed",
        );
    }

    #[test]
    fn single_leaf_register_is_kept_while_an_absent_cohort_is_deleted() {
        let (_dir, store) = temp_store();
        // Team present: cohort 1 still registers membership, while cohort 2 is absent.
        let reclassified = stage2_key(LIVE_TEAM, 1, 100);
        let deleted_cohort = stage2_key(LIVE_TEAM, 2, 100);
        put_row(&store, &reclassified);
        put_row(&store, &deleted_cohort);

        let catalog = loaded(&[(LIVE_TEAM as i32, &[(1, single_leaf())])]);
        let mut cursor = Stage2GcCursor::default();
        handle_stage2_orphan_gc(PARTITION, &store, &catalog, &mut cursor, NO_CAP);

        assert!(
            exists(&store, &reclassified),
            "a SingleLeaf row is a live membership register",
        );
        assert!(
            !exists(&store, &deleted_cohort),
            "a cohort absent from the catalog leaves its cf_stage2 row an orphan",
        );
    }

    #[test]
    fn live_composable_cohort_row_is_kept() {
        let (_dir, store) = temp_store();
        let live = stage2_key(LIVE_TEAM, 1, 100);
        put_row(&store, &live);

        let catalog = loaded(&[(
            LIVE_TEAM as i32,
            &[(1, CohortEligibility::Stage2Composable)],
        )]);
        let mut cursor = Stage2GcCursor::default();
        handle_stage2_orphan_gc(PARTITION, &store, &catalog, &mut cursor, NO_CAP);

        assert!(
            exists(&store, &live),
            "a still-composable cohort's row is live and must be kept",
        );
    }

    #[test]
    fn composable_ref_cohort_row_is_kept() {
        let (_dir, store) = temp_store();
        // Stage2ComposableRef also persists a cf_stage2 row — guard against a too-narrow predicate.
        let live = stage2_key(LIVE_TEAM, 1, 100);
        put_row(&store, &live);

        let catalog = loaded(&[(
            LIVE_TEAM as i32,
            &[(1, CohortEligibility::Stage2ComposableRef)],
        )]);
        let mut cursor = Stage2GcCursor::default();
        handle_stage2_orphan_gc(PARTITION, &store, &catalog, &mut cursor, NO_CAP);

        assert!(
            exists(&store, &live),
            "a Stage2ComposableRef cohort's row is live and must be kept",
        );
    }

    #[test]
    fn pass_is_skipped_when_catalog_is_unloaded() {
        let (_dir, store) = temp_store();
        let orphan = stage2_key(ABSENT_TEAM, 1, 100);
        put_row(&store, &orphan);

        // A fresh handle is unloaded; the pass must not delete before the first successful refresh.
        let catalog = CatalogHandle::new();
        assert!(!catalog.is_loaded());
        let mut cursor = Stage2GcCursor::default();
        handle_stage2_orphan_gc(PARTITION, &store, &catalog, &mut cursor, NO_CAP);

        assert!(
            exists(&store, &orphan),
            "no deletion before the first catalog load (the is_loaded gate)",
        );
    }

    #[test]
    fn pass_is_skipped_when_catalog_is_empty() {
        let (_dir, store) = temp_store();
        let orphan = stage2_key(ABSENT_TEAM, 1, 100);
        put_row(&store, &orphan);

        // Loaded but empty (team_count() == 0): a spurious empty refresh must never mass-delete.
        let catalog = CatalogHandle::from_catalog(FilterCatalog::from_teams([]));
        assert!(catalog.is_loaded());
        assert_eq!(catalog.load().team_count(), 0);
        let mut cursor = Stage2GcCursor::default();
        handle_stage2_orphan_gc(PARTITION, &store, &catalog, &mut cursor, NO_CAP);

        assert!(
            exists(&store, &orphan),
            "an empty catalog is not a basis for deletion (the team_count gate)",
        );
    }

    #[test]
    fn respects_the_scan_cap_and_resumes_via_the_cursor() {
        let (_dir, store) = temp_store();
        // Six orphans for the absent team; a cap of 2 reclaims only the first two per tick.
        let orphans: Vec<Stage2Key> = (1..=6u128).map(|p| stage2_key(ABSENT_TEAM, 1, p)).collect();
        for key in &orphans {
            put_row(&store, key);
        }

        let catalog = live_team_only();
        let mut cursor = Stage2GcCursor::default();
        let surviving = |store: &CohortStore| orphans.iter().filter(|k| exists(store, k)).count();

        handle_stage2_orphan_gc(PARTITION, &store, &catalog, &mut cursor, 2);
        assert_eq!(surviving(&store), 4, "tick 1 deleted exactly the cap of 2");

        handle_stage2_orphan_gc(PARTITION, &store, &catalog, &mut cursor, 2);
        assert_eq!(surviving(&store), 2, "tick 2 deleted the next 2");

        // Tick 3 drains the last 2 on an exactly-full page, so the cursor advances rather than wrapping.
        handle_stage2_orphan_gc(PARTITION, &store, &catalog, &mut cursor, 2);
        assert_eq!(
            surviving(&store),
            0,
            "all orphans gone after three capped ticks"
        );
        assert!(
            cursor.0.is_some(),
            "a full final page leaves the cursor advanced, not wrapped"
        );

        // The next tick finds an empty page and wraps to the prefix start.
        handle_stage2_orphan_gc(PARTITION, &store, &catalog, &mut cursor, 2);
        assert!(
            cursor.0.is_none(),
            "an empty follow-up tick wraps the cursor to the prefix start",
        );
    }

    #[test]
    fn cursor_advances_past_live_rows_to_reach_an_orphan() {
        let (_dir, store) = temp_store();
        // Three live rows (LIVE_TEAM sorts first) then one orphan (ABSENT_TEAM sorts last); a cap of 1
        // forces the cursor past each survivor before it can reach the orphan.
        let live: Vec<Stage2Key> = (1..=3u128).map(|p| stage2_key(LIVE_TEAM, 1, p)).collect();
        for key in &live {
            put_row(&store, key);
        }
        let orphan = stage2_key(ABSENT_TEAM, 1, 100);
        put_row(&store, &orphan);

        let catalog = live_team_only();
        let mut cursor = Stage2GcCursor::default();

        // Three ticks scan a survivor each; the fourth reaches and deletes the orphan.
        for _ in 0..4 {
            handle_stage2_orphan_gc(PARTITION, &store, &catalog, &mut cursor, 1);
        }

        assert!(
            !exists(&store, &orphan),
            "the cursor advanced past the live rows to the orphan"
        );
        for key in &live {
            assert!(exists(&store, key), "every live row survived the sweep");
        }
    }

    #[test]
    fn dirty_metadata_consumes_the_raw_per_tick_budget() {
        let (_dir, store) = temp_store();
        let live = stage2_key(LIVE_TEAM, 1, 100);
        let _tracking = store.track_stage2_dirty(live.cohort_prefix());
        put_row(&store, &live);
        let dirty = Stage2DirtyKey::new(live).encode().to_vec();
        let catalog = loaded(&[(LIVE_TEAM as i32, &[(1, single_leaf())])]);
        let mut cursor = Stage2GcCursor::default();

        handle_stage2_orphan_gc(PARTITION, &store, &catalog, &mut cursor, 1);
        assert_eq!(cursor.0, Some(live.encode().to_vec()));

        handle_stage2_orphan_gc(PARTITION, &store, &catalog, &mut cursor, 1);
        assert_eq!(
            cursor.0,
            Some(dirty),
            "one dirty marker consumes the entire one-key tick budget",
        );
        assert!(exists(&store, &live));

        handle_stage2_orphan_gc(PARTITION, &store, &catalog, &mut cursor, 1);
        assert!(cursor.0.is_none(), "the following empty tick wraps");
    }

    #[test]
    fn inactive_dirty_only_marker_is_reclaimed() {
        let (_dir, store) = temp_store();
        let deleted = stage2_key(ABSENT_TEAM, 1, 100);
        {
            let _tracking = store.track_stage2_dirty(deleted.cohort_prefix());
            store
                .write_batch(|batch| batch.delete_stage2(&deleted))
                .unwrap();
            assert!(store
                .get(Cf::Stage2, &Stage2DirtyKey::new(deleted).encode())
                .unwrap()
                .is_some());
        }

        let mut cursor = Stage2GcCursor::default();
        handle_stage2_orphan_gc(PARTITION, &store, &live_team_only(), &mut cursor, NO_CAP);

        assert!(store
            .get(Cf::Stage2, &Stage2DirtyKey::new(deleted).encode())
            .unwrap()
            .is_none());
    }

    #[test]
    fn transferred_register_survives_gc_until_catalog_refresh() {
        let (_dir, store) = temp_store();
        let transferred = stage2_key(ABSENT_TEAM, 17, 100);
        let inventory = Stage2TransferredRegisterKey::new(transferred);
        let state = Stage2State {
            in_cohort: true,
            last_evaluated_at_ms: 1,
        };
        let provenance = TransferredRegisterProvenance::new(
            TransferMembershipRegister {
                cohort_id: 17,
                in_cohort: true,
                kind: TransferMembershipRegisterKind::Composable,
            },
            &state.encode_transferred_fallback(),
        );
        store
            .write_batch(|batch| {
                batch.put_stage2(&transferred, &state.encode_transferred_fallback());
                batch.put_stage2_transferred_register(&inventory, &provenance.encode());
            })
            .unwrap();

        let mut cursor = Stage2GcCursor::default();
        handle_stage2_orphan_gc(PARTITION, &store, &live_team_only(), &mut cursor, NO_CAP);
        assert!(exists(&store, &transferred));
        assert!(store
            .get_stage2_transferred_register(&inventory)
            .unwrap()
            .is_some());

        // A later catalog snapshot recognizes the cohort. The ordinary keep predicate now protects
        // the row and GC retires only the temporary person-first inventory.
        let refreshed = loaded(&[(
            ABSENT_TEAM as i32,
            &[(17, CohortEligibility::Stage2Composable)],
        )]);
        cursor.0 = None;
        handle_stage2_orphan_gc(PARTITION, &store, &refreshed, &mut cursor, NO_CAP);
        assert!(exists(&store, &transferred));
        assert!(store
            .get_stage2_transferred_register(&inventory)
            .unwrap()
            .is_none());
    }

    #[test]
    fn stale_catalog_shape_cannot_retire_wire_inventory() {
        let (_dir, store) = temp_store();
        let transferred = stage2_key(LIVE_TEAM, 17, 100);
        let inventory = Stage2TransferredRegisterKey::new(transferred);
        let transferred_state = Stage2State {
            in_cohort: true,
            last_evaluated_at_ms: 1,
        };
        let provenance = TransferredRegisterProvenance::new(
            TransferMembershipRegister {
                cohort_id: 17,
                in_cohort: true,
                kind: TransferMembershipRegisterKind::SingleLeafBehavioral,
            },
            &transferred_state.encode_transferred_fallback(),
        );
        store
            .write_batch(|batch| {
                batch.put_stage2(
                    &transferred,
                    &transferred_state.encode_transferred_fallback(),
                );
                batch.put_stage2_transferred_register(&inventory, &provenance.encode());
            })
            .unwrap();
        let stale_shape = loaded(&[(
            LIVE_TEAM as i32,
            &[(17, CohortEligibility::Stage2Composable)],
        )]);
        let mut cursor = Stage2GcCursor::default();

        handle_stage2_orphan_gc(PARTITION, &store, &stale_shape, &mut cursor, NO_CAP);
        assert!(store
            .get_stage2_transferred_register(&inventory)
            .unwrap()
            .is_some());

        // A later normal evaluation write supersedes the exact fallback fingerprint. GC can retire
        // the provenance without adding a second write to the evaluation hot path.
        store
            .write_batch(|batch| {
                batch.put_stage2(
                    &transferred,
                    &Stage2State {
                        in_cohort: false,
                        last_evaluated_at_ms: 2,
                    }
                    .encode(),
                );
            })
            .unwrap();
        assert!(store
            .get_stage2_transferred_register(&inventory)
            .unwrap()
            .is_some());
        cursor.0 = None;
        handle_stage2_orphan_gc(PARTITION, &store, &stale_shape, &mut cursor, NO_CAP);
        assert!(store
            .get_stage2_transferred_register(&inventory)
            .unwrap()
            .is_none());
    }

    #[test]
    fn undecodable_or_impossible_key_is_left_in_place() {
        let (_dir, store) = temp_store();

        // A real orphan, to prove the pass still does its work.
        let orphan = stage2_key(ABSENT_TEAM, 1, 100);
        put_row(&store, &orphan);

        // A decodable key whose team_id overflows i32 — can't be classified against the catalog.
        let impossible = stage2_key(u64::MAX, 1, 200);
        put_row(&store, &impossible);

        // A corrupt key the decoder rejects (wrong length), staged under the partition prefix so the
        // scan still reaches it.
        let mut corrupt = PARTITION.to_be_bytes().to_vec();
        corrupt.extend_from_slice(&[0xFFu8; 8]); // 10 bytes ≠ STAGE2_KEY_LEN (34)
        store
            .write_batch(|batch| batch.put_raw(OpaqueCf::Stage2, &corrupt, b"x"))
            .unwrap();

        let catalog = live_team_only();
        let mut cursor = Stage2GcCursor::default();
        handle_stage2_orphan_gc(PARTITION, &store, &catalog, &mut cursor, NO_CAP);

        assert!(
            !exists(&store, &orphan),
            "the classifiable orphan is reclaimed"
        );
        assert!(
            exists(&store, &impossible),
            "a key with an out-of-i32 id is left in place (can't classify confidently)",
        );
        assert!(
            store.get(Cf::Stage2, &corrupt).unwrap().is_some(),
            "a corrupt, undecodable key is left in place (no delete-by-raw-bytes path)",
        );
    }

    #[test]
    fn is_orphan_classifies_each_eligibility_class() {
        let catalog = FilterCatalog::from_teams([(
            TeamId(LIVE_TEAM as i32),
            team_filters(&[
                (1, CohortEligibility::Stage2Composable),
                (2, CohortEligibility::Stage2ComposableRef),
                (3, single_leaf()),
                (4, CohortEligibility::Excluded(ExcludedReason::HasCohortRef)),
            ]),
        )]);

        // Composable classes are live (kept).
        assert_eq!(
            is_orphan(&catalog, &stage2_key(LIVE_TEAM, 1, 0)),
            Some(false)
        );
        assert_eq!(
            is_orphan(&catalog, &stage2_key(LIVE_TEAM, 2, 0)),
            Some(false)
        );
        // SingleLeaf registers membership; Excluded persists no row.
        assert_eq!(
            is_orphan(&catalog, &stage2_key(LIVE_TEAM, 3, 0)),
            Some(false)
        );
        assert_eq!(
            is_orphan(&catalog, &stage2_key(LIVE_TEAM, 4, 0)),
            Some(true)
        );
        // Cohort absent from the team → orphan; team absent → orphan.
        assert_eq!(
            is_orphan(&catalog, &stage2_key(LIVE_TEAM, 99, 0)),
            Some(true)
        );
        assert_eq!(
            is_orphan(&catalog, &stage2_key(ABSENT_TEAM, 1, 0)),
            Some(true)
        );
        // An id outside i32 can't be classified → None (left in place).
        assert_eq!(is_orphan(&catalog, &stage2_key(u64::MAX, 1, 0)), None);
        assert_eq!(
            is_orphan(&catalog, &stage2_key(LIVE_TEAM, u64::MAX, 0)),
            None
        );
    }
}
