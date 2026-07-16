use std::collections::{HashMap, VecDeque};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use dashmap::mapref::entry::Entry;
use dashmap::DashMap;

use super::PersonCacheKey;

/// A mark for a person whose latest acked state may not yet be applied to
/// Postgres by the writer.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DirtyMark {
    /// Version of the latest acked changelog record for this person.
    /// Recovery cross-checks it against the record it fetches: the two
    /// derive from the same state, so a mismatch means the acked state and
    /// the produced record diverged.
    pub version: i64,
    /// Changelog offset of that record. Because records are full state and
    /// the topic is compacted by person key, this single record is always
    /// sufficient to reconstruct the person — and compaction never removes
    /// the latest record for a key. Only the topic's `delete` retention
    /// bounds it, which matters solely if a mark outlives the retention
    /// window (a writer outage of days); even then recovery fails loudly
    /// with a retryable error rather than serving stale state.
    pub offset: i64,
    /// The person's routing partition, denormalized so pruning can work
    /// per partition without rehashing keys.
    pub partition: u32,
}

/// A partition's reclaim queue: `(offset, key)` entries in rough offset
/// order, popped from the head as the writer's committed offset passes them.
type ReclaimQueue = Arc<Mutex<VecDeque<(i64, PersonCacheKey)>>>;

/// Maximum queue pops per prune lock hold (see `prune_partition`).
const PRUNE_CHUNK: usize = 4_096;

/// Containers below this capacity are never shrunk — the retained memory
/// is a few hundred KB at most, not worth the churn.
const SHRINK_CAPACITY_FLOOR: usize = 4 * PRUNE_CHUNK;

/// Index of persons whose latest acked state is (or may be) newer than what
/// the writer has applied to Postgres.
///
/// The cache evicts freely; this index is what keeps eviction safe. On a
/// cache miss the leader consults it before trusting the PG fallback: a
/// marked person is recovered from the changelog record at the marked
/// offset, an unmarked person's PG row is known current. Entries cost
/// ~100 bytes with map overhead, so even an hours-long writer outage is
/// far cheaper to track here than to ride out by pinning person state.
///
/// Marks are added under the per-key lock after every acked produce, and
/// removed by a periodic prune once the writer's committed offset passes
/// them (committed offset semantics: the record at `committed - 1` is the
/// last one applied, so a mark is prunable when `offset < committed`).
///
/// The prune predicate is an offset threshold and marks arrive in roughly
/// offset order per partition, so reclaim is a queue pop, not a map scan:
/// alongside the map, each partition keeps an offset-ordered reclaim queue
/// of `(offset, key)` entries, and a prune pops from the head only while
/// entries are below the committed offset. A tick therefore costs work
/// proportional to the marks actually reclaimed — never the index size —
/// which is what lets the prune loop run every second.
///
/// The queue is a hint; the map is the truth. Every marked key has exactly
/// one live queue entry, carrying some offset at or below its map offset:
/// `mark` enqueues only brand-new keys, so a re-marked key's queue entry
/// goes stale, and when the prune pops it and finds the map ahead of the
/// committed offset it re-enqueues the entry at the map's offset instead
/// of removing the mark. Task scheduling can also interleave near-
/// simultaneous marks slightly out of offset order; the prune stops at the
/// first unapplied head, so an inversion only delays the entries behind it
/// until a later tick.
///
/// The index is soft-bounded by `max_entries`: under a sustained writer
/// outage it would otherwise grow one mark per unique person written —
/// gigabytes over hours at production churn, and an OOM restart replays
/// the same backlog through warming. Write admission (`can_admit`) is
/// checked before producing, so the bound sheds new write volume instead
/// of ever refusing to record a fact: `mark` itself never fails, because
/// warming must be able to record marks for records that are already
/// durable regardless of the bound.
pub struct DirtyIndex {
    map: DashMap<PersonCacheKey, DirtyMark>,
    /// Per-partition reclaim queues (see the struct docs). A prune pass
    /// holds a queue's lock for at most `PRUNE_CHUNK` pops and re-fetches
    /// the queue from this map between chunks, so `clear_partition` —
    /// which detaches the queue and then takes the same lock — waits out
    /// at most one chunk before draining, and a paused pass finds the
    /// queue gone instead of racing the drain. Entries popped before the
    /// detach have already had their map marks removed; everything else
    /// is still in the queue for the drain — no entry escapes a release.
    queues: DashMap<u32, ReclaimQueue>,
    /// Highest offset ever marked per partition since its last clear.
    /// Map offsets only grow and pruning removes low offsets first, so
    /// while any mark lives this equals the largest live mark — an O(1)
    /// read for the writer-lag gauge.
    max_marked: DashMap<u32, i64>,
    /// Entry count maintained alongside the map: `DashMap::len()` takes a
    /// read lock on every shard, which is too expensive for the admission
    /// check on the write hot path. Kept in step by `mark` (insert only)
    /// and the removal methods; approximate under concurrent mutation,
    /// which a soft bound tolerates.
    size: AtomicUsize,
    max_entries: usize,
}

impl DirtyIndex {
    pub fn new(max_entries: usize) -> Self {
        Self {
            map: DashMap::new(),
            queues: DashMap::new(),
            max_marked: DashMap::new(),
            size: AtomicUsize::new(0),
            max_entries,
        }
    }

    /// Whether a write for `key` may be admitted: either the index has
    /// room to grow, or the key is already marked (updating a mark does
    /// not grow the index). Checked before the produce — a durable but
    /// unmarked write would silently reopen the stale-fallback hole.
    /// Concurrent in-flight writes can overshoot the bound by the request
    /// concurrency; it is a memory bound, not an exact count.
    pub fn can_admit(&self, key: &PersonCacheKey) -> bool {
        self.size.load(Ordering::Relaxed) < self.max_entries || self.map.contains_key(key)
    }

    /// Record the latest acked offset for a person. Writers hold the
    /// per-key lock, so marks normally arrive in offset order; the guard
    /// against regressing keeps a concurrent warm-seeding pass from
    /// clobbering a newer mark with an older replayed one. The map is
    /// updated before the queue so a concurrent prune popping the entry
    /// always sees the mark.
    pub fn mark(&self, key: PersonCacheKey, mark: DirtyMark) {
        let partition = mark.partition;
        let offset = mark.offset;
        let is_new = match self.map.entry(key.clone()) {
            Entry::Occupied(mut entry) => {
                if mark.offset > entry.get().offset {
                    *entry.get_mut() = mark;
                }
                false
            }
            Entry::Vacant(entry) => {
                entry.insert(mark);
                self.size.fetch_add(1, Ordering::Relaxed);
                true
            }
        };
        self.max_marked
            .entry(partition)
            .and_modify(|max| *max = (*max).max(offset))
            .or_insert(offset);
        if is_new {
            let queue = Arc::clone(
                self.queues
                    .entry(partition)
                    .or_insert_with(|| Arc::new(Mutex::new(VecDeque::new())))
                    .value(),
            );
            queue
                .lock()
                .expect("dirty index queue lock poisoned")
                .push_back((offset, key));
        }
    }

    pub fn get(&self, key: &PersonCacheKey) -> Option<DirtyMark> {
        self.map.get(key).map(|entry| *entry.value())
    }

    /// Drop every mark the writer has applied, across all partitions: a
    /// mark is applied once its partition's committed offset (absent = no
    /// commit yet) has moved past it. Returns how many were pruned.
    pub fn prune_applied(&self, committed: &HashMap<u32, i64>) -> usize {
        let removed = committed
            .iter()
            .map(|(partition, committed)| self.prune_partition(*partition, *committed))
            .sum();
        if removed > 0 {
            self.maybe_shrink_map();
        }
        removed
    }

    /// Return the map's spare capacity to the allocator. Removal never
    /// shrinks it, so a catch-up after a deep outage would otherwise pin
    /// the backlog's worst-case footprint forever; capacity only becomes
    /// reclaimable through removals, so callers invoke this after removing
    /// something. The threshold makes it a no-op both during steady lag
    /// (the map is genuinely full) and right after a shrink (capacity
    /// tracks the live count again), so a draining backlog triggers at
    /// most a few shrinks, each cheap because little survives to rehash.
    fn maybe_shrink_map(&self) {
        let capacity = self.map.capacity();
        if capacity > SHRINK_CAPACITY_FLOOR && self.len() * 4 < capacity {
            self.map.shrink_to_fit();
        }
    }

    /// Drop marks on `partition` that the writer has applied (offset below
    /// its committed offset). Pops the reclaim queue only while its head
    /// is applied, so the cost is proportional to the marks reclaimed.
    /// The pass releases the queue lock every `PRUNE_CHUNK` pops: a
    /// catch-up after a long writer outage reclaims millions of marks in
    /// one call, and an unbroken hold would stall every new-key `mark` —
    /// the write hot path — for the whole pass. Between chunks the queue
    /// is re-fetched, so a concurrent `clear_partition` (which detaches
    /// it) ends the pass instead of racing the drain. Returns how many
    /// were pruned.
    pub fn prune_partition(&self, partition: u32, committed: i64) -> usize {
        let mut removed = 0;
        'pass: loop {
            let Some(queue) = self
                .queues
                .get(&partition)
                .map(|entry| Arc::clone(entry.value()))
            else {
                break;
            };
            let mut queue = queue.lock().expect("dirty index queue lock poisoned");
            let mut budget = PRUNE_CHUNK;
            while budget > 0 {
                let Some(&(offset, _)) = queue.front() else {
                    break 'pass;
                };
                if offset >= committed {
                    break 'pass;
                }
                budget -= 1;
                let (_, key) = queue.pop_front().expect("front was just observed");
                // The removal re-checks the map's offset under the shard
                // lock: between the pop and here the key may have been
                // re-marked, and removing the newer mark would silently
                // reopen the stale-fallback hole.
                if self
                    .map
                    .remove_if(&key, |_, mark| mark.offset < committed)
                    .is_some()
                {
                    removed += 1;
                } else if let Some(mark) = self.map.get(&key) {
                    // Superseded: the live mark is ahead of the committed
                    // offset, and the entry just popped was this key's only
                    // queue presence (`mark` enqueues keys once). Dropping
                    // it would leave the mark unreclaimable — pops are the
                    // only reclaim path — so re-enqueue at the map's
                    // offset. The tail lands past the committed threshold,
                    // so the head check terminates the pass before
                    // re-processing it; the resulting disorder only delays
                    // that key's reclaim, since removal is always re-proved
                    // against the map.
                    queue.push_back((mark.offset, key.clone()));
                }
            }
        }
        self.size.fetch_sub(removed, Ordering::Relaxed);
        // A queue never shrinks on pop, so after a catch-up it would pin
        // its backlog-peak buffer until the partition is released.
        if removed > 0 {
            if let Some(queue) = self
                .queues
                .get(&partition)
                .map(|entry| Arc::clone(entry.value()))
            {
                let mut queue = queue.lock().expect("dirty index queue lock poisoned");
                if queue.capacity() > SHRINK_CAPACITY_FLOOR && queue.len() * 4 < queue.capacity() {
                    queue.shrink_to_fit();
                }
            }
        }
        removed
    }

    /// Drop every mark on `partition` — used when the partition is released
    /// to another owner, whose warming rebuilds its own marks.
    pub fn clear_partition(&self, partition: u32) -> usize {
        let Some((_, queue)) = self.queues.remove(&partition) else {
            return 0;
        };
        self.max_marked.remove(&partition);
        let mut queue = queue.lock().expect("dirty index queue lock poisoned");
        let mut removed = 0;
        while let Some((_, key)) = queue.pop_front() {
            if self.map.remove(&key).is_some() {
                removed += 1;
            }
        }
        self.size.fetch_sub(removed, Ordering::Relaxed);
        // Releases bypass prune_applied, so a released backlog's map
        // capacity would otherwise stay pinned until some future prune.
        if removed > 0 {
            self.maybe_shrink_map();
        }
        removed
    }

    /// Partitions that currently hold marks — the prune loop's targeting
    /// set for the writer committed-offset fetch.
    pub fn partitions_with_marks(&self) -> Vec<u32> {
        self.queues
            .iter()
            .filter(|entry| {
                !entry
                    .value()
                    .lock()
                    .expect("dirty index queue lock poisoned")
                    .is_empty()
            })
            .map(|entry| *entry.key())
            .collect()
    }

    /// Highest live marked offset for a partition, if any — feeds the
    /// writer-lag gauge.
    pub fn max_offset(&self, partition: u32) -> Option<i64> {
        let has_marks = self.queues.get(&partition).is_some_and(|queue| {
            !queue
                .value()
                .lock()
                .expect("dirty index queue lock poisoned")
                .is_empty()
        });
        if !has_marks {
            return None;
        }
        self.max_marked.get(&partition).map(|max| *max.value())
    }

    pub fn len(&self) -> usize {
        self.size.load(Ordering::Relaxed)
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn key(person_id: i64) -> PersonCacheKey {
        PersonCacheKey {
            team_id: 1,
            person_id,
        }
    }

    fn mark(offset: i64, partition: u32) -> DirtyMark {
        DirtyMark {
            version: offset,
            offset,
            partition,
        }
    }

    #[test]
    fn admission_is_denied_at_capacity_except_for_marked_keys() {
        let index = DirtyIndex::new(1);
        assert!(index.can_admit(&key(1)));
        index.mark(key(1), mark(1, 0));

        // At capacity: new keys are denied, the marked key is not.
        assert!(!index.can_admit(&key(2)));
        assert!(index.can_admit(&key(1)));

        // Marks themselves are never refused (warming records facts about
        // already-durable records regardless of the bound).
        index.mark(key(2), mark(2, 0));
        assert_eq!(index.len(), 2);

        // Pruning frees admission again.
        index.prune_partition(0, 100);
        assert!(index.can_admit(&key(3)));
    }

    #[test]
    fn mark_keeps_the_newest_offset() {
        let index = DirtyIndex::new(1_000);
        index.mark(key(1), mark(5, 0));
        index.mark(key(1), mark(3, 0));
        assert_eq!(index.get(&key(1)).unwrap().offset, 5);

        index.mark(key(1), mark(7, 0));
        assert_eq!(index.get(&key(1)).unwrap().offset, 7);
    }

    #[test]
    fn prune_removes_applied_marks_and_keeps_the_boundary() {
        let index = DirtyIndex::new(1_000);
        index.mark(key(1), mark(4, 0));
        index.mark(key(2), mark(5, 0));
        index.mark(key(3), mark(6, 0));

        // Committed offset 5 means the record at 4 is applied; the record
        // at 5 is not yet.
        let pruned = index.prune_partition(0, 5);
        assert_eq!(pruned, 1);
        assert!(index.get(&key(1)).is_none());
        assert!(index.get(&key(2)).is_some());
        assert!(index.get(&key(3)).is_some());
    }

    #[test]
    fn remarked_key_survives_prune_until_its_newest_offset_is_applied() {
        let index = DirtyIndex::new(1_000);
        index.mark(key(1), mark(1, 0));
        index.mark(key(1), mark(5, 0));

        // The stale queue entry at offset 1 is popped, but the live mark
        // is ahead of the committed offset and must survive.
        assert_eq!(index.prune_partition(0, 3), 0);
        assert_eq!(index.get(&key(1)).unwrap().offset, 5);

        // The re-enqueued entry keeps the key reclaimable once the writer
        // catches up — a dropped entry would leak the mark forever.
        assert_eq!(index.prune_partition(0, 6), 1);
        assert!(index.get(&key(1)).is_none());
        assert_eq!(index.len(), 0);
    }

    #[test]
    fn prune_stops_at_the_first_unapplied_head() {
        let index = DirtyIndex::new(1_000);
        // Near-simultaneous marks can enqueue slightly out of offset
        // order; the prune stops at the first unapplied head, delaying
        // (not losing) the applied entry behind it.
        index.mark(key(1), mark(10, 0));
        index.mark(key(2), mark(9, 0));

        assert_eq!(index.prune_partition(0, 10), 0);
        assert_eq!(index.prune_partition(0, 11), 2);
        assert!(index.is_empty());
    }

    #[test]
    fn prune_reclaims_a_backlog_larger_than_one_chunk() {
        let total = PRUNE_CHUNK as i64 * 2 + 100;
        let index = DirtyIndex::new(usize::MAX);
        for offset in 0..total {
            index.mark(key(offset), mark(offset, 0));
        }

        // A catch-up reclaims across chunk boundaries in a single call.
        assert_eq!(index.prune_partition(0, total), total as usize);
        assert!(index.is_empty());
    }

    #[test]
    fn prune_and_clear_are_scoped_to_the_partition() {
        let index = DirtyIndex::new(1_000);
        index.mark(key(1), mark(1, 0));
        index.mark(key(2), mark(1, 7));

        assert_eq!(index.prune_partition(0, 100), 1);
        assert!(index.get(&key(2)).is_some());

        index.mark(key(3), mark(2, 7));
        assert_eq!(index.clear_partition(7), 2);
        assert!(index.is_empty());
    }

    #[test]
    fn partition_targeting_and_max_offset_track_live_marks() {
        let index = DirtyIndex::new(1_000);
        index.mark(key(1), mark(4, 0));
        index.mark(key(2), mark(9, 0));
        index.mark(key(3), mark(2, 7));

        let mut partitions = index.partitions_with_marks();
        partitions.sort_unstable();
        assert_eq!(partitions, vec![0, 7]);
        assert_eq!(index.max_offset(0), Some(9));
        assert_eq!(index.max_offset(7), Some(2));
        assert_eq!(index.max_offset(3), None);

        index.prune_partition(0, 100);
        assert_eq!(index.max_offset(0), None);
        assert_eq!(index.partitions_with_marks(), vec![7]);
    }

    #[test]
    fn size_tracks_inserts_updates_and_removals() {
        let index = DirtyIndex::new(1_000);
        index.mark(key(1), mark(1, 0));
        index.mark(key(1), mark(2, 0)); // update, not growth
        index.mark(key(2), mark(3, 0));
        assert_eq!(index.len(), 2);

        index.prune_partition(0, 3);
        assert_eq!(index.len(), 1);

        index.clear_partition(0);
        assert_eq!(index.len(), 0);
        assert!(index.is_empty());
    }
}
