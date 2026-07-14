use std::collections::HashMap;
use std::sync::atomic::{AtomicUsize, Ordering};

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
    /// Entry count maintained alongside the map: `DashMap::len()` takes a
    /// read lock on every shard, which is too expensive for the admission
    /// check on the write hot path. Kept in step by `mark` (insert only)
    /// and the removal methods; approximate under concurrent mutation,
    /// which a soft bound tolerates.
    size: AtomicUsize,
    max_entries: usize,
}

/// Per-partition summary for the prune loop, gathered in one pass.
#[derive(Debug, Clone, Copy)]
pub struct PartitionMarks {
    pub count: usize,
    pub max_offset: i64,
}

impl DirtyIndex {
    pub fn new(max_entries: usize) -> Self {
        Self {
            map: DashMap::new(),
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
    /// clobbering a newer mark with an older replayed one.
    pub fn mark(&self, key: PersonCacheKey, mark: DirtyMark) {
        match self.map.entry(key) {
            Entry::Occupied(mut entry) => {
                if mark.offset > entry.get().offset {
                    *entry.get_mut() = mark;
                }
            }
            Entry::Vacant(entry) => {
                entry.insert(mark);
                self.size.fetch_add(1, Ordering::Relaxed);
            }
        }
    }

    pub fn get(&self, key: &PersonCacheKey) -> Option<DirtyMark> {
        self.map.get(key).map(|entry| *entry.value())
    }

    /// Drop every mark the writer has applied, across all partitions, in a
    /// single pass: a mark is applied once its partition's committed offset
    /// (absent = no commit yet) has moved past it. Returns how many were
    /// pruned.
    pub fn prune_applied(&self, committed: &HashMap<u32, i64>) -> usize {
        let mut removed = 0;
        self.map.retain(|_, mark| {
            let applied = committed
                .get(&mark.partition)
                .is_some_and(|c| mark.offset < *c);
            if applied {
                removed += 1;
            }
            !applied
        });
        self.size.fetch_sub(removed, Ordering::Relaxed);
        removed
    }

    /// Drop marks on `partition` that the writer has applied (offset below
    /// its committed offset). Returns how many were pruned.
    pub fn prune_partition(&self, partition: u32, committed: i64) -> usize {
        self.prune_applied(&HashMap::from([(partition, committed)]))
    }

    /// Drop every mark on `partition` — used when the partition is released
    /// to another owner, whose warming rebuilds its own marks.
    pub fn clear_partition(&self, partition: u32) -> usize {
        let mut removed = 0;
        self.map.retain(|_, mark| {
            let keep = mark.partition != partition;
            if !keep {
                removed += 1;
            }
            keep
        });
        self.size.fetch_sub(removed, Ordering::Relaxed);
        removed
    }

    /// Per-partition mark counts and highest offsets, in one pass over the
    /// index — the prune loop's whole read side. Anything per-partition
    /// that iterated the map separately would go quadratic exactly when
    /// the index is large (a lagging writer).
    pub fn partition_marks(&self) -> HashMap<u32, PartitionMarks> {
        let mut stats: HashMap<u32, PartitionMarks> = HashMap::new();
        for entry in self.map.iter() {
            let s = stats.entry(entry.partition).or_insert(PartitionMarks {
                count: 0,
                max_offset: i64::MIN,
            });
            s.count += 1;
            s.max_offset = s.max_offset.max(entry.offset);
        }
        stats
    }

    /// Highest marked offset for a partition, if any.
    pub fn max_offset(&self, partition: u32) -> Option<i64> {
        self.partition_marks().get(&partition).map(|s| s.max_offset)
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

    fn mark(offset: i64, partition: u32) -> DirtyMark {
        DirtyMark {
            version: offset,
            offset,
            partition,
        }
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
    fn partition_marks_reflect_contents_in_one_pass() {
        let index = DirtyIndex::new(1_000);
        index.mark(key(1), mark(4, 0));
        index.mark(key(2), mark(9, 0));
        index.mark(key(3), mark(2, 7));

        let stats = index.partition_marks();
        assert_eq!(stats.len(), 2);
        assert_eq!(stats[&0].count, 2);
        assert_eq!(stats[&0].max_offset, 9);
        assert_eq!(stats[&7].count, 1);
        assert_eq!(index.max_offset(7), Some(2));
        assert_eq!(index.max_offset(3), None);
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
