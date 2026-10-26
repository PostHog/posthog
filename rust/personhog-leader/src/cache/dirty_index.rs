use std::collections::VecDeque;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use dashmap::mapref::entry::Entry;
use dashmap::DashMap;

use super::PersonCacheKey;

/// The changelog partition a mark's record lives in.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct Stream {
    pub topic: Arc<str>,
    pub partition: u32,
}

/// A mark for a person whose latest acked state may not yet be applied to
/// Postgres by the writer.
#[derive(Debug, Clone, PartialEq, Eq)]
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
    pub stream: Stream,
    /// Whether the marked record is a death document. The prune returns
    /// only these pairs, so the settle never touches live persons' keys.
    pub is_deleted: bool,
}

/// What a prune pass reclaimed: the count drives shrinking and metrics;
/// the death pairs go to the settle.
pub struct PrunedMarks {
    pub removed: usize,
    pub death_marks: Vec<(PersonCacheKey, DirtyMark)>,
}

/// `(offset, key)` entries in rough offset order, popped as the writer's commit passes them.
type ReclaimQueue = Arc<Mutex<VecDeque<(i64, PersonCacheKey)>>>;

/// One reclaim queue per cache partition and stream feeding it.
type QueueKey = (u32, Stream);

/// Maximum queue pops per prune lock hold (see `prune_chunk`).
pub const PRUNE_CHUNK: usize = 4_096;

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
/// The map is the truth and the queues are a hint. Each marked key has a queue
/// entry under its mark's home (partition and stream), at or below its offset.
/// The prune re-queues an entry whose mark moved ahead, and drops one whose mark
/// moved home. Out-of-order marks only delay the entries behind them.
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
    queues: DashMap<QueueKey, ReclaimQueue>,
    /// Highest offset marked per queue since its last clear, for the writer-lag gauge.
    max_marked: DashMap<QueueKey, i64>,
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

    /// Record the latest acked offset for a person. A replayed mark never moves one
    /// backwards within a home; a mark that moves home replaces the old one. The map
    /// updates before the queue, so a concurrent prune always sees the mark.
    pub fn mark(&self, key: PersonCacheKey, mark: DirtyMark) {
        let queue_key = (mark.partition, mark.stream.clone());
        let offset = mark.offset;
        let enqueue = match self.map.entry(key.clone()) {
            Entry::Occupied(mut entry) => {
                // A newer generation's record outranks any offset of an older one.
                let current = entry.get();
                let moved = mark.partition != current.partition || mark.stream != current.stream;
                if moved || mark.offset > current.offset {
                    *entry.get_mut() = mark;
                }
                moved
            }
            Entry::Vacant(entry) => {
                entry.insert(mark);
                self.size.fetch_add(1, Ordering::Relaxed);
                true
            }
        };
        self.max_marked
            .entry(queue_key.clone())
            .and_modify(|max| *max = (*max).max(offset))
            .or_insert(offset);
        if enqueue {
            let queue = Arc::clone(
                self.queues
                    .entry(queue_key)
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
        self.map.get(key).map(|entry| entry.value().clone())
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

    /// One bounded prune slice: hold the queue lock for at most
    /// `PRUNE_CHUNK` pops, remove the applied marks (offset below the
    /// committed offset), and return the death pairs for the caller to
    /// settle before the next slice — that keeps a catch-up's memory and
    /// lock exposure flat, and lets `mark` (the write hot path) breathe
    /// between slices. Exhausted means the head is unapplied, the queue
    /// is empty, or it was detached by a concurrent `clear_partition` —
    /// the re-fetch is what lets a release end an in-flight pass instead
    /// of racing its drain.
    pub fn prune_chunk(
        &self,
        partition: u32,
        stream: &Stream,
        committed: i64,
    ) -> (PrunedMarks, bool) {
        let mut pruned = PrunedMarks {
            removed: 0,
            death_marks: Vec::new(),
        };
        let Some(queue) = self
            .queues
            .get(&(partition, stream.clone()))
            .map(|entry| Arc::clone(entry.value()))
        else {
            return (pruned, true);
        };
        let mut queue = queue.lock().expect("dirty index queue lock poisoned");
        let mut removed = 0;
        let mut budget = PRUNE_CHUNK;
        let mut exhausted = false;
        while budget > 0 {
            let Some(&(offset, _)) = queue.front() else {
                exhausted = true;
                break;
            };
            if offset >= committed {
                exhausted = true;
                break;
            }
            budget -= 1;
            let (_, key) = queue.pop_front().expect("front was just observed");
            // The removal re-checks the map's home and offset under the
            // shard lock: between the pop and here the key may have been
            // re-marked, and removing the newer mark would silently
            // reopen the stale-fallback hole.
            if let Some(entry) = self.map.remove_if(&key, |_, mark| {
                mark.partition == partition && mark.stream == *stream && mark.offset < committed
            }) {
                removed += 1;
                pruned.removed += 1;
                if entry.1.is_deleted {
                    pruned.death_marks.push(entry);
                }
            } else if let Some(mark) = self.map.get(&key) {
                // The live mark is newer: re-queue it at its offset. An entry whose mark
                // moved home is stale here and dropped.
                if mark.partition == partition && mark.stream == *stream {
                    queue.push_back((mark.offset, key.clone()));
                }
            }
        }
        self.size.fetch_sub(removed, Ordering::Relaxed);
        if exhausted {
            // A queue never shrinks on pop; reclaim after a catch-up.
            if queue.capacity() > SHRINK_CAPACITY_FLOOR && queue.len() * 4 < queue.capacity() {
                queue.shrink_to_fit();
            }
        }
        drop(queue);
        if exhausted {
            self.maybe_shrink_map();
        }
        (pruned, exhausted)
    }

    /// Drop every mark homed on `partition`, across every stream feeding it.
    /// A queued key whose live mark moved to another home is left to that home.
    pub fn clear_partition(&self, partition: u32) -> usize {
        let keys: Vec<QueueKey> = self
            .queues
            .iter()
            .filter(|entry| entry.key().0 == partition)
            .map(|entry| entry.key().clone())
            .collect();
        let mut removed = 0;
        for queue_key in keys {
            let Some((_, queue)) = self.queues.remove(&queue_key) else {
                continue;
            };
            self.max_marked.remove(&queue_key);
            let mut queue = queue.lock().expect("dirty index queue lock poisoned");
            while let Some((_, key)) = queue.pop_front() {
                if self
                    .map
                    .remove_if(&key, |_, mark| mark.partition == partition)
                    .is_some()
                {
                    removed += 1;
                }
            }
        }
        self.size.fetch_sub(removed, Ordering::Relaxed);
        // Releases bypass the prune, so a released backlog's map
        // capacity would otherwise stay pinned until some future prune.
        if removed > 0 {
            self.maybe_shrink_map();
        }
        removed
    }

    /// Cache partitions and the streams on which they hold marks.
    pub fn streams_with_marks(&self) -> Vec<(u32, Stream)> {
        self.queues
            .iter()
            .filter(|entry| {
                !entry
                    .value()
                    .lock()
                    .expect("dirty index queue lock poisoned")
                    .is_empty()
            })
            .map(|entry| entry.key().clone())
            .collect()
    }

    /// Highest live marked offset on a stream, for the writer-lag gauge.
    pub fn max_offset(&self, partition: u32, stream: &Stream) -> Option<i64> {
        let queue_key = (partition, stream.clone());
        let has_marks = self.queues.get(&queue_key).is_some_and(|queue| {
            !queue
                .value()
                .lock()
                .expect("dirty index queue lock poisoned")
                .is_empty()
        });
        if !has_marks {
            return None;
        }
        self.max_marked.get(&queue_key).map(|max| *max.value())
    }

    pub fn len(&self) -> usize {
        self.size.load(Ordering::Relaxed)
    }

    /// The soft entry bound — exported as a gauge so fullness
    /// (`len / max_entries`) is alertable before writes start shedding.
    pub fn max_entries(&self) -> usize {
        self.max_entries
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

    fn stream(partition: u32) -> Stream {
        Stream {
            topic: Arc::from("personhog_updates"),
            partition,
        }
    }

    fn mark(offset: i64, partition: u32) -> DirtyMark {
        DirtyMark {
            version: offset,
            offset,
            partition,
            stream: stream(partition),
            is_deleted: false,
        }
    }

    fn death_mark(offset: i64, partition: u32) -> DirtyMark {
        DirtyMark {
            is_deleted: true,
            ..mark(offset, partition)
        }
    }

    fn prune_all(index: &DirtyIndex, partition: u32, committed: i64) -> PrunedMarks {
        let mut total = PrunedMarks {
            removed: 0,
            death_marks: Vec::new(),
        };
        loop {
            let (pruned, exhausted) = index.prune_chunk(partition, &stream(partition), committed);
            total.removed += pruned.removed;
            total.death_marks.extend(pruned.death_marks);
            if exhausted {
                return total;
            }
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
        prune_all(&index, 0, 100);
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
        index.mark(key(1), death_mark(4, 0));
        index.mark(key(2), mark(5, 0));
        index.mark(key(3), mark(6, 0));

        // Committed offset 5 means the record at 4 is applied; the record
        // at 5 is not yet.
        let pruned = prune_all(&index, 0, 5);
        assert_eq!(pruned.removed, 1);
        // The death pair carries the removed key and its mark, so the
        // settle acts on exactly what was pruned.
        assert_eq!(pruned.death_marks.len(), 1);
        assert_eq!(pruned.death_marks[0].0, key(1));
        assert_eq!(pruned.death_marks[0].1.offset, 4);
        assert!(index.get(&key(1)).is_none());
        assert!(index.get(&key(2)).is_some());
        assert!(index.get(&key(3)).is_some());

        // A pruned live mark counts but yields no death pair.
        let pruned = prune_all(&index, 0, 6);
        assert_eq!(pruned.removed, 1);
        assert!(pruned.death_marks.is_empty());
    }

    #[test]
    fn remarked_key_survives_prune_until_its_newest_offset_is_applied() {
        let index = DirtyIndex::new(1_000);
        index.mark(key(1), mark(1, 0));
        index.mark(key(1), mark(5, 0));

        // The stale queue entry at offset 1 is popped, but the live mark
        // is ahead of the committed offset and must survive.
        assert_eq!(prune_all(&index, 0, 3).removed, 0);
        assert_eq!(index.get(&key(1)).unwrap().offset, 5);

        // The re-enqueued entry keeps the key reclaimable once the writer
        // catches up — a dropped entry would leak the mark forever.
        assert_eq!(prune_all(&index, 0, 6).removed, 1);
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

        assert_eq!(prune_all(&index, 0, 10).removed, 0);
        assert_eq!(prune_all(&index, 0, 11).removed, 2);
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
        assert_eq!(prune_all(&index, 0, total).removed, total as usize);
        assert!(index.is_empty());
    }

    #[test]
    fn clear_between_chunks_ends_the_pass_without_leaking_marks() {
        let total = PRUNE_CHUNK as i64 + 500;
        let index = DirtyIndex::new(usize::MAX);
        for offset in 0..total {
            index.mark(key(offset), mark(offset, 0));
        }

        // The first chunk of an in-flight pass reclaims its bounded slice
        // and reports the pass unfinished.
        let (removed, exhausted) = index.prune_chunk(0, &stream(0), total);
        assert_eq!(removed.removed, PRUNE_CHUNK);
        assert!(!exhausted);

        // A release lands between chunks: it detaches the queue and
        // drains every remaining mark — nothing escapes.
        assert_eq!(index.clear_partition(0), 500);
        assert_eq!(index.len(), 0);

        // The paused pass re-fetches, observes the detachment, and ends
        // instead of racing the drain it would otherwise double-count.
        let (removed, exhausted) = index.prune_chunk(0, &stream(0), total);
        assert_eq!(removed.removed, 0);
        assert!(exhausted);

        // Ownership re-acquired after the release: fresh marks live in a
        // fresh queue that a new pass reclaims normally.
        index.mark(key(1), mark(total + 1, 0));
        assert_eq!(prune_all(&index, 0, total + 2).removed, 1);
        assert!(index.is_empty());
    }

    #[test]
    fn a_death_backlog_prunes_in_bounded_chunks() {
        let total = PRUNE_CHUNK as i64 + 100;
        let index = DirtyIndex::new(usize::MAX);
        for offset in 0..total {
            index.mark(key(offset), death_mark(offset, 0));
        }

        let (first, exhausted) = index.prune_chunk(0, &stream(0), total);
        assert_eq!(first.death_marks.len(), PRUNE_CHUNK);
        assert!(!exhausted);

        let (rest, exhausted) = index.prune_chunk(0, &stream(0), total);
        assert_eq!(rest.death_marks.len(), 100);
        assert!(exhausted);
        assert!(index.is_empty());
    }

    #[test]
    fn prune_and_clear_are_scoped_to_the_partition() {
        let index = DirtyIndex::new(1_000);
        index.mark(key(1), mark(1, 0));
        index.mark(key(2), mark(1, 7));

        assert_eq!(prune_all(&index, 0, 100).removed, 1);
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

        let mut partitions: Vec<u32> = index
            .streams_with_marks()
            .into_iter()
            .map(|(p, _)| p)
            .collect();
        partitions.sort_unstable();
        assert_eq!(partitions, vec![0, 7]);
        assert_eq!(index.max_offset(0, &stream(0)), Some(9));
        assert_eq!(index.max_offset(7, &stream(7)), Some(2));
        assert_eq!(index.max_offset(3, &stream(3)), None);

        prune_all(&index, 0, 100);
        assert_eq!(index.max_offset(0, &stream(0)), None);
        let left: Vec<u32> = index
            .streams_with_marks()
            .into_iter()
            .map(|(p, _)| p)
            .collect();
        assert_eq!(left, vec![7]);
    }

    /// Two streams under one partition prune apart and clear together.
    #[test]
    fn streams_under_one_partition_prune_apart_and_clear_together() {
        let index = DirtyIndex::new(1_000);
        let old = Stream {
            topic: Arc::from("personhog_updates_old"),
            partition: 1,
        };
        index.mark(key(1), mark(4, 65));
        index.mark(
            key(2),
            DirtyMark {
                stream: old.clone(),
                ..mark(900, 65)
            },
        );

        let (pruned, _) = index.prune_chunk(65, &stream(65), 100);
        assert_eq!(pruned.removed, 1);
        assert!(index.get(&key(1)).is_none());
        assert!(index.get(&key(2)).is_some());
        assert_eq!(index.max_offset(65, &old), Some(900));

        index.mark(key(2), mark(5, 65));
        assert_eq!(index.get(&key(2)).unwrap().stream, stream(65));
        assert_eq!(index.clear_partition(65), 1);
        assert!(index.streams_with_marks().is_empty());
    }

    #[test]
    fn pruning_a_stream_terminates_when_a_key_was_re_marked_on_a_newer_stream() {
        let old = Stream {
            topic: Arc::from("personhog_updates_old"),
            partition: 0,
        };
        for committed in [1_457, i64::MAX] {
            let index = DirtyIndex::new(1_000);
            index.mark(
                key(1),
                DirtyMark {
                    stream: old.clone(),
                    ..mark(900, 0)
                },
            );
            index.mark(key(1), mark(12, 0));
            let mut chunks = 0;
            loop {
                let (_, exhausted) = index.prune_chunk(0, &old, committed);
                chunks += 1;
                if exhausted {
                    break;
                }
                assert!(
                    chunks < 64,
                    "the old stream never exhausts at committed {committed}"
                );
            }
            assert_eq!(index.get(&key(1)).unwrap().stream, stream(0));
            // Refiled under its own stream, the mark is reclaimable there.
            assert_eq!(index.max_offset(0, &old), None);
            assert_eq!(prune_all(&index, 0, 13).removed, 1);
            assert!(index.get(&key(1)).is_none());
        }
    }

    #[test]
    fn a_key_that_moved_home_survives_the_old_homes_clear_and_prune() {
        // Shrink 8 -> 4: old partition 5 and new partition 1 share keys.
        let old5 = Stream {
            topic: Arc::from("personhog_updates_old"),
            partition: 5,
        };
        let index = DirtyIndex::new(1_000);
        index.mark(
            key(1),
            DirtyMark {
                partition: 5,
                stream: old5.clone(),
                ..mark(900, 5)
            },
        );
        // The new home's warm replays the same record: equal offset, new partition.
        index.mark(
            key(1),
            DirtyMark {
                partition: 1,
                stream: old5.clone(),
                ..mark(900, 1)
            },
        );
        assert_eq!(index.get(&key(1)).unwrap().partition, 1);

        // Old-5's last prune and its release both leave the moved mark alone.
        let (pruned, exhausted) = index.prune_chunk(5, &old5, 1_457);
        assert_eq!((pruned.removed, exhausted), (0, true));
        assert_eq!(index.clear_partition(5), 0);
        assert_eq!(index.get(&key(1)).unwrap().partition, 1);

        // And the new home reclaims it once the writer applies the old record.
        let (pruned, _) = index.prune_chunk(1, &old5, 901);
        assert_eq!(pruned.removed, 1);
        assert!(index.get(&key(1)).is_none());

        // The release may also come first, before any prune touched old-5.
        let index = DirtyIndex::new(1_000);
        for partition in [5, 1] {
            index.mark(
                key(1),
                DirtyMark {
                    partition,
                    stream: old5.clone(),
                    ..mark(900, partition)
                },
            );
        }
        assert_eq!(index.clear_partition(5), 0);
        assert_eq!(index.get(&key(1)).unwrap().partition, 1);
    }

    #[test]
    fn size_tracks_inserts_updates_and_removals() {
        let index = DirtyIndex::new(1_000);
        index.mark(key(1), mark(1, 0));
        index.mark(key(1), mark(2, 0)); // update, not growth
        index.mark(key(2), mark(3, 0));
        assert_eq!(index.len(), 2);

        prune_all(&index, 0, 3);
        assert_eq!(index.len(), 1);

        index.clear_partition(0);
        assert_eq!(index.len(), 0);
        assert!(index.is_empty());
    }
}
