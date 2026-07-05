//! Owned, `Send`-able write staging that can cross a `spawn_blocking` boundary.
//!
//! [`BatchBuilder`](super::rocks::BatchBuilder) borrows the store's CF handles, so a batch built
//! through it is tied to the store's lifetime and cannot be moved into a `'static` blocking closure.
//! [`StagedBatch`] is the owned counterpart: each staging call encodes its key into owned bytes at
//! call time and remembers only the target [`Cf`], so the value is `Send + 'static` and can be
//! replayed on a background thread via [`CohortStore::apply`](super::rocks::CohortStore::apply).
//!
//! The staging surface mirrors `BatchBuilder` one-to-one and encodes identically, so a sequence
//! staged here and applied through `apply` is byte-for-byte the same set of RocksDB operations as
//! that sequence built through `BatchBuilder` and committed through `write_batch`.

use super::column_families::{Cf, OpaqueCf};
use super::keys::{MergeAppliedKey, MergeDrainKey, PendingTransferKey, Stage2Key, TombstoneKey};
use super::keyspace::Keyspace;

/// One staged RocksDB operation with owned bytes, so the batch is `Send + 'static`.
pub(crate) enum StagedOp {
    Put {
        cf: Cf,
        key: Vec<u8>,
        value: Vec<u8>,
    },
    Delete {
        cf: Cf,
        key: Vec<u8>,
    },
}

/// Owned, `Send`-able staging for a multi-CF `WriteBatch`, mirroring
/// [`BatchBuilder`](super::rocks::BatchBuilder) one-to-one.
///
/// Stage operations with the typed methods, then replay them into one atomic batch with
/// [`CohortStore::apply`](super::rocks::CohortStore::apply). Holds no borrowed CF handles, so it can
/// move across thread boundaries.
#[must_use]
#[derive(Default)]
pub struct StagedBatch {
    ops: Vec<StagedOp>,
}

impl StagedBatch {
    pub fn is_empty(&self) -> bool {
        self.ops.is_empty()
    }

    pub fn len(&self) -> usize {
        self.ops.len()
    }

    pub(crate) fn ops(&self) -> &[StagedOp] {
        &self.ops
    }

    /// Put a typed key/value into its keyspace's CF. The [`Keyspace`] binding routes to the right CF,
    /// so a key cannot be staged for the wrong column family.
    pub fn put<K: Keyspace>(&mut self, key: &K::Key, value: &[u8]) {
        self.ops.push(StagedOp::Put {
            cf: K::CF,
            key: K::encode(key),
            value: value.to_vec(),
        });
    }

    /// Delete a typed key from its keyspace's CF.
    pub fn delete<K: Keyspace>(&mut self, key: &K::Key) {
        self.ops.push(StagedOp::Delete {
            cf: K::CF,
            key: K::encode(key),
        });
    }

    pub fn put_stage2(&mut self, key: &Stage2Key, value: &[u8]) {
        self.ops.push(StagedOp::Put {
            cf: Cf::Stage2,
            key: key.encode().to_vec(),
            value: value.to_vec(),
        });
    }

    pub fn delete_stage2(&mut self, key: &Stage2Key) {
        self.ops.push(StagedOp::Delete {
            cf: Cf::Stage2,
            key: key.encode().to_vec(),
        });
    }

    /// Stage the Phase 1 idempotence marker for a drained merge message.
    pub fn put_merge_drain_applied(&mut self, key: &MergeDrainKey, value: &[u8]) {
        self.ops.push(StagedOp::Put {
            cf: Cf::MergeDrainsApplied,
            key: key.encode().to_vec(),
            value: value.to_vec(),
        });
    }

    /// GC-delete one expired Phase 1 idempotence marker.
    pub fn delete_merge_drain_applied(&mut self, key: &MergeDrainKey) {
        self.ops.push(StagedOp::Delete {
            cf: Cf::MergeDrainsApplied,
            key: key.encode().to_vec(),
        });
    }

    /// Stage a packaged merge into the outbox.
    pub fn put_pending_transfer(&mut self, key: &PendingTransferKey, value: &[u8]) {
        self.ops.push(StagedOp::Put {
            cf: Cf::PendingTransfers,
            key: key.encode().to_vec(),
            value: value.to_vec(),
        });
    }

    /// Clear an outbox slot once its transfer is acked.
    pub fn delete_pending_transfer(&mut self, key: &PendingTransferKey) {
        self.ops.push(StagedOp::Delete {
            cf: Cf::PendingTransfers,
            key: key.encode().to_vec(),
        });
    }

    /// Stage the Phase 2 idempotence marker for an applied transfer message.
    pub fn put_merge_applied(&mut self, key: &MergeAppliedKey, value: &[u8]) {
        self.ops.push(StagedOp::Put {
            cf: Cf::MergeApplied,
            key: key.encode().to_vec(),
            value: value.to_vec(),
        });
    }

    /// GC-delete one expired Phase 2 idempotence marker.
    pub fn delete_merge_applied(&mut self, key: &MergeAppliedKey) {
        self.ops.push(StagedOp::Delete {
            cf: Cf::MergeApplied,
            key: key.encode().to_vec(),
        });
    }

    /// Stage the redirect tombstone for a merged-away person.
    pub fn put_tombstone(&mut self, key: &TombstoneKey, value: &[u8]) {
        self.ops.push(StagedOp::Put {
            cf: Cf::MergeTombstones,
            key: key.encode().to_vec(),
            value: value.to_vec(),
        });
    }

    /// GC-delete one expired redirect tombstone.
    pub fn delete_tombstone(&mut self, key: &TombstoneKey) {
        self.ops.push(StagedOp::Delete {
            cf: Cf::MergeTombstones,
            key: key.encode().to_vec(),
        });
    }

    /// Raw put by pre-encoded key bytes. Restricted to [`OpaqueCf`].
    pub fn put_raw(&mut self, cf: OpaqueCf, key: &[u8], value: &[u8]) {
        self.ops.push(StagedOp::Put {
            cf: cf.cf(),
            key: key.to_vec(),
            value: value.to_vec(),
        });
    }
}

#[cfg(test)]
// Tests drive the store directly through `CohortStore` (`write_batch`/`apply`/`get_*`) — the
// sanctioned direct-store surface for tests — to pin that `apply` writes exactly what `write_batch`
// does.
#[allow(clippy::disallowed_methods)]
mod tests {
    use tempfile::TempDir;
    use uuid::Uuid;

    use super::*;
    use crate::stage1::key::LeafStateKey;
    use crate::store::keyspace::{Behavioral, BehavioralKey};
    use crate::store::rocks::{BatchBuilder, CohortStore, StoreConfig};

    const PARTITION: u16 = 3;
    const TEAM: u64 = 7;
    const LARGE_LIMIT: usize = 1024;

    fn behavioral_key(person: u128, lsk: u8) -> BehavioralKey {
        BehavioralKey::new(
            PARTITION,
            TEAM,
            Uuid::from_u128(person),
            LeafStateKey([lsk; 16]),
        )
    }

    fn stage2_key(person: u128, cohort: u64) -> Stage2Key {
        Stage2Key {
            partition_id: PARTITION,
            team_id: TEAM,
            cohort_id: cohort,
            person_id: Uuid::from_u128(person),
        }
    }

    fn merge_drain_key(person: u128) -> MergeDrainKey {
        MergeDrainKey {
            partition_id: PARTITION,
            team_id: TEAM,
            old_person: Uuid::from_u128(person),
            merge_msg_partition: 1,
            merge_msg_offset: 2,
        }
    }

    fn pending_transfer_key(person: u128) -> PendingTransferKey {
        PendingTransferKey {
            partition_id: PARTITION,
            team_id: TEAM,
            old_person: Uuid::from_u128(person),
        }
    }

    fn merge_applied_key(person: u128) -> MergeAppliedKey {
        MergeAppliedKey {
            partition_id: PARTITION,
            team_id: TEAM,
            new_person: Uuid::from_u128(person),
            source_partition: 4,
            source_offset: 5,
        }
    }

    fn tombstone_key(person: u128) -> TombstoneKey {
        TombstoneKey {
            partition_id: PARTITION,
            team_id: TEAM,
            person: Uuid::from_u128(person),
        }
    }

    fn open_store(dir: &TempDir, name: &str) -> CohortStore {
        CohortStore::open(&StoreConfig {
            path: dir.path().join(name),
            ..StoreConfig::default()
        })
        .unwrap()
    }

    /// Drives every staging method through `BatchBuilder`, including a behavioral put that survives and
    /// one cancelled by a delete, and both `OpaqueCf` arms of `put_raw`.
    fn drive_batch_builder(b: &mut BatchBuilder<'_>) {
        b.put::<Behavioral>(&behavioral_key(1, 0xA0), b"s1-put");
        b.put::<Behavioral>(&behavioral_key(2, 0xA1), b"s1-doomed");
        b.delete::<Behavioral>(&behavioral_key(2, 0xA1));

        b.put_stage2(&stage2_key(1, 100), b"s2-put");
        b.put_stage2(&stage2_key(2, 200), b"s2-doomed");
        b.delete_stage2(&stage2_key(2, 200));

        b.put_merge_drain_applied(&merge_drain_key(1), b"drain-put");
        b.delete_merge_drain_applied(&merge_drain_key(2));

        b.put_pending_transfer(&pending_transfer_key(1), b"transfer-put");
        b.delete_pending_transfer(&pending_transfer_key(2));

        b.put_merge_applied(&merge_applied_key(1), b"applied-put");
        b.delete_merge_applied(&merge_applied_key(2));

        b.put_tombstone(&tombstone_key(1), b"tombstone-put");
        b.delete_tombstone(&tombstone_key(2));

        b.put_raw(
            OpaqueCf::Behavioral,
            &behavioral_key(9, 0xF0).encode(),
            b"raw-s1",
        );
        b.put_raw(OpaqueCf::Stage2, &stage2_key(9, 900).encode(), b"raw-s2");
    }

    /// The same sequence as [`drive_batch_builder`], staged into a `StagedBatch`.
    fn drive_staged_batch(s: &mut StagedBatch) {
        s.put::<Behavioral>(&behavioral_key(1, 0xA0), b"s1-put");
        s.put::<Behavioral>(&behavioral_key(2, 0xA1), b"s1-doomed");
        s.delete::<Behavioral>(&behavioral_key(2, 0xA1));

        s.put_stage2(&stage2_key(1, 100), b"s2-put");
        s.put_stage2(&stage2_key(2, 200), b"s2-doomed");
        s.delete_stage2(&stage2_key(2, 200));

        s.put_merge_drain_applied(&merge_drain_key(1), b"drain-put");
        s.delete_merge_drain_applied(&merge_drain_key(2));

        s.put_pending_transfer(&pending_transfer_key(1), b"transfer-put");
        s.delete_pending_transfer(&pending_transfer_key(2));

        s.put_merge_applied(&merge_applied_key(1), b"applied-put");
        s.delete_merge_applied(&merge_applied_key(2));

        s.put_tombstone(&tombstone_key(1), b"tombstone-put");
        s.delete_tombstone(&tombstone_key(2));

        s.put_raw(
            OpaqueCf::Behavioral,
            &behavioral_key(9, 0xF0).encode(),
            b"raw-s1",
        );
        s.put_raw(OpaqueCf::Stage2, &stage2_key(9, 900).encode(), b"raw-s2");
    }

    #[test]
    fn staged_batch_apply_writes_exactly_what_batch_builder_writes() {
        let dir = TempDir::new().unwrap();
        let via_builder = open_store(&dir, "builder");
        let via_staged = open_store(&dir, "staged");

        via_builder.write_batch(drive_batch_builder).unwrap();

        let mut staged = StagedBatch::default();
        drive_staged_batch(&mut staged);
        assert!(!staged.is_empty());
        assert_eq!(staged.len(), 16);
        via_staged.apply(&staged).unwrap();

        // `scan_merge_cf` is CF-generic and all keys carry the partition prefix, so it enumerates any
        // partitioned CF's slice.
        for cf in Cf::ALL {
            if !cf.partitioned() {
                continue;
            }
            let builder_kvs = via_builder
                .scan_merge_cf(cf, PARTITION, None, LARGE_LIMIT)
                .unwrap();
            let staged_kvs = via_staged
                .scan_merge_cf(cf, PARTITION, None, LARGE_LIMIT)
                .unwrap();
            assert_eq!(
                builder_kvs, staged_kvs,
                "CF {cf:?} diverged between write_batch and StagedBatch::apply",
            );
        }

        // The surviving behavioral put leaves exactly one row; the put-then-deleted one is gone.
        assert_eq!(
            via_staged
                .get_behavioral(&behavioral_key(1, 0xA0))
                .unwrap()
                .as_deref(),
            Some(b"s1-put".as_slice()),
        );
        assert_eq!(
            via_staged.get_behavioral(&behavioral_key(2, 0xA1)).unwrap(),
            None,
        );
    }

    #[test]
    fn default_staged_batch_is_empty() {
        let batch = StagedBatch::default();
        assert!(batch.is_empty());
        assert_eq!(batch.len(), 0);
    }

    // The type exists to cross a `spawn_blocking` boundary: a field that is not `Send + 'static` must
    // fail here, not at the distant offload call site.
    #[test]
    fn staged_batch_is_send_and_static() {
        fn assert_send_static<T: Send + 'static>() {}
        assert_send_static::<StagedBatch>();
    }
}
