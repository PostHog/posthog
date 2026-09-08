//! Death-document settle: a pruned mark drops its death document from the
//! cache, and only its own — the removal is version-conditional and
//! serialized on the per-key lock.

mod common;

use std::sync::Arc;

use dashmap::DashMap;
use personhog_leader::cache::{CachedPerson, DirtyMark, PartitionedCache, PersonCacheKey};
use personhog_leader::service::drop_settled_death_documents;

use common::test_cached_person;

const PARTITION: u32 = 0;

fn death_doc(team_id: i64, person_id: i64, version: i64) -> CachedPerson {
    CachedPerson {
        id: person_id,
        team_id,
        version,
        is_deleted: true,
        properties: b"{}".to_vec(),
        ..test_cached_person()
    }
}

type LockMap = Arc<DashMap<PersonCacheKey, Arc<tokio::sync::Mutex<()>>>>;

fn setup(entry: Option<CachedPerson>) -> (Arc<PartitionedCache>, LockMap, PersonCacheKey) {
    let cache = Arc::new(PartitionedCache::new(1 << 20));
    cache.create_partition(PARTITION);
    let key = PersonCacheKey {
        team_id: 7,
        person_id: 42,
    };
    if let Some(entry) = entry {
        cache.put(PARTITION, key.clone(), entry);
    }
    (cache, Arc::new(DashMap::new()), key)
}

fn pruned(key: &PersonCacheKey, version: i64) -> Vec<(PersonCacheKey, DirtyMark)> {
    vec![(
        key.clone(),
        DirtyMark {
            version,
            offset: 9,
            partition: PARTITION,
            is_deleted: true,
        },
    )]
}

#[tokio::test]
async fn a_settled_death_document_is_dropped() {
    let (cache, locks, key) = setup(Some(death_doc(7, 42, 3)));

    drop_settled_death_documents(&cache, &locks, &pruned(&key, 3)).await;

    assert!(
        cache.peek(PARTITION, &key).is_none(),
        "the settled death document must be dropped so misses serve PG"
    );
}

#[tokio::test]
async fn a_newer_entry_survives_an_old_marks_settle() {
    // A newer death document (its own mark still standing) must not be
    // dropped by a superseded mark's prune.
    let (cache, locks, key) = setup(Some(death_doc(7, 42, 9)));

    drop_settled_death_documents(&cache, &locks, &pruned(&key, 3)).await;

    assert!(
        cache
            .peek(PARTITION, &key)
            .is_some_and(|entry| entry.version == 9),
        "an entry other than the pruned mark's must never be dropped"
    );
}

#[tokio::test]
async fn a_live_person_survives_its_marks_settle() {
    let live = CachedPerson {
        is_deleted: false,
        ..death_doc(7, 42, 3)
    };
    let (cache, locks, key) = setup(Some(live));

    drop_settled_death_documents(&cache, &locks, &pruned(&key, 3)).await;

    assert!(
        cache.peek(PARTITION, &key).is_some(),
        "settling a live person's mark drops nothing"
    );
}

#[tokio::test]
async fn the_drop_waits_for_the_per_key_lock() {
    // Holding the person's lock holds the drop; the entry surviving while
    // held is an invariant, not a timing bet.
    let (cache, locks, key) = setup(Some(death_doc(7, 42, 3)));

    let mutex = locks.entry(key.clone()).or_default().value().clone();
    let held = mutex.lock().await;

    let settling = tokio::spawn({
        let (cache, locks, key) = (Arc::clone(&cache), Arc::clone(&locks), key.clone());
        async move { drop_settled_death_documents(&cache, &locks, &pruned(&key, 3)).await }
    });
    tokio::task::yield_now().await;

    assert!(
        cache.peek(PARTITION, &key).is_some(),
        "no drop may land while the per-key lock is held"
    );

    drop(held);
    settling.await.expect("settle task");
    assert!(
        cache.peek(PARTITION, &key).is_none(),
        "the drop lands once the lock frees"
    );
}

#[tokio::test]
async fn an_install_landing_mid_settle_is_still_dropped() {
    // Absent at peek time: a recovery holds the lock and installs the
    // death document before releasing. The settle must wait, not skip.
    let (cache, locks, key) = setup(None);

    let mutex = locks.entry(key.clone()).or_default().value().clone();
    let held = mutex.lock().await;

    let settling = tokio::spawn({
        let (cache, locks, key) = (Arc::clone(&cache), Arc::clone(&locks), key.clone());
        async move { drop_settled_death_documents(&cache, &locks, &pruned(&key, 3)).await }
    });
    tokio::task::yield_now().await;

    cache.put(PARTITION, key.clone(), death_doc(7, 42, 3));
    drop(held);

    settling.await.expect("settle task");
    assert!(
        cache.peek(PARTITION, &key).is_none(),
        "a death document installed while the settle waited must be dropped"
    );
}
