//! End-to-end tests against a real RocksDB in a temp dir, through the public API only.

// `CohortStore` is the API under test here, so tests call it directly.
#![allow(clippy::disallowed_methods)]

use cohort_stream_processor::store::{
    Behavioral, BehavioralKey, Cf, CohortStore, LeafStateKey, MergeAppliedKey, MergeDrainKey,
    OpaqueCf, PendingTransferKey, PersonPrefix, Stage2Key, StoreConfig, TombstoneKey,
};
use tempfile::TempDir;
use uuid::Uuid;

fn config_in(dir: &TempDir) -> StoreConfig {
    StoreConfig {
        path: dir.path().join("db"),
        ..StoreConfig::default()
    }
}

fn open_store(dir: &TempDir) -> CohortStore {
    CohortStore::open(&config_in(dir)).expect("open store")
}

fn lsk(b: u8) -> LeafStateKey {
    LeafStateKey([b; 16])
}

fn person(n: u128) -> Uuid {
    Uuid::from_u128(n)
}

fn behavioral_key(partition: u16, team: u64, leaf: u8, p: u128) -> BehavioralKey {
    BehavioralKey::new(partition, team, person(p), lsk(leaf))
}

fn stage2_key(partition: u16, team: u64, cohort: u64, p: u128) -> Stage2Key {
    Stage2Key {
        partition_id: partition,
        team_id: team,
        cohort_id: cohort,
        person_id: person(p),
    }
}

fn merge_drain_key(partition: u16, team: u64, old: u128) -> MergeDrainKey {
    MergeDrainKey {
        partition_id: partition,
        team_id: team,
        old_person: person(old),
        merge_msg_partition: 17,
        merge_msg_offset: 99,
    }
}

fn pending_transfer_key(partition: u16, team: u64, old: u128) -> PendingTransferKey {
    PendingTransferKey {
        partition_id: partition,
        team_id: team,
        old_person: person(old),
    }
}

fn merge_applied_key(partition: u16, team: u64, new: u128) -> MergeAppliedKey {
    MergeAppliedKey {
        partition_id: partition,
        team_id: team,
        new_person: person(new),
        source_partition: 3,
        source_offset: 42,
    }
}

fn tombstone_key(partition: u16, team: u64, p: u128) -> TombstoneKey {
    TombstoneKey {
        partition_id: partition,
        team_id: team,
        person: person(p),
    }
}

#[test]
fn point_writes_and_reads_per_cf() {
    let dir = TempDir::new().unwrap();
    let store = open_store(&dir);

    let s1 = behavioral_key(0, 100, 1, 7);
    let s2 = stage2_key(0, 100, 55, 7);

    store
        .write_batch(|b| {
            b.put::<Behavioral>(&s1, b"behavioral-value");
            b.put_stage2(&s2, b"stage2-value");
        })
        .unwrap();

    assert_eq!(
        store.get_behavioral(&s1).unwrap().as_deref(),
        Some(&b"behavioral-value"[..])
    );
    assert_eq!(
        store.get_stage2(&s2).unwrap().as_deref(),
        Some(&b"stage2-value"[..])
    );

    assert_eq!(
        store.get(Cf::Behavioral, &s1.encode()).unwrap().as_deref(),
        Some(&b"behavioral-value"[..])
    );

    assert!(store
        .get_behavioral(&behavioral_key(0, 100, 1, 999))
        .unwrap()
        .is_none());
}

#[test]
fn put_raw_writes_to_the_addressed_opaque_cf() {
    let dir = TempDir::new().unwrap();
    let store = open_store(&dir);

    let s1 = behavioral_key(4, 100, 7, 11);
    let s2 = stage2_key(4, 100, 88, 11);

    store
        .write_batch(|b| {
            b.put_raw(OpaqueCf::Behavioral, &s1.encode(), b"raw-s1");
            b.put_raw(OpaqueCf::Stage2, &s2.encode(), b"raw-s2");
        })
        .unwrap();

    assert_eq!(
        store.get_behavioral(&s1).unwrap().as_deref(),
        Some(&b"raw-s1"[..])
    );
    assert_eq!(
        store.get(Cf::Behavioral, &s1.encode()).unwrap().as_deref(),
        Some(&b"raw-s1"[..])
    );
    assert_eq!(
        store.get_stage2(&s2).unwrap().as_deref(),
        Some(&b"raw-s2"[..])
    );
}

#[test]
fn cross_cf_write_batch_is_atomic() {
    let dir = TempDir::new().unwrap();
    let store = open_store(&dir);

    let s1 = behavioral_key(3, 200, 9, 42);
    let s2 = stage2_key(3, 200, 88, 42);

    store
        .write_batch(|b| {
            b.put::<Behavioral>(&s1, b"v");
            b.put_stage2(&s2, b"w");
        })
        .unwrap();

    assert_eq!(
        store.get_behavioral(&s1).unwrap().as_deref(),
        Some(&b"v"[..])
    );
    assert_eq!(store.get_stage2(&s2).unwrap().as_deref(), Some(&b"w"[..]));
}

/// A person's leaves are one contiguous prefix slice: a prefix scan returns exactly them in lsk order,
/// crossing neither into an adjacent person nor an adjacent partition.
#[test]
fn behavioral_prefix_scan_returns_one_persons_leaves_in_lsk_order() {
    let dir = TempDir::new().unwrap();
    let store = open_store(&dir);

    store
        .write_batch(|b| {
            for leaf in [30u8, 10, 20] {
                b.put::<Behavioral>(&behavioral_key(1, 300, leaf, 5), b"v");
            }
            // A neighbouring person in the same partition, and the same person in another partition.
            b.put::<Behavioral>(&behavioral_key(1, 300, 99, 6), b"other-person");
            b.put::<Behavioral>(&behavioral_key(2, 300, 10, 5), b"other-partition");
        })
        .unwrap();
    store.flush().unwrap();

    let rows = store
        .scan_behavioral_prefix(PersonPrefix::new(1, 300, person(5)))
        .unwrap();
    let leaves: Vec<[u8; 16]> = rows.iter().map(|(k, _)| k.lsk().0).collect();
    assert_eq!(
        leaves,
        vec![lsk(10).0, lsk(20).0, lsk(30).0],
        "exactly person 5's leaves, in lsk-byte order, never leaking to a neighbour",
    );
}

#[test]
fn behavioral_prefix_scan_spans_multiple_flushed_ssts() {
    // The single-batch test above flushes once, so the scan only ever reads one SST. Force one
    // person's leaves across two flushed SSTs so the prefix seek (prefix bloom + upper-bound iterator)
    // is exercised across an SST boundary: a scan that stops one key early, or lets the prefix bloom
    // skip a live SST, would pass the single-SST test but fail here.
    let dir = TempDir::new().unwrap();
    let store = open_store(&dir);

    // SST 1: person 5's leaf 10, plus a neighbouring person that must not leak into the scan.
    store
        .write_batch(|b| {
            b.put::<Behavioral>(&behavioral_key(1, 300, 10, 5), b"a");
            b.put::<Behavioral>(&behavioral_key(1, 300, 99, 6), b"other-person");
        })
        .unwrap();
    store.flush().unwrap();

    // SST 2: person 5's leaves 30 and 20 (written out of order), plus the same person in another
    // partition, which shares neither the partition nor the person prefix.
    store
        .write_batch(|b| {
            b.put::<Behavioral>(&behavioral_key(1, 300, 30, 5), b"c");
            b.put::<Behavioral>(&behavioral_key(1, 300, 20, 5), b"b");
            b.put::<Behavioral>(&behavioral_key(2, 300, 10, 5), b"other-partition");
        })
        .unwrap();
    store.flush().unwrap();

    let rows = store
        .scan_behavioral_prefix(PersonPrefix::new(1, 300, person(5)))
        .unwrap();
    let leaves: Vec<[u8; 16]> = rows.iter().map(|(k, _)| k.lsk().0).collect();
    assert_eq!(
        leaves,
        vec![lsk(10).0, lsk(20).0, lsk(30).0],
        "person 5's leaves stay contiguous and in lsk order across two SSTs, no neighbour leak",
    );
}

#[test]
fn delete_partition_isolates_other_partitions() {
    let dir = TempDir::new().unwrap();
    let store = open_store(&dir);

    let write_partition = |p: u16| {
        store
            .write_batch(|b| {
                b.put::<Behavioral>(&behavioral_key(p, 100, 1, 7), b"s1");
                b.put_stage2(&stage2_key(p, 100, 55, 7), b"s2");
            })
            .unwrap();
    };
    write_partition(0);
    write_partition(1);

    store.delete_partition(0).unwrap();

    assert!(store
        .get_behavioral(&behavioral_key(0, 100, 1, 7))
        .unwrap()
        .is_none());
    assert!(store
        .get_stage2(&stage2_key(0, 100, 55, 7))
        .unwrap()
        .is_none());

    assert_eq!(
        store
            .get_behavioral(&behavioral_key(1, 100, 1, 7))
            .unwrap()
            .as_deref(),
        Some(&b"s1"[..])
    );
    assert_eq!(
        store
            .get_stage2(&stage2_key(1, 100, 55, 7))
            .unwrap()
            .as_deref(),
        Some(&b"s2"[..])
    );
}

#[test]
fn data_survives_reopen() {
    let dir = TempDir::new().unwrap();
    let config = config_in(&dir);

    let s1 = behavioral_key(2, 100, 4, 8);

    {
        let store = CohortStore::open(&config).unwrap();
        store
            .write_batch(|b| {
                b.put::<Behavioral>(&s1, b"persisted");
            })
            .unwrap();
        store.flush().unwrap();
    } // drop releases the DB lock so the reopen below can acquire it

    let reopened = CohortStore::open(&config).unwrap();
    assert_eq!(
        reopened.get_behavioral(&s1).unwrap().as_deref(),
        Some(&b"persisted"[..])
    );
}

#[test]
fn one_write_batch_spans_state_and_merge_cfs_atomically() {
    let dir = TempDir::new().unwrap();
    let store = open_store(&dir);

    let s1 = behavioral_key(2, 100, 1, 7);
    let s2 = stage2_key(2, 100, 55, 7);
    let drain = merge_drain_key(2, 100, 7);
    let pending = pending_transfer_key(2, 100, 7);
    let applied = merge_applied_key(2, 100, 8);
    let tombstone = tombstone_key(2, 100, 7);

    // A drain-shaped batch: delete P_old's whole prefix slice, stage the outbox + idempotence markers
    // + tombstone, all in one WriteBatch spanning the old and new CFs.
    store
        .write_batch(|b| {
            b.put::<Behavioral>(&s1, b"old-state");
            b.put_stage2(&s2, b"old-stage2");
        })
        .unwrap();
    store
        .write_batch(|b| {
            b.delete_behavioral_prefix(&PersonPrefix::new(2, 100, person(7)));
            b.delete_stage2(&s2);
            b.put_merge_drain_applied(&drain, b"drained_at");
            b.put_pending_transfer(&pending, b"transfer-payload");
            b.put_merge_applied(&applied, b"applied_at");
            b.put_tombstone(&tombstone, b"P_new+merged_at");
        })
        .unwrap();

    assert!(
        store.get_behavioral(&s1).unwrap().is_none(),
        "P_old state deleted"
    );
    assert!(store.get_stage2(&s2).unwrap().is_none());
    assert_eq!(
        store.get_merge_drain_applied(&drain).unwrap().as_deref(),
        Some(&b"drained_at"[..]),
    );
    assert_eq!(
        store.get_pending_transfer(&pending).unwrap().as_deref(),
        Some(&b"transfer-payload"[..]),
    );
    assert_eq!(
        store.get_merge_applied(&applied).unwrap().as_deref(),
        Some(&b"applied_at"[..]),
    );
    assert_eq!(
        store.get_tombstone(&tombstone).unwrap().as_deref(),
        Some(&b"P_new+merged_at"[..]),
    );

    store
        .write_batch(|b| b.delete_pending_transfer(&pending))
        .unwrap();
    assert!(store.get_pending_transfer(&pending).unwrap().is_none());
    assert!(
        store.get_tombstone(&tombstone).unwrap().is_some(),
        "clearing the outbox leaves the tombstone in place",
    );
}

#[test]
fn delete_partition_reclaims_the_merge_cfs() {
    let dir = TempDir::new().unwrap();
    let store = open_store(&dir);

    let seed = |p: u16| {
        store
            .write_batch(|b| {
                b.put_merge_drain_applied(&merge_drain_key(p, 100, 7), b"d");
                b.put_pending_transfer(&pending_transfer_key(p, 100, 7), b"t");
                b.put_merge_applied(&merge_applied_key(p, 100, 8), b"a");
                b.put_tombstone(&tombstone_key(p, 100, 7), b"s");
            })
            .unwrap();
    };
    seed(0);
    seed(1);

    store.delete_partition(0).unwrap();

    assert!(store
        .get_merge_drain_applied(&merge_drain_key(0, 100, 7))
        .unwrap()
        .is_none());
    assert!(store
        .get_pending_transfer(&pending_transfer_key(0, 100, 7))
        .unwrap()
        .is_none());
    assert!(store
        .get_merge_applied(&merge_applied_key(0, 100, 8))
        .unwrap()
        .is_none());
    assert!(store
        .get_tombstone(&tombstone_key(0, 100, 7))
        .unwrap()
        .is_none());
    assert!(store
        .scan_pending_transfers(0, None, usize::MAX)
        .unwrap()
        .is_empty());

    assert!(store
        .get_tombstone(&tombstone_key(1, 100, 7))
        .unwrap()
        .is_some());
    assert_eq!(
        store
            .scan_pending_transfers(1, None, usize::MAX)
            .unwrap()
            .len(),
        1
    );
}

#[test]
fn scan_pending_transfers_returns_only_its_partition_in_key_order() {
    let dir = TempDir::new().unwrap();
    let store = open_store(&dir);

    // Two persons in partition 5 (inserted out of order), one in the neighbouring partitions 4 and 6.
    store
        .write_batch(|b| {
            b.put_pending_transfer(&pending_transfer_key(5, 100, 30), b"p30");
            b.put_pending_transfer(&pending_transfer_key(5, 100, 10), b"p10");
            b.put_pending_transfer(&pending_transfer_key(4, 100, 99), b"p4");
            b.put_pending_transfer(&pending_transfer_key(6, 100, 99), b"p6");
        })
        .unwrap();

    let scanned = store.scan_pending_transfers(5, None, usize::MAX).unwrap();
    assert_eq!(scanned.len(), 2, "only partition 5's entries");
    // Person UUIDs from `Uuid::from_u128` sort by their big-endian bytes, so 10 precedes 30.
    assert_eq!(scanned[0].0, pending_transfer_key(5, 100, 10));
    assert_eq!(scanned[0].1, b"p10");
    assert_eq!(scanned[1].0, pending_transfer_key(5, 100, 30));
    assert_eq!(scanned[1].1, b"p30");

    assert_eq!(
        store
            .scan_pending_transfers(4, None, usize::MAX)
            .unwrap()
            .len(),
        1
    );
    assert_eq!(
        store
            .scan_pending_transfers(6, None, usize::MAX)
            .unwrap()
            .len(),
        1
    );
    assert!(
        store
            .scan_pending_transfers(7, None, usize::MAX)
            .unwrap()
            .is_empty(),
        "an empty partition scans to nothing",
    );
}

#[test]
fn scan_pending_transfers_caps_at_the_limit() {
    let dir = TempDir::new().unwrap();
    let store = open_store(&dir);

    // Stage more entries than the limit; the bounded scan must early-break and return exactly `limit`.
    let limit = 5usize;
    store
        .write_batch(|b| {
            for old in 0..(limit as u128 + 3) {
                b.put_pending_transfer(&pending_transfer_key(2, 100, old), b"v");
            }
        })
        .unwrap();

    let scanned = store.scan_pending_transfers(2, None, limit).unwrap();
    assert_eq!(
        scanned.len(),
        limit,
        "the scan stops at the limit even though more entries exist",
    );
    // The early-break keeps the lowest keys in order (UUIDs from `Uuid::from_u128` sort big-endian).
    let firsts: Vec<_> = scanned.iter().map(|(k, _)| k.old_person).collect();
    assert_eq!(
        firsts,
        (0..limit as u128).map(person).collect::<Vec<_>>(),
        "returns the `limit` smallest keys, in key order",
    );
}

#[test]
fn scan_pending_transfers_resumes_after_the_cursor() {
    let dir = TempDir::new().unwrap();
    let store = open_store(&dir);

    store
        .write_batch(|b| {
            for old in 0..5u128 {
                b.put_pending_transfer(&pending_transfer_key(2, 100, old), b"v");
            }
        })
        .unwrap();

    // Walk the slice two at a time, resuming strictly after the last key of each page. The cursor is
    // exclusive, so the union of the pages is every key exactly once with no overlap and no gap.
    let mut seen = Vec::new();
    let mut cursor: Option<Vec<u8>> = None;
    loop {
        let page = store
            .scan_pending_transfers(2, cursor.as_deref(), 2)
            .unwrap();
        if page.is_empty() {
            break;
        }
        cursor = Some(page.last().unwrap().0.encode().to_vec());
        let last_was_short = page.len() < 2;
        seen.extend(page.into_iter().map(|(k, _)| k.old_person));
        if last_was_short {
            break;
        }
    }

    assert_eq!(
        seen,
        (0..5u128).map(person).collect::<Vec<_>>(),
        "paginating with the cursor yields every key once, in key order",
    );
}

#[test]
fn merge_cf_values_survive_reopen_without_wipe() {
    let dir = TempDir::new().unwrap();
    let config = config_in(&dir);

    let drain = merge_drain_key(2, 100, 7);
    let pending = pending_transfer_key(2, 100, 7);
    let applied = merge_applied_key(2, 100, 8);
    let tombstone = tombstone_key(2, 100, 7);

    {
        let store = CohortStore::open(&config).unwrap();
        store
            .write_batch(|b| {
                b.put_merge_drain_applied(&drain, b"d");
                b.put_pending_transfer(&pending, b"t");
                b.put_merge_applied(&applied, b"a");
                b.put_tombstone(&tombstone, b"s");
            })
            .unwrap();
        store.flush().unwrap();
    } // drop releases the DB lock

    let reopened = CohortStore::open(&config).unwrap();
    assert_eq!(
        reopened.get_merge_drain_applied(&drain).unwrap().as_deref(),
        Some(&b"d"[..]),
    );
    assert_eq!(
        reopened.get_pending_transfer(&pending).unwrap().as_deref(),
        Some(&b"t"[..]),
    );
    assert_eq!(
        reopened.get_merge_applied(&applied).unwrap().as_deref(),
        Some(&b"a"[..]),
    );
    assert_eq!(
        reopened.get_tombstone(&tombstone).unwrap().as_deref(),
        Some(&b"s"[..]),
    );
    let scanned = reopened
        .scan_pending_transfers(2, None, usize::MAX)
        .unwrap();
    assert_eq!(scanned, vec![(pending, b"t".to_vec())]);
}
