use std::collections::hash_map::Entry;
use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use metrics::counter;
use personhog_proto::personhog::types::v1::Person;

use crate::kafka::Source;

/// A buffered person plus the partition its latest message arrived on, so
/// drains can select whole partitions.
pub struct BufferedPerson {
    pub person: Person,
    pub source: Source,
}

/// A partition-complete slice of the buffer, ready to flush. Offsets cover
/// exactly the partitions whose entries were drained, so committing them
/// can never skip past a person still sitting in the buffer.
pub struct DrainedBatch {
    pub persons: Vec<BufferedPerson>,
    /// Max offset seen per drained partition.
    pub offsets: HashMap<Source, i64>,
    /// Oldest message timestamp across the drained partitions (millis
    /// since epoch), for end-to-end latency measurement.
    pub oldest_message_ts_ms: Option<i64>,
}

/// In-memory dedup buffer keyed by (team_id, person_id).
/// Later messages for the same person overwrite earlier ones.
pub struct PersonBuffer {
    entries: HashMap<(i64, i64), BufferedPerson>,
    /// Max offset seen per partition for offset commits.
    offsets: HashMap<Source, i64>,
    /// Oldest message timestamp per partition with buffered entries.
    oldest_ts_ms: HashMap<Source, i64>,
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
    pub fn insert(&mut self, person: Person, source: Source, offset: i64, ts_ms: Option<i64>) {
        self.offsets
            .entry(source.clone())
            .and_modify(|o| {
                if offset > *o {
                    *o = offset;
                }
            })
            .or_insert(offset);

        if let Some(ts_ms) = ts_ms {
            self.oldest_ts_ms
                .entry(source.clone())
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
                e.insert(BufferedPerson { person, source });
                counter!("personhog_writer_messages_deduped_total").increment(1);
            }
            Entry::Vacant(e) => {
                e.insert(BufferedPerson { person, source });
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
    pub fn source_offset(&self, source: &Source) -> Option<i64> {
        self.offsets.get(source).copied()
    }

    pub fn remove_sources(&mut self, sources: &[Source]) -> usize {
        let revoked: HashSet<&Source> = sources.iter().collect();
        let before = self.entries.len();
        self.entries
            .retain(|_, buffered| !revoked.contains(&buffered.source));
        for source in &revoked {
            self.offsets.remove(*source);
            self.oldest_ts_ms.remove(*source);
        }
        before - self.entries.len()
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

        let mut keys_by_source: HashMap<Source, Vec<(i64, i64)>> = HashMap::new();
        for (key, buffered) in &self.entries {
            keys_by_source
                .entry(buffered.source.clone())
                .or_default()
                .push(*key);
        }

        // Oldest-first keeps the e2e latency tail short; the partition id
        // tiebreak makes drain order deterministic.
        let mut sources: Vec<Source> = keys_by_source.keys().cloned().collect();
        sources.sort_unstable_by_key(|s| {
            (
                self.oldest_ts_ms.get(s).copied().unwrap_or(i64::MAX),
                s.partition,
                Arc::clone(&s.topic),
            )
        });

        let mut persons = Vec::new();
        let mut offsets = HashMap::new();
        let mut oldest_message_ts_ms: Option<i64> = None;

        for source in sources {
            if persons.len() >= max_rows {
                break;
            }
            for key in &keys_by_source[&source] {
                let buffered = self.entries.remove(key).expect("key collected above");
                persons.push(buffered);
            }
            if let Some(offset) = self.offsets.remove(&source) {
                offsets.insert(source.clone(), offset);
            }
            if let Some(ts) = self.oldest_ts_ms.remove(&source) {
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

    fn src(partition: i32) -> Source {
        Source {
            topic: Arc::from("personhog_updates"),
            partition,
        }
    }

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
        buf.insert(make_person(1, 42, 1), src(0), 0, None);
        buf.insert(make_person(1, 43, 1), src(0), 1, None);

        assert_eq!(buf.len(), 2);

        let batch = buf.drain_up_to(usize::MAX).unwrap();
        assert_eq!(batch.persons.len(), 2);
        assert_eq!(batch.offsets[&src(0)], 1);
        assert_eq!(buf.len(), 0);
        assert!(buf.drain_up_to(usize::MAX).is_none());
    }

    #[test]
    fn dedup_keeps_latest_message() {
        let mut buf = PersonBuffer::new(100);
        buf.insert(make_person(1, 42, 1), src(0), 0, None);
        buf.insert(make_person(1, 42, 2), src(0), 1, None);
        buf.insert(make_person(1, 42, 3), src(0), 2, None);

        assert_eq!(buf.len(), 1);

        let batch = buf.drain_up_to(usize::MAX).unwrap();
        assert_eq!(batch.persons[0].person.version, 3);
    }

    #[test]
    fn is_full_respects_capacity() {
        let mut buf = PersonBuffer::new(2);
        assert!(!buf.is_full());

        buf.insert(make_person(1, 1, 1), src(0), 0, None);
        assert!(!buf.is_full());

        buf.insert(make_person(1, 2, 1), src(0), 1, None);
        assert!(buf.is_full());
    }

    #[test]
    fn tracks_max_offset_per_partition() {
        let mut buf = PersonBuffer::new(100);
        buf.insert(make_person(1, 1, 1), src(0), 10, None);
        buf.insert(make_person(1, 2, 1), src(0), 5, None);
        buf.insert(make_person(1, 3, 1), src(1), 3, None);

        assert_eq!(buf.source_offset(&src(0)), Some(10));
        assert_eq!(buf.source_offset(&src(1)), Some(3));
        assert_eq!(buf.source_offset(&src(2)), None);

        let batch = buf.drain_up_to(usize::MAX).unwrap();
        assert_eq!(batch.offsets[&src(0)], 10);
        assert_eq!(batch.offsets[&src(1)], 3);
    }

    #[test]
    fn capped_drain_takes_whole_partitions_and_only_their_offsets() {
        let mut buf = PersonBuffer::new(100);
        // Partition 0 is older (ts 100), partition 1 newer (ts 200).
        buf.insert(make_person(1, 1, 1), src(0), 10, Some(100));
        buf.insert(make_person(1, 2, 1), src(0), 11, Some(150));
        buf.insert(make_person(1, 3, 1), src(1), 20, Some(200));
        buf.insert(make_person(1, 4, 1), src(1), 21, Some(250));

        let batch = buf.drain_up_to(2).unwrap();
        assert_eq!(batch.persons.len(), 2);
        assert!(batch
            .persons
            .iter()
            .all(|p| p.person.id == 1 || p.person.id == 2));
        assert_eq!(batch.offsets.len(), 1);
        assert_eq!(batch.offsets[&src(0)], 11);
        assert_eq!(batch.oldest_message_ts_ms, Some(100));

        // Partition 1 stays fully buffered, offset uncommitted.
        assert_eq!(buf.len(), 2);
        assert_eq!(buf.source_offset(&src(1)), Some(21));
        assert_eq!(buf.source_offset(&src(0)), None);

        let rest = buf.drain_up_to(2).unwrap();
        assert_eq!(rest.persons.len(), 2);
        assert_eq!(rest.offsets[&src(1)], 21);
        assert_eq!(rest.oldest_message_ts_ms, Some(200));
        assert!(buf.is_empty());
    }

    #[test]
    fn capped_drain_never_splits_a_partition() {
        let mut buf = PersonBuffer::new(100);
        for id in 1..=5 {
            buf.insert(make_person(1, id, 1), src(0), id, None);
        }

        let batch = buf.drain_up_to(2).unwrap();
        assert_eq!(batch.persons.len(), 5);
        assert_eq!(batch.offsets[&src(0)], 5);
        assert!(buf.is_empty());
    }

    #[test]
    fn capped_drain_prefers_oldest_partition() {
        let mut buf = PersonBuffer::new(100);
        buf.insert(make_person(1, 1, 1), src(3), 0, Some(500));
        buf.insert(make_person(1, 2, 1), src(7), 0, Some(100));

        let batch = buf.drain_up_to(1).unwrap();
        assert_eq!(batch.persons[0].person.id, 2);
        assert_eq!(batch.offsets.len(), 1);
        assert_eq!(batch.offsets[&src(7)], 0);
    }

    #[test]
    fn remove_sources_drops_rows_offsets_and_timestamps() {
        let mut buf = PersonBuffer::new(100);
        buf.insert(make_person(1, 1, 1), src(0), 10, Some(100));
        buf.insert(make_person(1, 2, 1), src(1), 20, Some(50));
        buf.insert(make_person(1, 3, 1), src(1), 21, Some(60));

        assert_eq!(buf.remove_sources(&[src(1)]), 2);
        assert_eq!(buf.len(), 1);
        assert_eq!(buf.source_offset(&src(1)), None);

        let batch = buf.drain_up_to(usize::MAX).unwrap();
        assert_eq!(
            batch
                .persons
                .iter()
                .map(|p| p.person.id)
                .collect::<Vec<_>>(),
            vec![1]
        );
        assert_eq!(batch.offsets, HashMap::from([(src(0), 10)]));
        assert_eq!(batch.oldest_message_ts_ms, Some(100));
    }
}
