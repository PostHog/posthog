//! Death-document residency maintenance: the prune tick and the settle
//! that drops a death document once the writer has applied its record.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use dashmap::DashMap;
use metrics::{counter, histogram};
use tokio::sync::Mutex;

use crate::cache::{CachedPerson, DirtyIndex, DirtyMark, PartitionedCache, PersonCacheKey};
use crate::warming::{fetch_writer_committed_offsets, ConsumerPool};

/// One prune pass: fetch committed offsets, prune applied marks of the
/// published partitions only (the settle cannot see a warming build),
/// and settle the death documents those marks covered. Returns marked
/// partitions and offsets for lag gauges; None if the fetch failed.
pub async fn prune_and_settle_tick(
    dirty_index: &DirtyIndex,
    cache: &PartitionedCache,
    locks: &DashMap<PersonCacheKey, Arc<Mutex<()>>>,
    offsets_pool: &ConsumerPool,
    topic: &str,
    offsets_timeout: Duration,
) -> Option<(Vec<u32>, HashMap<u32, i64>)> {
    let partitions = dirty_index.partitions_with_marks();
    if partitions.is_empty() {
        return Some((partitions, HashMap::new()));
    }
    let committed_offsets =
        match fetch_writer_committed_offsets(offsets_pool, topic, &partitions, offsets_timeout)
            .await
        {
            Ok(offsets) => offsets,
            Err(e) => {
                tracing::warn!(error = %e, "dirty-index prune offset fetch failed");
                return None;
            }
        };

    // Prune chunk by chunk, settling each chunk's death pairs before the
    // next, so a catch-up never materializes more than one chunk.
    let started = Instant::now();
    let mut removed_total = 0u64;
    for (partition, committed) in &committed_offsets {
        if !cache.is_published(*partition) {
            continue;
        }
        loop {
            let (pruned, exhausted) = dirty_index.prune_chunk(*partition, *committed);
            removed_total += pruned.removed as u64;
            if !pruned.death_marks.is_empty() {
                drop_settled_death_documents(cache, locks, &pruned.death_marks).await;
            }
            if exhausted {
                break;
            }
        }
    }
    if removed_total > 0 {
        counter!("personhog_leader_dirty_index_pruned_total").increment(removed_total);
    }
    // A long tick means the settle parked on per-key locks, not an idle
    // pass.
    histogram!("personhog_leader_prune_tick_duration_ms")
        .record(started.elapsed().as_secs_f64() * 1000.0);
    Some((partitions, committed_offsets))
}

/// Drop death documents whose marks the writer settled: past the mark,
/// PG answers for the person — tombstoned or revived. A revival cannot
/// precede the applied tombstone (stub creation revives only
/// `is_deleted = true` rows), so the miss after the drop serves truth.
pub async fn drop_settled_death_documents(
    cache: &PartitionedCache,
    locks: &DashMap<PersonCacheKey, Arc<Mutex<()>>>,
    pruned: &[(PersonCacheKey, DirtyMark)],
) {
    for (key, mark) in pruned {
        // Skip lock-free only on a live or newer entry. An absent entry
        // must take the lock: a recovery holding it may be about to
        // install this very death document.
        let settled = |entry: &Arc<CachedPerson>| entry.is_deleted && entry.version == mark.version;
        if cache
            .peek(mark.partition, key)
            .as_ref()
            .is_some_and(|entry| !settled(entry))
        {
            continue;
        }
        let mutex = locks.entry(key.clone()).or_default().value().clone();
        let _guard = mutex.lock().await;
        // Re-proved under the lock so a concurrent commit's newer entry
        // is never dropped.
        if cache
            .peek(mark.partition, key)
            .as_ref()
            .is_some_and(settled)
        {
            cache.remove(mark.partition, key);
            counter!("personhog_leader_death_documents_settled_total").increment(1);
        }
    }
}
