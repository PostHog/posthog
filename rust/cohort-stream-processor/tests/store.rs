//! PR 1.2 acceptance, end-to-end against a real RocksDB in a temp dir, through the public API
//! only: per-CF point writes, atomic cross-CF `WriteBatch`, the secondary-index merge operator,
//! `delete_partition` isolation, and reopen-after-flush persistence.

use cohort_stream_processor::store::{
    Cf, CohortStore, IndexOp, LeafStateKey, OpaqueCf, PersonIndexKey, Stage1Key, Stage2Key,
    StoreConfig,
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

fn stage1_key(partition: u16, team: u64, leaf: u8, p: u128) -> Stage1Key {
    Stage1Key {
        partition_id: partition,
        team_id: team,
        leaf_state_key: lsk(leaf),
        person_id: person(p),
    }
}

fn person_index_key(partition: u16, team: u64, p: u128) -> PersonIndexKey {
    PersonIndexKey {
        partition_id: partition,
        team_id: team,
        person_id: person(p),
    }
}

fn stage2_key(partition: u16, team: u64, cohort: u64, p: u128) -> Stage2Key {
    Stage2Key {
        partition_id: partition,
        team_id: team,
        cohort_id: cohort,
        person_id: person(p),
    }
}

/// Acceptance 1 — point writes and reads on each CF; misses read as absent/empty.
#[test]
fn point_writes_and_reads_per_cf() {
    let dir = TempDir::new().unwrap();
    let store = open_store(&dir);

    let s1 = stage1_key(0, 100, 1, 7);
    let s2 = stage2_key(0, 100, 55, 7);
    let pix = person_index_key(0, 100, 7);

    store
        .write_batch(|b| {
            b.put_stage1(&s1, b"stage1-value");
            b.put_stage2(&s2, b"stage2-value");
            b.merge_person_index(&pix, IndexOp::Append(lsk(1)));
        })
        .unwrap();

    assert_eq!(
        store.get_stage1(&s1).unwrap().as_deref(),
        Some(&b"stage1-value"[..])
    );
    assert_eq!(
        store.get_stage2(&s2).unwrap().as_deref(),
        Some(&b"stage2-value"[..])
    );
    assert_eq!(store.get_person_index(&pix).unwrap(), vec![lsk(1)]);

    // Raw read through the generic accessor agrees with the typed one.
    assert_eq!(
        store.get(Cf::Stage1, &s1.encode()).unwrap().as_deref(),
        Some(&b"stage1-value"[..])
    );

    // Absent keys: `None` for opaque CFs, empty set for the person index.
    assert!(store
        .get_stage1(&stage1_key(0, 100, 1, 999))
        .unwrap()
        .is_none());
    assert!(store
        .get_person_index(&person_index_key(0, 100, 999))
        .unwrap()
        .is_empty());
}

/// The typed escape hatch: a raw put by pre-encoded key bytes lands in the addressed opaque CF and
/// reads back through both the generic and typed accessors. `cf_person_index` is merge-only and not
/// an `OpaqueCf` variant, so a raw put to it cannot be expressed here (it would not compile).
#[test]
fn put_raw_writes_to_the_addressed_opaque_cf() {
    let dir = TempDir::new().unwrap();
    let store = open_store(&dir);

    let s1 = stage1_key(4, 100, 7, 11);
    let s2 = stage2_key(4, 100, 88, 11);

    store
        .write_batch(|b| {
            b.put_raw(OpaqueCf::Stage1, &s1.encode(), b"raw-s1");
            b.put_raw(OpaqueCf::Stage2, &s2.encode(), b"raw-s2");
        })
        .unwrap();

    assert_eq!(
        store.get_stage1(&s1).unwrap().as_deref(),
        Some(&b"raw-s1"[..])
    );
    assert_eq!(
        store.get(Cf::Stage1, &s1.encode()).unwrap().as_deref(),
        Some(&b"raw-s1"[..])
    );
    assert_eq!(
        store.get_stage2(&s2).unwrap().as_deref(),
        Some(&b"raw-s2"[..])
    );
}

/// Acceptance 2 — the §2.5:301 invariant: a `cf_stage1` put and its `cf_person_index` append are
/// applied in one atomic `WriteBatch`, and both are visible afterward.
#[test]
fn cross_cf_write_batch_is_atomic() {
    let dir = TempDir::new().unwrap();
    let store = open_store(&dir);

    let s1 = stage1_key(3, 200, 9, 42);
    let pix = person_index_key(3, 200, 42);

    store
        .write_batch(|b| {
            b.put_stage1(&s1, b"v");
            b.merge_person_index(&pix, IndexOp::Append(s1.leaf_state_key));
        })
        .unwrap();

    assert_eq!(store.get_stage1(&s1).unwrap().as_deref(), Some(&b"v"[..]));
    assert_eq!(store.get_person_index(&pix).unwrap(), vec![lsk(9)]);
}

/// Acceptance 3 — append/remove through the real merge operator, forcing on-disk collapse with a
/// flush. Removing every entry must read back as empty — not a "Merge operator failed" error,
/// which is what returning `None` from `full_merge` would produce.
#[test]
fn secondary_index_merge_append_and_remove() {
    let dir = TempDir::new().unwrap();
    let store = open_store(&dir);
    let pix = person_index_key(1, 300, 5);

    // Three appends, each its own batch → three separate merge operands.
    for leaf in [10u8, 20, 30] {
        store
            .write_batch(|b| b.merge_person_index(&pix, IndexOp::Append(lsk(leaf))))
            .unwrap();
    }
    assert_eq!(
        store.get_person_index(&pix).unwrap(),
        vec![lsk(10), lsk(20), lsk(30)]
    );

    // Remove the middle one, flush to force the operator to collapse into an SST, read back.
    store
        .write_batch(|b| b.merge_person_index(&pix, IndexOp::Remove(lsk(20))))
        .unwrap();
    store.flush().unwrap();
    assert_eq!(
        store.get_person_index(&pix).unwrap(),
        vec![lsk(10), lsk(30)]
    );

    // Remove the rest → empty set must read back as empty (the merge-`None` correctness case).
    store
        .write_batch(|b| {
            b.merge_person_index(&pix, IndexOp::Remove(lsk(10)));
            b.merge_person_index(&pix, IndexOp::Remove(lsk(30)));
        })
        .unwrap();
    store.flush().unwrap();
    assert_eq!(store.get_person_index(&pix).unwrap(), vec![]);
}

/// Acceptance 4 — `delete_partition` reclaims exactly one partition across all three CFs while a
/// neighbouring partition (identical but for the partition prefix) is untouched.
#[test]
fn delete_partition_isolates_other_partitions() {
    let dir = TempDir::new().unwrap();
    let store = open_store(&dir);

    let write_partition = |p: u16| {
        store
            .write_batch(|b| {
                b.put_stage1(&stage1_key(p, 100, 1, 7), b"s1");
                b.put_stage2(&stage2_key(p, 100, 55, 7), b"s2");
                b.merge_person_index(&person_index_key(p, 100, 7), IndexOp::Append(lsk(1)));
            })
            .unwrap();
    };
    write_partition(0);
    write_partition(1);

    store.delete_partition(0).unwrap();

    // Partition 0 is gone across every CF...
    assert!(store
        .get_stage1(&stage1_key(0, 100, 1, 7))
        .unwrap()
        .is_none());
    assert!(store
        .get_stage2(&stage2_key(0, 100, 55, 7))
        .unwrap()
        .is_none());
    assert!(store
        .get_person_index(&person_index_key(0, 100, 7))
        .unwrap()
        .is_empty());

    // ...and partition 1 survives across every CF.
    assert_eq!(
        store
            .get_stage1(&stage1_key(1, 100, 1, 7))
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
    assert_eq!(
        store
            .get_person_index(&person_index_key(1, 100, 7))
            .unwrap(),
        vec![lsk(1)]
    );
}

/// Acceptance 5 — data written + flushed survives closing and reopening the DB at the same path.
#[test]
fn data_survives_reopen() {
    let dir = TempDir::new().unwrap();
    let config = config_in(&dir);

    let s1 = stage1_key(2, 100, 4, 8);
    let pix = person_index_key(2, 100, 8);

    {
        let store = CohortStore::open(&config).unwrap();
        store
            .write_batch(|b| {
                b.put_stage1(&s1, b"persisted");
                b.merge_person_index(&pix, IndexOp::Append(lsk(4)));
            })
            .unwrap();
        store.flush().unwrap();
    } // store drops here, closing the DB and releasing its lock

    let reopened = CohortStore::open(&config).unwrap();
    assert_eq!(
        reopened.get_stage1(&s1).unwrap().as_deref(),
        Some(&b"persisted"[..])
    );
    assert_eq!(reopened.get_person_index(&pix).unwrap(), vec![lsk(4)]);
}
