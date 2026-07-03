//! Worker-side merge-CF garbage collection.
//!
//! [`handle_merge_gc`] runs on the partition worker in response to a
//! [`ShuffleMessage::MergeCfGc`](crate::partitions::shuffle_message::ShuffleMessage::MergeCfGc). For
//! each GC-able merge CF it scans the partition's slice (capped per tick), decodes the value
//! timestamp, and batch-deletes every entry older than the relevant cutoff in one `write_batch`. A
//! per-CF in-memory resume cursor ([`MergeGcCursor`]) continues each tick where the last one stopped
//! and wraps to the prefix start on exhaustion.
//!
//! Posture choices a reader can't recover from the code:
//! - **Undecodable value → delete + count.** An unreadable timestamp can never age out, so it would
//!   leak forever. Deleting it costs at most one bounded replay of the 7d-retention source topic.
//!   Counted on [`MERGE_GC_UNDECODABLE_TOTAL`].
//! - **`cf_pending_transfers` is never GC'd here.** It is the redrive's outbox (drained by
//!   [`crate::merge::redrive`]), not a marker that ages out — GCing it would drop a staged,
//!   never-produced transfer. It is simply absent from [`GC_CFS`].

// Sync core run on the blocking pool via `StoreHandle::run_section`, so its direct `CohortStore` I/O
// is sanctioned.
#![allow(clippy::disallowed_methods)]

use metrics::counter;
use tracing::warn;

use crate::merge::transfer::{ApplyStamp, DrainStamp, Tombstone};
use crate::observability::metrics::{
    MERGE_GC_KEYS_DELETED_TOTAL, MERGE_GC_KEYS_SCANNED_TOTAL, MERGE_GC_UNDECODABLE_TOTAL,
};
use crate::store::keys::{MergeAppliedKey, MergeDrainKey, TombstoneKey};
use crate::store::{BatchBuilder, Cf, CohortStore};

/// The merge CFs the GC sweep evicts. `cf_pending_transfers` is deliberately excluded (see the
/// module doc).
#[derive(Copy, Clone, Debug, Eq, PartialEq)]
enum GcCf {
    /// Drain marker (`DrainStamp.drained_at_ms`), evicted below the marker cutoff.
    DrainsApplied,
    /// Apply marker (`ApplyStamp.applied_at_ms`), evicted below the marker cutoff.
    Applied,
    /// Redirect tombstone (`Tombstone.merged_at_ms`), evicted below the (longer) tombstone cutoff.
    Tombstones,
}

const GC_CFS: [GcCf; 3] = [GcCf::DrainsApplied, GcCf::Applied, GcCf::Tombstones];

impl GcCf {
    fn cf(self) -> Cf {
        match self {
            GcCf::DrainsApplied => Cf::MergeDrainsApplied,
            GcCf::Applied => Cf::MergeApplied,
            GcCf::Tombstones => Cf::MergeTombstones,
        }
    }

    fn label(self) -> &'static str {
        self.cf().as_str()
    }
}

/// Per-worker resume cursors, one raw last-key per GC CF. `None` restarts the next scan at the
/// partition's prefix start (the wrap-on-exhaustion state). Loss on a rebalance is benign: a fresh
/// tenure rescans from the start, and re-scanning an already-deleted key is a no-op.
#[derive(Default)]
pub struct MergeGcCursor {
    drains_applied: Option<Vec<u8>>,
    applied: Option<Vec<u8>>,
    tombstones: Option<Vec<u8>>,
}

impl MergeGcCursor {
    fn get(&self, cf: GcCf) -> Option<&[u8]> {
        match cf {
            GcCf::DrainsApplied => self.drains_applied.as_deref(),
            GcCf::Applied => self.applied.as_deref(),
            GcCf::Tombstones => self.tombstones.as_deref(),
        }
    }

    fn set(&mut self, cf: GcCf, value: Option<Vec<u8>>) {
        match cf {
            GcCf::DrainsApplied => self.drains_applied = value,
            GcCf::Applied => self.applied = value,
            GcCf::Tombstones => self.tombstones = value,
        }
    }
}

/// GC one partition's three merge CFs for one tick. `marker_cutoff_ms` gates the two idempotence
/// markers; `tombstone_cutoff_ms` (longer) gates tombstones.
pub fn handle_merge_gc(
    partition_id: u16,
    store: &CohortStore,
    cursor: &mut MergeGcCursor,
    marker_cutoff_ms: i64,
    tombstone_cutoff_ms: i64,
    scan_limit: usize,
) {
    for gc_cf in GC_CFS {
        let cutoff = match gc_cf {
            GcCf::DrainsApplied | GcCf::Applied => marker_cutoff_ms,
            GcCf::Tombstones => tombstone_cutoff_ms,
        };
        sweep_one_cf(partition_id, store, cursor, gc_cf, cutoff, scan_limit);
    }
}

/// Scan one CF up to the cap, collect expired/undecodable keys, delete them in one batch, and
/// advance the cursor (wrapping on exhaustion).
fn sweep_one_cf(
    partition_id: u16,
    store: &CohortStore,
    cursor: &mut MergeGcCursor,
    gc_cf: GcCf,
    cutoff_ms: i64,
    scan_limit: usize,
) {
    let cf = gc_cf.cf();
    let label = gc_cf.label();

    let entries = match store.scan_merge_cf(cf, partition_id, cursor.get(gc_cf), scan_limit) {
        Ok(entries) => entries,
        Err(error) => {
            warn!(
                partition_id,
                cf = label,
                error = %error,
                "merge-CF GC scan failed; retrying next tick",
            );
            return;
        }
    };

    if entries.is_empty() {
        // Exhausted this partition's slice — wrap to the prefix start for the next tick.
        cursor.set(gc_cf, None);
        return;
    }

    counter!(MERGE_GC_KEYS_SCANNED_TOTAL, "cf" => label).increment(entries.len() as u64);

    // Decide deletions before opening the batch so the closure borrows nothing fallible.
    let mut undecodable = 0u64;
    let mut victims: Vec<Vec<u8>> = Vec::new();
    for (key_bytes, value_bytes) in &entries {
        match expiry_decision(gc_cf, value_bytes, cutoff_ms) {
            ExpiryDecision::Keep => {}
            ExpiryDecision::Expired => victims.push(key_bytes.clone()),
            ExpiryDecision::Undecodable => {
                undecodable += 1;
                victims.push(key_bytes.clone());
            }
        }
    }

    if !victims.is_empty() {
        let result = store.write_batch(|batch| {
            for key_bytes in &victims {
                stage_delete(batch, gc_cf, key_bytes, partition_id, label);
            }
        });
        match result {
            Ok(()) => {
                counter!(MERGE_GC_KEYS_DELETED_TOTAL, "cf" => label)
                    .increment(victims.len() as u64);
                if undecodable > 0 {
                    counter!(MERGE_GC_UNDECODABLE_TOTAL, "cf" => label).increment(undecodable);
                }
            }
            Err(error) => {
                // The delete batch failed; leave the cursor unadvanced so the same keys are
                // re-evaluated next tick. Nothing was counted as deleted.
                warn!(
                    partition_id,
                    cf = label,
                    error = %error,
                    "merge-CF GC delete batch failed; leaving the keys for the next tick",
                );
                return;
            }
        }
    }

    // Full page → more may remain, resume after the last key; short page → slice exhausted, wrap to
    // the start. The cursor is the last *scanned* key (survivors included), so a long-lived entry
    // never wedges the cursor on itself.
    if entries.len() == scan_limit {
        let last_key = entries
            .last()
            .expect("non-empty by the guard above")
            .0
            .clone();
        cursor.set(gc_cf, Some(last_key));
    } else {
        cursor.set(gc_cf, None);
    }
}

/// Whether one entry's value timestamp is older than `cutoff_ms`.
enum ExpiryDecision {
    Keep,
    Expired,
    /// Value timestamp could not be decoded → delete (it can never age out otherwise).
    Undecodable,
}

fn expiry_decision(gc_cf: GcCf, value_bytes: &[u8], cutoff_ms: i64) -> ExpiryDecision {
    let timestamp = match gc_cf {
        GcCf::DrainsApplied => DrainStamp::decode(value_bytes).map(|stamp| stamp.drained_at_ms),
        GcCf::Applied => ApplyStamp::decode(value_bytes).map(|stamp| stamp.applied_at_ms),
        GcCf::Tombstones => Tombstone::decode(value_bytes).map(|tombstone| tombstone.merged_at_ms),
    };
    match timestamp {
        Ok(ts) if ts < cutoff_ms => ExpiryDecision::Expired,
        Ok(_) => ExpiryDecision::Keep,
        Err(_) => ExpiryDecision::Undecodable,
    }
}

/// Decode the raw key into its typed form and stage the matching CF delete. Unlike an undecodable
/// *value*, an undecodable *key* is left in place (there is no delete-by-raw-bytes path, and an
/// unparseable key signals store corruption, not routine expiry) and only warned.
fn stage_delete(
    batch: &mut BatchBuilder<'_>,
    gc_cf: GcCf,
    key_bytes: &[u8],
    partition_id: u16,
    label: &str,
) {
    let decoded = match gc_cf {
        GcCf::DrainsApplied => MergeDrainKey::decode(key_bytes).map(|key| {
            batch.delete_merge_drain_applied(&key);
        }),
        GcCf::Applied => MergeAppliedKey::decode(key_bytes).map(|key| {
            batch.delete_merge_applied(&key);
        }),
        GcCf::Tombstones => TombstoneKey::decode(key_bytes).map(|key| {
            batch.delete_tombstone(&key);
        }),
    };
    if decoded.is_err() {
        warn!(
            partition_id,
            cf = label,
            "merge-CF GC could not decode an expired key; leaving it in place",
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;
    use uuid::Uuid;

    use crate::store::keys::{MergeAppliedKey, MergeDrainKey, PendingTransferKey, TombstoneKey};
    use crate::store::StoreConfig;

    const PARTITION: u16 = 5;
    const TEAM: u64 = 7;
    const MARKER_CUTOFF: i64 = 1_000;
    const TOMBSTONE_CUTOFF: i64 = 500;
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

    fn drain_key(person: u128, offset: i64) -> MergeDrainKey {
        MergeDrainKey {
            partition_id: PARTITION,
            team_id: TEAM,
            old_person: Uuid::from_u128(person),
            merge_msg_partition: PARTITION as i32,
            merge_msg_offset: offset,
        }
    }

    fn applied_key(person: u128, offset: i64) -> MergeAppliedKey {
        MergeAppliedKey {
            partition_id: PARTITION,
            team_id: TEAM,
            new_person: Uuid::from_u128(person),
            source_partition: PARTITION as i32,
            source_offset: offset,
        }
    }

    fn tombstone_key(person: u128) -> TombstoneKey {
        TombstoneKey {
            partition_id: PARTITION,
            team_id: TEAM,
            person: Uuid::from_u128(person),
        }
    }

    fn put_drain(store: &CohortStore, key: &MergeDrainKey, drained_at_ms: i64) {
        let value = DrainStamp { drained_at_ms }.encode();
        store
            .write_batch(|batch| batch.put_merge_drain_applied(key, &value))
            .unwrap();
    }

    fn put_applied(store: &CohortStore, key: &MergeAppliedKey, applied_at_ms: i64) {
        let value = ApplyStamp { applied_at_ms }.encode();
        store
            .write_batch(|batch| batch.put_merge_applied(key, &value))
            .unwrap();
    }

    fn put_tombstone(store: &CohortStore, key: &TombstoneKey, merged_at_ms: i64) {
        let value = Tombstone {
            new_person: Uuid::from_u128(0xBEEF),
            merged_at_ms,
        }
        .encode();
        store
            .write_batch(|batch| batch.put_tombstone(key, &value))
            .unwrap();
    }

    fn run_gc(store: &CohortStore, cursor: &mut MergeGcCursor, cap: usize) {
        handle_merge_gc(
            PARTITION,
            store,
            cursor,
            MARKER_CUTOFF,
            TOMBSTONE_CUTOFF,
            cap,
        );
    }

    #[test]
    fn expired_markers_and_tombstones_are_deleted_and_fresh_ones_kept() {
        let (_dir, store) = temp_store();

        // Drain markers: one expired (drained_at < marker cutoff), one fresh.
        let expired_drain = drain_key(1, 10);
        let fresh_drain = drain_key(2, 11);
        put_drain(&store, &expired_drain, MARKER_CUTOFF - 1);
        put_drain(&store, &fresh_drain, MARKER_CUTOFF + 1);

        // Apply markers: one expired, one fresh.
        let expired_apply = applied_key(3, 12);
        let fresh_apply = applied_key(4, 13);
        put_applied(&store, &expired_apply, MARKER_CUTOFF - 1);
        put_applied(&store, &fresh_apply, MARKER_CUTOFF + 1);

        // Tombstones: one expired (merged_at < tombstone cutoff), one fresh.
        let expired_tomb = tombstone_key(5);
        let fresh_tomb = tombstone_key(6);
        put_tombstone(&store, &expired_tomb, TOMBSTONE_CUTOFF - 1);
        put_tombstone(&store, &fresh_tomb, TOMBSTONE_CUTOFF + 1);

        let mut cursor = MergeGcCursor::default();
        run_gc(&store, &mut cursor, NO_CAP);

        assert!(store
            .get_merge_drain_applied(&expired_drain)
            .unwrap()
            .is_none());
        assert!(store
            .get_merge_drain_applied(&fresh_drain)
            .unwrap()
            .is_some());
        assert!(store.get_merge_applied(&expired_apply).unwrap().is_none());
        assert!(store.get_merge_applied(&fresh_apply).unwrap().is_some());
        assert!(store.get_tombstone(&expired_tomb).unwrap().is_none());
        assert!(store.get_tombstone(&fresh_tomb).unwrap().is_some());
    }

    #[test]
    fn marker_and_tombstone_cutoffs_are_independent() {
        let (_dir, store) = temp_store();

        // A drain marker between the two cutoffs (TOMBSTONE_CUTOFF < ts < MARKER_CUTOFF): expired by
        // the marker cutoff. A tombstone at the same timestamp is fresh by the tombstone cutoff.
        let ts = (MARKER_CUTOFF + TOMBSTONE_CUTOFF) / 2;
        assert!(ts < MARKER_CUTOFF && ts > TOMBSTONE_CUTOFF);

        let marker = drain_key(1, 10);
        let tomb = tombstone_key(2);
        put_drain(&store, &marker, ts);
        put_tombstone(&store, &tomb, ts);

        let mut cursor = MergeGcCursor::default();
        run_gc(&store, &mut cursor, NO_CAP);

        assert!(
            store.get_merge_drain_applied(&marker).unwrap().is_none(),
            "marker expired by the marker cutoff",
        );
        assert!(
            store.get_tombstone(&tomb).unwrap().is_some(),
            "same-timestamp tombstone is fresh by the longer tombstone cutoff",
        );
    }

    #[test]
    fn scan_cap_is_respected_and_the_remainder_survives_to_the_next_tick() {
        let (_dir, store) = temp_store();
        // Six expired tombstones; cap of 2 deletes only the first two per tick.
        let keys: Vec<TombstoneKey> = (1..=6u128).map(tombstone_key).collect();
        for key in &keys {
            put_tombstone(&store, key, TOMBSTONE_CUTOFF - 1);
        }

        let mut cursor = MergeGcCursor::default();

        run_gc(&store, &mut cursor, 2);
        let surviving = keys
            .iter()
            .filter(|k| store.get_tombstone(k).unwrap().is_some())
            .count();
        assert_eq!(surviving, 4, "tick 1 deleted exactly the cap of 2");

        run_gc(&store, &mut cursor, 2);
        let surviving = keys
            .iter()
            .filter(|k| store.get_tombstone(k).unwrap().is_some())
            .count();
        assert_eq!(surviving, 2, "tick 2 deleted the next 2");

        // Tick 3 drains the last 2 (a short page → exhausted, wraps).
        run_gc(&store, &mut cursor, 2);
        assert!(
            keys.iter()
                .all(|k| store.get_tombstone(k).unwrap().is_none()),
            "all expired tombstones gone after three capped ticks",
        );
    }

    #[test]
    fn cursor_resumes_mid_prefix_and_wraps_on_exhaustion() {
        let (_dir, store) = temp_store();
        // Three FRESH tombstones (none expire), so the cap-bounded scan must advance past them via
        // the cursor rather than re-scanning the same survivors forever.
        let keys: Vec<TombstoneKey> = (1..=3u128).map(tombstone_key).collect();
        for key in &keys {
            put_tombstone(&store, key, TOMBSTONE_CUTOFF + 1);
        }

        let mut cursor = MergeGcCursor::default();

        // Cap 1: tick 1 scans key 1 (full page → cursor set past key 1).
        run_gc(&store, &mut cursor, 1);
        assert!(
            cursor.tombstones.is_some(),
            "a full page advances the cursor mid-prefix",
        );
        let after_tick1 = cursor.tombstones.clone();

        // Tick 2 must resume past key 1 (cursor moves), not restart.
        run_gc(&store, &mut cursor, 1);
        assert_ne!(cursor.tombstones, after_tick1, "cursor advanced to key 2");

        // Tick 3 scans key 3 (still a full page of 1).
        run_gc(&store, &mut cursor, 1);
        // Tick 4 finds nothing past key 3 → short (empty) page → wraps to the start.
        run_gc(&store, &mut cursor, 1);
        assert!(
            cursor.tombstones.is_none(),
            "exhausting the slice wraps the cursor to the prefix start",
        );

        // All three survived (fresh) throughout.
        assert!(keys
            .iter()
            .all(|k| store.get_tombstone(k).unwrap().is_some()));
    }

    #[test]
    fn undecodable_value_is_deleted() {
        let (_dir, store) = temp_store();
        let key = tombstone_key(1);
        // Stage a tombstone slot with a garbage value the decoder rejects.
        store
            .write_batch(|batch| batch.put_tombstone(&key, b"not-a-tombstone"))
            .unwrap();

        let mut cursor = MergeGcCursor::default();
        run_gc(&store, &mut cursor, NO_CAP);

        assert!(
            store.get_tombstone(&key).unwrap().is_none(),
            "an undecodable value is deleted (it can never age out)",
        );
    }

    #[test]
    fn pending_transfers_are_untouched_by_a_gc_tick() {
        let (_dir, store) = temp_store();
        let pending_key = PendingTransferKey {
            partition_id: PARTITION,
            team_id: TEAM,
            old_person: Uuid::from_u128(1),
        };
        store
            .write_batch(|batch| batch.put_pending_transfer(&pending_key, b"outbox-entry"))
            .unwrap();
        // Also stage an expired tombstone so the tick does real work.
        let tomb = tombstone_key(2);
        put_tombstone(&store, &tomb, TOMBSTONE_CUTOFF - 1);

        let mut cursor = MergeGcCursor::default();
        run_gc(&store, &mut cursor, NO_CAP);

        assert!(
            store.get_pending_transfer(&pending_key).unwrap().is_some(),
            "the redrive outbox is never GC'd",
        );
        assert!(
            store.get_tombstone(&tomb).unwrap().is_none(),
            "the GC still did its real work",
        );
    }
}
