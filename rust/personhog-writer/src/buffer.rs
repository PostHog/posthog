use std::collections::hash_map::Entry;
use std::collections::HashMap;

use metrics::counter;
use personhog_proto::personhog::types::v1::Person;

/// A buffered person plus the partition its latest message arrived on, so
/// drains can select whole partitions.
struct Buffered {
    person: Person,
    partition: i32,
}

/// A partition-complete slice of the buffer, ready to flush. Offsets cover
/// exactly the partitions whose entries were drained, so committing them
/// can never skip past a person still sitting in the buffer.
pub struct DrainedBatch {
    pub persons: Vec<Person>,
    /// Max offset seen per drained partition.
    pub offsets: HashMap<i32, i64>,
    /// Oldest message timestamp across the drained partitions (millis
    /// since epoch), for end-to-end latency measurement.
    pub oldest_message_ts_ms: Option<i64>,
}

/// In-memory dedup buffer keyed by (team_id, person_id).
/// Later messages for the same person overwrite earlier ones.
pub struct PersonBuffer {
    entries: HashMap<(i64, i64), Buffered>,
    /// Max offset seen per partition for offset commits.
    offsets: HashMap<i32, i64>,
    /// Oldest message timestamp per partition with buffered entries.
    oldest_ts_ms: HashMap<i32, i64>,
    capacity: usize,
}

impl PersonBuffer {
    pub fn new(capacity: usize) -> Self {
        Self {
            entries: HashMap::new(),
            offsets: HashMap::new(),
            oldest_ts_ms: HashMap::new(),
            capacity,
        }
    }

    /// Insert a person into the buffer. Later messages for the same person
    /// overwrite earlier ones -- Kafka partition ordering guarantees the
    /// latest version always arrives last.
    pub fn insert(&mut self, person: Person, partition: i32, offset: i64, ts_ms: Option<i64>) {
        self.offsets
            .entry(partition)
            .and_modify(|o| {
                if offset > *o {
                    *o = offset;
                }
            })
            .or_insert(offset);

        if let Some(ts_ms) = ts_ms {
            self.oldest_ts_ms
                .entry(partition)
                .and_modify(|t| {
                    if ts_ms < *t {
                        *t = ts_ms;
                    }
                })
                .or_insert(ts_ms);
        }

        let key = (person.team_id, person.id);
        match self.entries.entry(key) {
            Entry::Occupied(mut e) => {
                e.insert(Buffered { person, partition });
                counter!("personhog_writer_messages_deduped_total").increment(1);
            }
            Entry::Vacant(e) => {
                e.insert(Buffered { person, partition });
            }
        }
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    pub fn is_full(&self) -> bool {
        self.entries.len() >= self.capacity
    }

    /// Get the current offset for a partition, if tracked.
    pub fn partition_offset(&self, partition: i32) -> Option<i64> {
        self.offsets.get(&partition).copied()
    }

    /// Drain whole partitions — oldest buffered message first — until at
    /// least `max_rows` persons are collected or the buffer is empty. A
    /// partition is never split: its max offset is only safe to commit once
    /// every buffered person from it is flushed, so a single partition can
    /// exceed `max_rows` on its own. Returns `None` on an empty buffer.
    pub fn drain_up_to(&mut self, max_rows: usize) -> Option<DrainedBatch> {
        if self.entries.is_empty() {
            return None;
        }

        let mut keys_by_partition: HashMap<i32, Vec<(i64, i64)>> = HashMap::new();
        for (key, buffered) in &self.entries {
            keys_by_partition
                .entry(buffered.partition)
                .or_default()
                .push(*key);
        }

        // Oldest-first keeps the e2e latency tail short; the partition id
        // tiebreak makes drain order deterministic.
        let mut partitions: Vec<i32> = keys_by_partition.keys().copied().collect();
        partitions
            .sort_unstable_by_key(|p| (self.oldest_ts_ms.get(p).copied().unwrap_or(i64::MAX), *p));

        let mut persons = Vec::new();
        let mut offsets = HashMap::new();
        let mut oldest_message_ts_ms: Option<i64> = None;

        for partition in partitions {
            if persons.len() >= max_rows {
                break;
            }
            for key in &keys_by_partition[&partition] {
                let buffered = self.entries.remove(key).expect("key collected above");
                persons.push(buffered.person);
            }
            if let Some(offset) = self.offsets.remove(&partition) {
                offsets.insert(partition, offset);
            }
            if let Some(ts) = self.oldest_ts_ms.remove(&partition) {
                oldest_message_ts_ms = Some(oldest_message_ts_ms.map_or(ts, |cur| cur.min(ts)));
            }
        }

        Some(DrainedBatch {
            persons,
            offsets,
            oldest_message_ts_ms,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_person(team_id: i64, person_id: i64, version: i64) -> Person {
        Person {
            id: person_id,
            team_id,
            uuid: format!("uuid-{team_id}-{person_id}"),
            properties: vec![],
            properties_last_updated_at: vec![],
            properties_last_operation: vec![],
            created_at: 1700000000,
            version,
            is_identified: false,
            is_user_id: None,
            last_seen_at: None,
            is_deleted: false,
        }
    }

    #[test]
    fn insert_and_drain() {
        let mut buf = PersonBuffer::new(100);
        buf.insert(make_person(1, 42, 1), 0, 0, None);
        buf.insert(make_person(1, 43, 1), 0, 1, None);

        assert_eq!(buf.len(), 2);

        let batch = buf.drain_up_to(usize::MAX).unwrap();
        assert_eq!(batch.persons.len(), 2);
        assert_eq!(batch.offsets[&0], 1);
        assert_eq!(buf.len(), 0);
        assert!(buf.drain_up_to(usize::MAX).is_none());
    }

    #[test]
    fn dedup_keeps_latest_message() {
        let mut buf = PersonBuffer::new(100);
        buf.insert(make_person(1, 42, 1), 0, 0, None);
        buf.insert(make_person(1, 42, 2), 0, 1, None);
        buf.insert(make_person(1, 42, 3), 0, 2, None);

        assert_eq!(buf.len(), 1);

        let batch = buf.drain_up_to(usize::MAX).unwrap();
        assert_eq!(batch.persons[0].version, 3);
    }

    #[test]
    fn is_full_respects_capacity() {
        let mut buf = PersonBuffer::new(2);
        assert!(!buf.is_full());

        buf.insert(make_person(1, 1, 1), 0, 0, None);
        assert!(!buf.is_full());

        buf.insert(make_person(1, 2, 1), 0, 1, None);
        assert!(buf.is_full());
    }

    #[test]
    fn tracks_max_offset_per_partition() {
        let mut buf = PersonBuffer::new(100);
        buf.insert(make_person(1, 1, 1), 0, 10, None);
        buf.insert(make_person(1, 2, 1), 0, 5, None);
        buf.insert(make_person(1, 3, 1), 1, 3, None);

        assert_eq!(buf.partition_offset(0), Some(10));
        assert_eq!(buf.partition_offset(1), Some(3));
        assert_eq!(buf.partition_offset(2), None);

        let batch = buf.drain_up_to(usize::MAX).unwrap();
        assert_eq!(batch.offsets[&0], 10);
        assert_eq!(batch.offsets[&1], 3);
    }

    #[test]
    fn capped_drain_takes_whole_partitions_and_only_their_offsets() {
        let mut buf = PersonBuffer::new(100);
        // Partition 0 is older (ts 100), partition 1 newer (ts 200).
        buf.insert(make_person(1, 1, 1), 0, 10, Some(100));
        buf.insert(make_person(1, 2, 1), 0, 11, Some(150));
        buf.insert(make_person(1, 3, 1), 1, 20, Some(200));
        buf.insert(make_person(1, 4, 1), 1, 21, Some(250));

        let batch = buf.drain_up_to(2).unwrap();
        assert_eq!(batch.persons.len(), 2);
        assert!(batch.persons.iter().all(|p| p.id == 1 || p.id == 2));
        assert_eq!(batch.offsets.len(), 1);
        assert_eq!(batch.offsets[&0], 11);
        assert_eq!(batch.oldest_message_ts_ms, Some(100));

        // Partition 1 stays fully buffered, offset uncommitted.
        assert_eq!(buf.len(), 2);
        assert_eq!(buf.partition_offset(1), Some(21));
        assert_eq!(buf.partition_offset(0), None);

        let rest = buf.drain_up_to(2).unwrap();
        assert_eq!(rest.persons.len(), 2);
        assert_eq!(rest.offsets[&1], 21);
        assert_eq!(rest.oldest_message_ts_ms, Some(200));
        assert!(buf.is_empty());
    }

    #[test]
    fn capped_drain_never_splits_a_partition() {
        let mut buf = PersonBuffer::new(100);
        for id in 1..=5 {
            buf.insert(make_person(1, id, 1), 0, id, None);
        }

        let batch = buf.drain_up_to(2).unwrap();
        assert_eq!(batch.persons.len(), 5);
        assert_eq!(batch.offsets[&0], 5);
        assert!(buf.is_empty());
    }

    #[test]
    fn capped_drain_prefers_oldest_partition() {
        let mut buf = PersonBuffer::new(100);
        buf.insert(make_person(1, 1, 1), 3, 0, Some(500));
        buf.insert(make_person(1, 2, 1), 7, 0, Some(100));

        let batch = buf.drain_up_to(1).unwrap();
        assert_eq!(batch.persons[0].id, 2);
        assert_eq!(batch.offsets.len(), 1);
        assert_eq!(batch.offsets[&7], 0);
    }
}
